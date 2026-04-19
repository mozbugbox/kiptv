"""
EPG Manager Module

Handles EPG loading, parsing, caching, and retrieval.
Includes thread-safe LRU cache with 3-hour expiration and 100-entry limit.
"""

import threading
import time
import socket
import ipaddress
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
from defusedxml import ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import parse_url
from PyQt6.QtCore import QObject, pyqtSignal


# Block private and reserved IP ranges to prevent SSRF
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),      # Private
    ipaddress.ip_network('172.16.0.0/12'),   # Private
    ipaddress.ip_network('192.168.0.0/16'),  # Private
    ipaddress.ip_network('127.0.0.0/8'),     # Loopback
    ipaddress.ip_network('169.254.0.0/16'),  # Link-local
    ipaddress.ip_network('0.0.0.0/8'),       # Current network
    ipaddress.ip_network('224.0.0.0/4'),     # Multicast
    ipaddress.ip_network('240.0.0.0/4'),     # Reserved
    ipaddress.ip_network('::1/128'),         # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),        # IPv6 private
    ipaddress.ip_network('fe80::/10'),       # IPv6 link-local
]


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
    - Asynchronous loading via requests with SSRF protection
    - XMLTV format parsing with XXE protection (using defusedxml)
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
        
        # Create a custom session with SSRF protection
        self.session = requests.Session()
        self.session.mount('http://', _SSRFProtectionAdapter())
        self.session.mount('https://', _SSRFProtectionAdapter())
    
    def load_epg(self, url: str) -> None:
        """
        Load EPG data from URL asynchronously.
        
        Parses XMLTV format and caches results.
        Emits epg_loaded signal for each channel parsed.
        
        Security: Validates URL scheme and blocks private IP addresses.
        """
        try:
            # Validate URL scheme
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                self.error_occurred.emit(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.")
                return
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            self._parse_xmltv(response.text)
        except requests.exceptions.RequestException as e:
            self.error_occurred.emit(f"Failed to load EPG: {str(e)}")
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


def _is_ip_blocked(ip: str) -> bool:
    """Check if an IP address is in a blocked range."""
    try:
        ip_obj = ipaddress.ip_address(ip)
        for network in BLOCKED_IP_RANGES:
            if ip_obj in network:
                return True
        return False
    except ValueError:
        return True  # Block invalid IPs


def _resolve_and_check_hostname(hostname: str) -> Tuple[bool, Optional[str]]:
    """
    Resolve hostname and check if the IP is safe to connect to.
    
    Returns (is_safe, resolved_ip) tuple.
    """
    try:
        # Get all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip = sockaddr[0]
            if _is_ip_blocked(ip):
                return False, ip
        return True, addr_info[0][4][0] if addr_info else None
    except socket.gaierror:
        return False, None


class _SSRFProtectionAdapter(HTTPAdapter):
    """
    HTTP Adapter that provides SSRF protection by blocking private/reserved IPs.
    """
    
    def init_poolmanager(self, *args, **kwargs):
        # Enable server hostname verification
        kwargs['block_all_connections'] = False
        return super().init_poolmanager(*args, **kwargs)
    
    def send(self, request, *args, **kwargs):
        # Parse the URL to get the hostname
        parsed = urlparse(request.url)
        hostname = parsed.hostname
        
        if not hostname:
            raise requests.exceptions.RequestException("Invalid URL: missing hostname")
        
        # Check if hostname is an IP address directly
        try:
            ipaddress.ip_address(hostname)
            # It's an IP address, check if it's blocked
            if _is_ip_blocked(hostname):
                raise requests.exceptions.RequestException(
                    f"Connection to {hostname} blocked: private/reserved IP address"
                )
        except ValueError:
            # It's a hostname, resolve and check
            is_safe, resolved_ip = _resolve_and_check_hostname(hostname)
            if not is_safe:
                raise requests.exceptions.RequestException(
                    f"Connection to {hostname} blocked: resolves to private/reserved IP ({resolved_ip})"
                )
        
        # Enable strict SSL verification
        kwargs.setdefault('verify', True)
        
        return super().send(request, *args, **kwargs)


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
