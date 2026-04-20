"""
IPTV Player Package
"""

from iptv_player.iptv_player import IPTVPlayer, ChannelItem, LogoLoader
from iptv_player.m3u_parser import load_playlist, M3uParser
from iptv_player.epg_manager import EpgManager, EpgLoader, EpgCache, EpgProgram

__all__ = [
    'IPTVPlayer',
    'ChannelItem',
    'LogoLoader',
    'load_playlist',
    'M3uParser',
    'EpgManager',
    'EpgLoader',
    'EpgCache',
    'EpgProgram',
]
