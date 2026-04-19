"""
M3U/M3U8 Parser Module using m3u8 library with custom tag parsing.
Supports EXTVLCOPT tags for special IPTV playback requirements.
"""
import re
import m3u8
from typing import Dict, List, Optional, Any


def parse_extvlcopt_line(line: str) -> Dict[str, str]:
    """
    Parse a #EXTVLCOPT line to extract VLC/mpv options.
    Common options: http-user-agent, http-referrer, program, etc.
    Format: #EXTVLCOPT:option=value or #EXTVLCOPT:option
    """
    options = {}
    content = line.replace('#EXTVLCOPT:', '').strip()
    
    if '=' in content:
        key, value = content.split('=', 1)
        options[key.strip()] = value.strip()
    else:
        # Boolean option (e.g., #EXTVLCOPT:no-http)
        options[content] = 'true'
    
    return options


def parse_ext_x_key_line(line: str) -> Dict[str, str]:
    """
    Parse a #EXT-X-KEY line to extract HLS encryption key information.
    Format: #EXT-X-KEY:METHOD=AES-128,URI="http://...",IV=0x...,KEYFORMAT="..."
    
    Returns dict with keys: method, uri, iv, keyformat, keyformatversions
    """
    key_info = {}
    content = line.replace('#EXT-X-KEY:', '').strip()
    
    # Pattern to match key="value" pairs OR key=hexvalue (for IV which may not have quotes)
    # First try quoted values
    attr_pattern = re.compile(r'([A-Z0-9\-]+)="([^"]*)"')
    matches = attr_pattern.findall(content)
    
    for key, value in matches:
        key_info[key.lower()] = value
    
    # Also check for unquoted values (like IV=0x...)
    unquoted_pattern = re.compile(r'([A-Z0-9\-]+)=([0-9a-fA-Fx]+)(?:,|$)')
    unquoted_matches = unquoted_pattern.findall(content)
    
    for key, value in unquoted_matches:
        key_lower = key.lower()
        if key_lower not in key_info:  # Don't override quoted values
            key_info[key_lower] = value
    
    return key_info




def parse_extinf_line(line: str) -> Dict[str, Any]:
    """
    Parse a single #EXTINF line to extract attributes and channel name.
    Handles standard attributes like tvg-id, tvg-name, tvg-logo, group-title, etc.
    """
    # Pattern to match key="value" or key='value'
    attr_pattern = re.compile(r'([a-zA-Z0-9\-]+)="([^"]*)"')
    
    info = {
        'duration': -1.0,
        'title': '',
        'attributes': {},
        'vlcopts': []  # List of EXTVLCOPT options
    }
    
    # Remove the #EXTINF tag and split by comma to separate duration/attrs from title
    # Format: #EXTINF:-1 tvg-id="..." tvg-logo="...",Channel Name
    content = line.replace('#EXTINF:', '').strip()
    
    # Find the last comma which separates attributes from the title
    last_comma_idx = content.rfind(',')
    if last_comma_idx == -1:
        return info
        
    attr_part = content[:last_comma_idx].strip()
    title_part = content[last_comma_idx+1:].strip()
    
    info['title'] = title_part
    
    # Handle case where duration and attributes are merged without space (e.g., "-1tvg-id=...")
    # First, try to split by whitespace
    parts = attr_part.split(None, 1)
    
    if parts and len(parts) == 1:
        # No whitespace found, might be merged like "-1tvg-id=..." or just duration or just attrs
        # Try to find where duration ends and attributes begin
        duration_match = re.match(r'^(-?[0-9]+\.?[0-9]*)(.*)', parts[0])
        if duration_match:
            dur_str = duration_match.group(1)
            rest = duration_match.group(2)
            try:
                info['duration'] = float(dur_str)
                attr_part = rest
            except ValueError:
                pass
    elif parts:
        # Check if first part might contain duration merged with attributes
        first_part = parts[0]
        duration_match = re.match(r'^(-?[0-9]+\.?[0-9]*)(.*)', first_part)
        if duration_match:
            dur_str = duration_match.group(1)
            rest = duration_match.group(2)
            try:
                info['duration'] = float(dur_str)
                # Combine rest with remaining parts
                attr_part = rest + (' ' + parts[1] if len(parts) > 1 else '')
            except ValueError:
                # Not a duration, use original logic
                try:
                    info['duration'] = float(first_part)
                    if len(parts) > 1:
                        attr_part = parts[1]
                except ValueError:
                    pass
        else:
            # Standard case: first part is duration
            try:
                info['duration'] = float(parts[0])
                if len(parts) > 1:
                    attr_part = parts[1]
            except ValueError:
                pass
            
    # Parse key="value" pairs
    matches = attr_pattern.findall(attr_part)
    for key, value in matches:
        info['attributes'][key.lower()] = value
        
    return info


