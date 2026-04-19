#!/usr/bin/env python3
"""
IPTV Player with MPV, M3U8 parsing, Channel Grouping, Logos, and EPG Support.
Uses custom m3u_parser module with m3u8 library and custom_tags_parser.
"""

import sys
import os
import subprocess
import time
from datetime import datetime
from collections import OrderedDict

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
                             QComboBox, QLabel, QSplitter, QTreeWidget, QTreeWidgetItem,
                             QStatusBar, QMessageBox, QFrame, QTextEdit, QFileDialog)
from PyQt6.QtCore import QUrl, Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from m3u_parser import load_playlist
from epg_manager import EpgManager, EpgProgram


class LogoLoader(QObject):
    """Helper to load logos asynchronously."""
    logo_loaded = pyqtSignal(str, QPixmap)

    def __init__(self):
        super().__init__()
        self.manager = QNetworkAccessManager()
        self.manager.finished.connect(self.on_finished)
        self.pending_urls = {}

    def load_logo(self, channel_name, url):
        if not url:
            return
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"IPTV-Player/1.0")
        reply = self.manager.get(request)
        self.pending_urls[reply] = channel_name

    def on_finished(self, reply):
        channel_name = self.pending_urls.pop(reply, None)
        if reply.error() or not channel_name:
            reply.deleteLater()
            return
        
        data = reply.readAll().data()
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        
        if not pixmap.isNull():
            scaled = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.logo_loaded.emit(channel_name, scaled)
        
        reply.deleteLater()


class IPTVPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Player with EPG")
        self.setGeometry(100, 100, 1200, 800)

        self.channels = []
        self.channel_map = {}
        self.current_channel = None
        self.mpv_process = None
        self.logo_loader = LogoLoader()
        self.epg_manager = EpgManager()
        self.epg_data = {}

        # Timer for periodic EPG highlight updates
        self.epg_timer = QTimer()
        self.epg_timer.timeout.connect(self.update_epg_highlight)
        self.epg_timer.start(30000)  # Update every 30 seconds

        self.epg_manager.loader.epg_loaded.connect(self.on_epg_loaded)
        self.epg_manager.loader.error_occurred.connect(lambda msg: self.statusBar().showMessage(f"EPG Error: {msg}", 5000))
        self.logo_loader.logo_loaded.connect(self.update_channel_logo)

        self.init_ui()
        self.load_sample_playlist()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        
        self.video_label = QLabel("MPV Video Window\n(External)")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; color: #fff; min-height: 300px;")
        left_layout.addWidget(self.video_label)

        controls_layout = QHBoxLayout()
        
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.play_channel)
        controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_channel)
        controls_layout.addWidget(self.stop_btn)

        self.source_label = QLabel("Source:")
        controls_layout.addWidget(self.source_label)

        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self.switch_source)
        controls_layout.addWidget(self.source_combo)
        controls_layout.addStretch()

        left_layout.addLayout(controls_layout)

        epg_label = QLabel("Electronic Program Guide (EPG)")
        epg_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        left_layout.addWidget(epg_label)

        # EPG Table (Scrollable with highlighting)
        self.epg_table = QTableWidget()
        self.epg_table.setColumnCount(4)
        self.epg_table.setHorizontalHeaderLabels(["Start", "End", "Title", "Description"])
        self.epg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.epg_table.verticalHeader().setVisible(False)
        self.epg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.epg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.epg_table.setMaximumHeight(200)
        left_layout.addWidget(self.epg_table)

        left_layout.addStretch()

        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        
        load_btn = QPushButton("Load M3U File")
        load_btn.clicked.connect(self.load_m3u_file)
        right_layout.addWidget(load_btn)

        self.channel_tree = QTreeWidget()
        self.channel_tree.setHeaderLabels(["Channel Group"])
        self.channel_tree.itemClicked.connect(self.on_channel_selected)
        right_layout.addWidget(self.channel_tree)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_frame)
        splitter.addWidget(right_frame)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)

        self.statusBar().showMessage("Ready")

    def load_sample_playlist(self):
        # Use the new m3u_parser module to parse sample content
        # First write sample to a temp file since our parser expects a file path
        import tempfile
        sample_content = '''#EXTM3U x-tvg-url="https://raw.githubusercontent.com/iptv-org/epg/master/epg.xml"
#EXTINF:-1 tvg-id="CNN.us" tvg-name="CNN" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/thumb/6/66/CNN_International_logo.svg/200px-CNN_International_logo.svg.png" group-title="News",CNN International
http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4
#EXTINF:-1 tvg-id="BBCOne.uk" tvg-name="BBC One" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/BBC_One_logo_2021.svg/200px-BBC_One_logo_2021.svg.png" group-title="News",BBC One
http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4
#EXTINF:-1 tvg-id="Discovery.us" tvg-name="Discovery" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/thumb/7/77/Discovery_Channel_logo.svg/200px-Discovery_Channel_logo.svg.png" group-title="Documentary",Discovery Channel
http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4
http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.m3u8', delete=False, encoding='utf-8') as f:
            f.write(sample_content)
            temp_path = f.name
        
        try:
            channels_data, epg_url = load_playlist(temp_path)
            self.populate_channels(channels_data, epg_url)
        finally:
            os.unlink(temp_path)
        
        self.statusBar().showMessage("Sample playlist loaded. EPG loading in background...")

    def load_m3u_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load M3U Playlist", "", "M3U Files (*.m3u *.m3u8);;All Files (*)")
        if file_path:
            try:
                channels_data, epg_url = load_playlist(file_path)
                self.populate_channels(channels_data, epg_url)
                self.statusBar().showMessage(f"Loaded: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load file: {e}")

    def populate_channels(self, channels_data, epg_url):
        """Populate the channel tree from parsed channel data."""
        self.channels = []
        self.channel_map = {}
        self.channel_tree.clear()
        
        # Load EPG if URL is provided
        if epg_url:
            self.statusBar().showMessage(f"EPG URL found: {epg_url}. Loading...")
            self.epg_manager.load_from_url(epg_url)
        
        groups = {}
        
        for ch_data in channels_data:
            name = ch_data.get('name', '')
            logo_url = ch_data.get('logo')
            group_title = ch_data.get('group', 'Uncategorized')
            tvg_id = ch_data.get('tvg_id')
            sources_list = ch_data.get('sources', [])
            vlcopts = ch_data.get('vlcopts', [])
            encryption = ch_data.get('encryption')
            
            if name and sources_list:
                # Check if channel already exists (multiple URLs for same channel name)
                if name in self.channel_map:
                    # Add as additional source to existing channel
                    existing = self.channel_map[name]
                    existing.sources.extend(sources_list)
                    # Merge vlcopts if new ones exist
                    if vlcopts:
                        existing.vlcopts.extend(vlcopts)
                    # Update encryption if provided
                    if encryption:
                        existing.encryption = encryption
                else:
                    self.add_channel(name, logo_url, group_title, tvg_id, sources_list, groups, vlcopts, encryption)
        
        self.channel_tree.expandAll()

    def add_channel(self, name, logo_url, group_title, tvg_id, sources, groups_dict, vlcopts=None, encryption=None):
        if not name or not sources:
            return

        channel = ChannelItem(name, logo_url, group_title, tvg_id, sources, vlcopts, encryption)
        self.channels.append(channel)
        self.channel_map[name] = channel

        group_name = group_title if group_title else "Ungrouped"
        
        if group_name not in groups_dict:
            group_item = QTreeWidgetItem(self.channel_tree)
            group_item.setText(0, group_name)
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsEnabled)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            groups_dict[group_name] = group_item
        
        parent = groups_dict[group_name]
        child = QTreeWidgetItem(parent)
        child.setText(0, name)
        child.setData(0, Qt.ItemDataRole.UserRole, name)
        
        if logo_url:
            self.logo_loader.load_logo(name, logo_url)

    def update_channel_logo(self, channel_name, pixmap):
        items = self.channel_tree.findItems(channel_name, Qt.MatchFlag.MatchRecursive)
        for item in items:
            if item.parent() is not None:
                item.setIcon(0, QIcon(pixmap))
                break

    def on_channel_selected(self, item, column):
        if item.parent() is None:
            return
        
        channel_name = item.data(0, Qt.ItemDataRole.UserRole)
        channel = self.channel_map.get(channel_name)
        
        if channel:
            self.current_channel = channel
            self.statusBar().showMessage(f"Selected: {channel.name}")
            
            self.source_combo.clear()
            for i, src in enumerate(channel.sources):
                self.source_combo.addItem(f"Source {i+1}")
            self.source_combo.setCurrentIndex(channel.current_source_index)
            
            self.update_epg_display(channel)

    def update_epg_display(self, channel):
        self.epg_table.setRowCount(0)  # Clear table
        
        if not channel.tvg_id:
            self.epg_table.setRowCount(1)
            self.epg_table.setItem(0, 0, QTableWidgetItem("No EPG ID (tvg-id) defined"))
            self.epg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            return

        programs = self.epg_manager.get_programs(channel.tvg_id)
        
        if not programs:
            self.epg_table.setRowCount(1)
            self.epg_table.setItem(0, 0, QTableWidgetItem(f"No program guide found for ID: {channel.tvg_id}"))
            return

        now = datetime.now()
        current_row_index = -1
        
        self.epg_table.setRowCount(len(programs))
        
        for row_idx, prog in enumerate(programs):
            start_str = str(prog.start) if hasattr(prog, 'start') else prog.get('start', '')
            end_str = str(prog.end) if hasattr(prog, 'end') else prog.get('end', '')
            title = prog.title if hasattr(prog, 'title') else prog.get('title', 'Unknown')
            description = prog.description if hasattr(prog, 'description') else prog.get('desc', '')
            
            # Format times
            start_time = self.format_epg_time(start_str)
            end_time = self.format_epg_time(end_str)
            
            # Parse actual datetime for comparison
            try:
                start_dt = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
                end_dt = datetime.strptime(end_str[:14], "%Y%m%d%H%M%S") if end_str else None
            except (ValueError, IndexError):
                start_dt = None
                end_dt = None
            
            # Check if this is the current program
            is_current = False
            if start_dt and end_dt:
                if start_dt <= now < end_dt:
                    is_current = True
                    current_row_index = row_idx
            elif start_dt and not end_dt:
                # Open-ended program
                if start_dt <= now:
                    is_current = True
                    current_row_index = row_idx
            
            # Populate row
            self.epg_table.setItem(row_idx, 0, QTableWidgetItem(start_time))
            self.epg_table.setItem(row_idx, 1, QTableWidgetItem(end_time))
            self.epg_table.setItem(row_idx, 2, QTableWidgetItem(title))
            self.epg_table.setItem(row_idx, 3, QTableWidgetItem(description))
            
            # Highlight current program
            if is_current:
                self.highlight_current_program(row_idx)
        
        # Scroll to current program
        if current_row_index >= 0:
            self.epg_table.scrollToItem(self.epg_table.item(current_row_index, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
            self.epg_table.selectRow(current_row_index)
    
    def highlight_current_program(self, row_idx):
        """Highlight the current program with yellow background and bold text."""
        for col in range(4):
            item = self.epg_table.item(row_idx, col)
            if item:
                item.setBackground(QColor(255, 255, 153))  # Light yellow
                font = item.font()
                font.setBold(True)
                item.setFont(font)

    def update_epg_highlight(self):
        """Update EPG highlight every 30 seconds to reflect current program."""
        if self.current_channel:
            self.update_epg_display(self.current_channel)

    def on_epg_loaded(self, channel_id, programs):
        # Cache is handled by EpgManager internally
        self.statusBar().showMessage(f"EPG Data Loaded for {channel_id}")
        if self.current_channel and self.current_channel.tvg_id == channel_id:
            self.update_epg_display(self.current_channel)

    def switch_source(self, index):
        if self.current_channel:
            self.current_channel.current_source_index = index
            if self.mpv_process and self.mpv_process.poll() is None:
                self.play_channel()

    def play_channel(self):
        if not self.current_channel:
            QMessageBox.warning(self, "Warning", "No channel selected")
            return

        url = self.current_channel.current_source
        if not url:
            return

        self.stop_channel()

        # Build mpv command with VLC options converted to mpv equivalents and encryption support
        mpv_args = ["mpv", "--no-terminal", "--force-window"]
        
        # Add VLC options as mpv equivalents
        for vlcopt in self.current_channel.vlcopts:
            for key, value in vlcopt.items():
                opt_name, opt_value = self.vlcopt_to_mpv_opt(key, value)
                if opt_name and opt_value:
                    mpv_args.append(opt_name)
                    mpv_args.append(opt_value)
        
        # Add HLS decryption options if encryption is present
        if self.current_channel.encryption:
            enc = self.current_channel.encryption
            method = enc.get('method', '').upper()
            uri = enc.get('uri')
            iv = enc.get('iv')
            
            if method == 'AES-128' and uri:
                # mpv can handle HLS encryption automatically via the playlist
                # But we can also explicitly set options if needed
                # For AES-128, mpv will fetch the key from the URI automatically
                # If IV is specified, pass it explicitly
                if iv:
                    mpv_args.append(f'--hls-aes-iv={iv}')
                # Note: mpv automatically handles key fetching from URI in HLS streams
        
        mpv_args.append(url)

        try:
            self.mpv_process = subprocess.Popen(
                mpv_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.statusBar().showMessage(f"Playing: {self.current_channel.name}")
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "MPV player not found. Please install mpv.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start MPV: {e}")

    def vlcopt_to_mpv_opt(self, key: str, value: str):
        """
        Convert VLC options to mpv equivalent options.
        Common mappings:
        - http-user-agent -> --user-agent
        - http-referrer -> --referrer
        - program -> --program (for MPEG-TS)
        
        Returns tuple of (option_name, value) or (None, None) if no conversion.
        """
        key_lower = key.lower()
        
        # Direct mappings from VLC to mpv
        if key_lower in ['http-user-agent', 'user-agent']:
            return '--user-agent', value
        elif key_lower in ['http-referrer', 'referrer']:
            return '--referrer', value
        elif key_lower == 'program':
            return '--program', value
        elif key_lower in ['network-caching', 'live-caching']:
            try:
                cache_secs = int(value) / 1000.0
                return '--cache-secs', str(cache_secs)
            except ValueError:
                return '--cache-secs', value
        
        # For unknown options, try to pass them as --{key}={value}
        if value and value != 'true':
            return f'--{key}', value
        
        return None, None

    def stop_channel(self):
        if self.mpv_process:
            self.mpv_process.terminate()
            try:
                self.mpv_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.mpv_process.kill()
            self.mpv_process = None
            self.statusBar().showMessage("Stopped")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IPTVPlayer()
    window.show()
    sys.exit(app.exec())
