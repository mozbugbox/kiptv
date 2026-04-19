"""
EPG Manager Module

Handles EPG loading, parsing, caching, and retrieval.
Includes thread-safe LRU cache with 3-hour expiration and 100-entry limit.
"""

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from xml.etree import ElementTree as ET
import requests
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class EpgProgram:
    """Represents a single EPG program entry."""
    start: int
    end: int
    title: str
    description: str = ""
    channel: str = ""


class EpgCache:
    """
    Thread-safe LRU cache for EPG data.
    
    Features:
    - Maximum 100 entries
    - 3-hour expiration time
    - LRU eviction policy
    - Thread-safe operations using RLock
    """
    
    def __init__(self, max_entries: int = 100, ttl_hours: int = 3):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_hours * 3600
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, channel_id: str) -> Optional[List[EpgProgram]]:
        """
        Get cached EPG programs for a channel.
        
        Returns None if not found or expired.
        Updates LRU order on successful hit.
        """
        with self._lock:
            if channel_id not in self._cache:
                return None
            
            entry = self._cache[channel_id]
            current_time = time.time()
            
            # Check expiration
            if current_time - entry['timestamp'] > self.ttl_seconds:
                del self._cache[channel_id]
                return None
            
            # Update LRU order (move to end)
            self._cache.move_to_end(channel_id)
            return entry['programs']
    
    def set(self, channel_id: str, programs: List[EpgProgram]) -> None:
        """
        Cache EPG programs for a channel.
        
        Evicts oldest entries if max capacity is reached.
        """
        with self._lock:
            current_time = time.time()
            
            # If key exists, remove it first to update position
            if channel_id in self._cache:
                del self._cache[channel_id]
            
            # Evict if at capacity
            while len(self._cache) >= self.max_entries:
                # Remove oldest (first item)
                self._cache.popitem(last=False)
            
            self._cache[channel_id] = {
                'programs': programs,
                'timestamp': current_time
            }
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """Return current number of cached entries."""
        with self._lock:
            return len(self._cache)


class EpgLoader(QObject):
    """
    Handles loading and parsing of XMLTV EPG data.
    
    Features:
    - Asynchronous loading via requests
    - XMLTV format parsing
    - Integration with EpgCache
    - Thread-safe operations
    """
    
    epg_loaded = pyqtSignal(str, list)  # channel_id, programs
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.cache = EpgCache(max_entries=100, ttl_hours=3)
        self._live_data: Dict[str, List[EpgProgram]] = {}
        self._lock = threading.RLock()
    
    def load_epg(self, url: str) -> None:
        """
        Load EPG data from URL asynchronously.
        
        Parses XMLTV format and caches results.
        Emits epg_loaded signal for each channel parsed.
        """
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            self._parse_xmltv(response.text)
        except Exception as e:
            self.error_occurred.emit(f"Failed to load EPG: {str(e)}")
    
    def _parse_xmltv(self, xml_content: str) -> None:
        """Parse XMLTV content and populate cache."""
        try:
            root = ET.fromstring(xml_content)
            channels: Dict[str, str] = {}
            programs: Dict[str, List[EpgProgram]] = {}
            
            # Parse channel definitions
            for channel_elem in root.findall('.//channel'):
                channel_id = channel_elem.get('id', '')
                if not channel_id:
                    continue
                
                # Get display name
                display_name_elem = channel_elem.find('display-name')
                if display_name_elem is not None and display_name_elem.text:
                    channels[channel_id] = display_name_elem.text
            
            # Parse program listings
            for programme_elem in root.findall('.//programme'):
                channel_id = programme_elem.get('channel', '')
                if not channel_id:
                    continue
                
                start_str = programme_elem.get('start', '')
                stop_str = programme_elem.get('stop', '')
                
                # Parse times (XMLTV format: YYYYMMDDHHmmss +timezone)
                start_time = self._parse_xmltv_time(start_str)
                stop_time = self._parse_xmltv_time(stop_str)
                
                if start_time is None or stop_time is None:
                    continue
                
                # Get title
                title_elem = programme_elem.find('title')
                title = title_elem.text if title_elem is not None and title_elem.text else "Unknown"
                
                # Get description
                desc_elem = programme_elem.find('desc')
                description = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                
                program = EpgProgram(
                    start=start_time,
                    end=stop_time,
                    title=title,
                    description=description,
                    channel=channel_id
                )
                
                if channel_id not in programs:
                    programs[channel_id] = []
                programs[channel_id].append(program)
            
            # Store live data and update cache
            with self._lock:
                self._live_data = programs
            
            # Cache all channels
            for channel_id, progs in programs.items():
                self.cache.set(channel_id, progs)
                self.epg_loaded.emit(channel_id, progs)
                
        except ET.ParseError as e:
            self.error_occurred.emit(f"XML parsing error: {str(e)}")
        except Exception as e:
            self.error_occurred.emit(f"EPG processing error: {str(e)}")
    
    def _parse_xmltv_time(self, time_str: str) -> Optional[int]:
        """
        Parse XMLTV timestamp to Unix epoch.
        
        Format: YYYYMMDDHHmmss +timezone (e.g., 20240115143000 +0000)
        Returns Unix timestamp or None if parsing fails.
        """
        if not time_str:
            return None
        
        try:
            # Remove timezone for simple parsing (assume UTC for now)
            time_part = time_str.split()[0] if ' ' in time_str else time_str
            
            from datetime import datetime
            dt = datetime.strptime(time_part, '%Y%m%d%H%M%S')
            return int(dt.timestamp())
        except (ValueError, IndexError):
            return None
    
    def get_programs(self, channel_id: str) -> Optional[List[EpgProgram]]:
        """
        Get EPG programs for a channel.
        
        Checks cache first, falls back to live data if not cached.
        """
        # Try cache first
        cached = self.cache.get(channel_id)
        if cached is not None:
            return cached
        
        # Fallback to live data
        with self._lock:
            return self._live_data.get(channel_id)
    
    def clear_cache(self) -> None:
        """Clear the EPG cache."""
        self.cache.clear()
    
    def get_cache_size(self) -> int:
        """Get current cache size."""
        return self.cache.size()


class EpgManager:
    """
    Main EPG manager class that combines loader and cache functionality.
    
    Provides a simple interface for the IPTV player to interact with EPG data.
    """
    
    def __init__(self):
        self.loader = EpgLoader()
        self.loader.epg_loaded.connect(self._on_program_loaded)
        self._channel_programs: Dict[str, List[EpgProgram]] = {}
    
    def _on_program_loaded(self, channel_id: str, programs: List[EpgProgram]) -> None:
        """Internal handler for loaded programs."""
        self._channel_programs[channel_id] = programs
    
    def load_from_url(self, url: str) -> None:
        """Start loading EPG from URL."""
        self._channel_programs.clear()
        self.loader.load_epg(url)
    
    def get_programs(self, channel_id: str) -> Optional[List[EpgProgram]]:
        """Get programs for a channel (checks cache first)."""
        return self.loader.get_programs(channel_id)
    
    def get_all_programs(self) -> Dict[str, List[EpgProgram]]:
        """Get all currently loaded programs."""
        return self._channel_programs.copy()
    
    def clear_cache(self) -> None:
        """Clear EPG cache."""
        self.loader.clear_cache()
    
    def get_cache_size(self) -> int:
        """Get current cache size."""
        return self.loader.get_cache_size()