def parse_m3u_header(line: str) -> Dict[str, str]:
    """
    Parse the #EXTM3U header line to extract global attributes like x-tvg-url.
    """
    attrs = {}
    if not line.startswith('#EXTM3U'):
        return attrs
        
    content = line.replace('#EXTM3U', '').strip()
    attr_pattern = re.compile(r'([a-zA-Z0-9\-]+)="([^"]*)"')
    matches = attr_pattern.findall(content)
    
    for key, value in matches:
        attrs[key.lower()] = value
        
    return attrs


class M3uParser:
    """
    Custom parser class to be used with m3u8.load/loads via custom_tags_parser.
    """
    def __init__(self):
        self.global_attrs = {}
        self.current_channel_info = {}
        self.channels = []
        self.epg_url = None
        self.pending_channel = None  # Track channel waiting for URLs
        self.current_key = None  # Track active encryption key for subsequent channels/segments

    def handle_line(self, line: str, lineno: int, data: Dict[str, Any]):
        """
        Callback function for m3u8 custom_tags_parser.
        """
        line = line.strip()
        if not line:
            return

        if line.startswith('#EXTM3U'):
            self.global_attrs = parse_m3u_header(line)
            self.epg_url = self.global_attrs.get('x-tvg-url')
            
        elif line.startswith('#EXTINF'):
            # If we have a pending channel with URLs, save it first
            if self.pending_channel and self.pending_channel['sources']:
                self.channels.append(self.pending_channel)
            
            self.current_channel_info = parse_extinf_line(line)
            # Initialize pending channel
            self.pending_channel = {
                'name': self.current_channel_info.get('title', 'Unknown'),
                'logo': self.current_channel_info.get('attributes', {}).get('tvg-logo'),
                'group': self.current_channel_info.get('attributes', {}).get('group-title', 'Uncategorized'),
                'tvg_id': self.current_channel_info.get('attributes', {}).get('tvg-id'),
                'tvg_name': self.current_channel_info.get('attributes', {}).get('tvg-name'),
                'sources': [],
                'vlcopts': [],  # VLC options for special playback requirements
                'encryption': None,  # HLS encryption key info if present
                'duration': self.current_channel_info.get('duration')
            }
            # Apply any active encryption key to this new channel
            if self.current_key:
                self.pending_channel['encryption'] = self.current_key
            
        elif line.startswith('#EXTVLCOPT') and self.pending_channel:
            # Parse VLC options and add to current channel
            vlcopt = parse_extvlcopt_line(line)
            self.pending_channel['vlcopts'].append(vlcopt)
            
        elif line.startswith('#EXT-X-KEY:'):
            # Parse HLS encryption key and apply to current or subsequent channels
            key_info = parse_ext_x_key_line(line)
            self.current_key = key_info
            if self.pending_channel:
                self.pending_channel['encryption'] = key_info
            
        elif not line.startswith('#') and self.pending_channel:
            # This is a URL line following an EXTINF
            self.pending_channel['sources'].append(line)
            # Ensure encryption key is attached to the channel with this URL
            if self.current_key and not self.pending_channel.get('encryption'):
                self.pending_channel['encryption'] = self.current_key

    def finalize(self):
        """Call after all lines are processed to save any pending channel."""
        if self.pending_channel and self.pending_channel['sources']:
            self.channels.append(self.pending_channel)
            self.pending_channel = None

    def get_channels(self) -> List[Dict[str, Any]]:
        return self.channels

    def get_epg_url(self) -> Optional[str]:
        return self.epg_url


def load_playlist(file_path: str) -> tuple[List[Dict], Optional[str]]:
    """
    Load an M3U/M3U8 file and return a list of channels and the EPG URL.
    
    Returns:
        tuple: (list of channel dicts, epg_url string or None)
    """
    parser = M3uParser()
    
    try:
        # Use the m3u8 library with our custom tag parser
        # We read the file content and pass it to loads with custom_tags_parser
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Create a state object to pass to the parser
        # The m3u8 library's custom_tags_parser expects a function that takes (line, lineno, data)
        # We wrap our class method
        
        def custom_tag_handler(line, lineno, data):
            parser.handle_line(line, lineno, data)
            
        # Process all lines through our custom handler
        lines = content.splitlines()
        data = {} # State data passed by library
        
        for idx, line in enumerate(lines):
            custom_tag_handler(line, idx, data)
        
        # Finalize to ensure last channel is saved
        parser.finalize()
            
        return parser.get_channels(), parser.get_epg_url()
        
    except Exception as e:
        print(f"Error parsing M3U file: {e}")
        return [], None
