"""
Unit tests for the IPTV Player GUI module.
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestChannelItem(unittest.TestCase):
    """Test cases for ChannelItem class."""

    def test_channel_item_creation(self):
        """Test creating a ChannelItem with basic parameters."""
        from iptv_player import ChannelItem
        
        item = ChannelItem(
            name="Test Channel",
            logo_url="http://example.com/logo.png",
            group_title="Test Group",
            tvg_id="Test.id",
            sources=["http://example.com/stream.m3u8"],
            vlcopts=[],
            encryption=None
        )
        
        self.assertEqual(item.name, "Test Channel")
        self.assertEqual(item.sources, ["http://example.com/stream.m3u8"])
        self.assertEqual(item.tvg_id, "Test.id")
        self.assertEqual(item.logo_url, "http://example.com/logo.png")
        self.assertEqual(item.group_title, "Test Group")
        self.assertEqual(item.current_source_index, 0)

    def test_channel_item_multiple_sources(self):
        """Test ChannelItem with multiple sources."""
        from iptv_player import ChannelItem
        
        sources = [
            "http://source1.com/stream.m3u8",
            "http://source2.com/stream.m3u8",
            "http://source3.com/stream.m3u8"
        ]
        item = ChannelItem(
            name="Multi Source Channel",
            logo_url="",
            group_title="",
            tvg_id="",
            sources=sources,
            vlcopts=[],
            encryption=None
        )
        
        self.assertEqual(len(item.sources), 3)
        self.assertEqual(item.get_current_source(), sources[0])
        
        item.current_source_index = 1
        self.assertEqual(item.get_current_source(), sources[1])

    def test_channel_item_get_current_source(self):
        """Test getting current source from ChannelItem."""
        from iptv_player import ChannelItem
        
        item = ChannelItem(
            name="Test",
            logo_url="",
            group_title="",
            tvg_id="",
            sources=["http://first.com", "http://second.com"],
            vlcopts=[],
            encryption=None
        )
        
        self.assertEqual(item.get_current_source(), "http://first.com")
        item.current_source_index = 1
        self.assertEqual(item.get_current_source(), "http://second.com")
        
        # Test boundary - should wrap or stay at last
        item.current_source_index = 10
        # Depending on implementation, this might raise or return last
        # Just ensure no crash
        try:
            item.get_current_source()
        except IndexError:
            pass  # Acceptable behavior


class TestEpgLoader(unittest.TestCase):
    """Test cases for EpgLoader class."""

    @patch('iptv_player.QNetworkAccessManager')
    def test_epg_loader_initialization(self, mock_manager):
        """Test EpgLoader initialization."""
        from iptv_player import EpgLoader
        
        loader = EpgLoader()
        self.assertIsNotNone(loader)
        self.assertTrue(hasattr(loader, 'epg_data'))
        self.assertIsInstance(loader.epg_data, dict)

    def test_parse_xmltv_basic(self):
        """Test parsing basic XMLTV content."""
        from iptv_player import EpgLoader
        
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <programme channel="CNN.us" start="20240101140000 +0000" stop="20240101150000 +0000">
    <title lang="en">CNN Newsroom</title>
    <desc lang="en">Latest news from around the world.</desc>
  </programme>
  <programme channel="CNN.us" start="20240101150000 +0000" stop="20240101160000 +0000">
    <title lang="en">Connect the World</title>
    <desc lang="en">Global connections.</desc>
  </programme>
</tv>
"""
        loader = EpgLoader()
        programs = loader.parse_xmltv(xml_content)
        
        self.assertIn("CNN.us", programs)
        self.assertEqual(len(programs["CNN.us"]), 2)
        self.assertEqual(programs["CNN.us"][0]['title'], 'CNN Newsroom')
        self.assertEqual(programs["CNN.us"][1]['title'], 'Connect the World')

    def test_parse_xmltv_empty(self):
        """Test parsing empty XMLTV content."""
        from iptv_player import EpgLoader
        
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
</tv>
"""
        loader = EpgLoader()
        programs = loader.parse_xmltv(xml_content)
        
        self.assertEqual(len(programs), 0)

    def test_parse_xmltv_multiple_channels(self):
        """Test parsing XMLTV with multiple channels."""
        from iptv_player import EpgLoader
        
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <programme channel="CNN.us" start="20240101140000 +0000" stop="20240101150000 +0000">
    <title lang="en">CNN News</title>
  </programme>
  <programme channel="BBC.uk" start="20240101140000 +0000" stop="20240101150000 +0000">
    <title lang="en">BBC News</title>
  </programme>
</tv>
"""
        loader = EpgLoader()
        programs = loader.parse_xmltv(xml_content)
        
        self.assertIn("CNN.us", programs)
        self.assertIn("BBC.uk", programs)
        self.assertEqual(len(programs), 2)


class TestVlcoptToMpvOpt(unittest.TestCase):
    """Test VLC option to MPV option conversion."""

    def test_http_user_agent(self):
        """Test http-user-agent conversion."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('http-user-agent', 'MyAgent')
        self.assertEqual(opt, '--user-agent')
        self.assertEqual(val, 'MyAgent')

    def test_http_referrer(self):
        """Test http-referrer conversion."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('http-referrer', 'http://example.com')
        self.assertEqual(opt, '--referrer')
        self.assertEqual(val, 'http://example.com')

    def test_program(self):
        """Test program conversion."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('program', '1')
        self.assertEqual(opt, '--program')
        self.assertEqual(val, '1')

    def test_network_caching(self):
        """Test network-caching conversion (ms to seconds)."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('network-caching', '3000')
        self.assertEqual(opt, '--cache-secs')
        self.assertEqual(float(val), 3.0)

    def test_live_caching(self):
        """Test live-caching conversion (ms to seconds)."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('live-caching', '5000')
        self.assertEqual(opt, '--cache-secs')
        self.assertEqual(float(val), 5.0)

    def test_unknown_option(self):
        """Test unknown option passthrough."""
        from iptv_player import IPTVPlayer
        player = IPTVPlayer.__new__(IPTVPlayer)  # Create without __init__
        opt, val = player.vlcopt_to_mpv_opt('custom-option', 'value')
        self.assertEqual(opt, '--custom-option')
        self.assertEqual(val, 'value')


class TestIptvPlayerHelpers(unittest.TestCase):
    """Test helper methods in IPTVPlayer."""

    @patch('iptv_player.QApplication')
    def test_build_mpv_command_no_encryption(self, mock_app):
        """Test building mpv command without encryption."""
        from iptv_player import IPTVPlayer, ChannelItem
        
        player = IPTVPlayer()
        channel = ChannelItem(
            name="Test",
            sources=["http://example.com/stream.m3u8"],
            tvg_id="",
            tvg_logo="",
            group_title="",
            vlcopts={'http-user-agent': 'TestAgent'},
            encryption=None
        )
        
        cmd = player.build_mpv_command(channel)
        
        self.assertIn('mpv', cmd[0])
        self.assertIn('--no-terminal', cmd)
        self.assertIn('--force-window', cmd)
        self.assertIn('--user-agent', cmd)
        self.assertIn('TestAgent', cmd)
        self.assertIn('http://example.com/stream.m3u8', cmd)

    @patch('iptv_player.QApplication')
    def test_build_mpv_command_with_encryption(self, mock_app):
        """Test building mpv command with encryption."""
        from iptv_player import IPTVPlayer, ChannelItem
        
        player = IPTVPlayer()
        channel = ChannelItem(
            name="Encrypted",
            sources=["http://example.com/encrypted.m3u8"],
            tvg_id="",
            tvg_logo="",
            group_title="",
            vlcopts={},
            encryption={
                'method': 'AES-128',
                'uri': 'http://keys.example.com/key.key',
                'iv': '0x1234567890abcdef'
            }
        )
        
        cmd = player.build_mpv_command(channel)
        
        self.assertIn('mpv', cmd[0])
        self.assertIn('--hls-aes-iv', cmd)
        self.assertIn('0x1234567890abcdef', cmd)


if __name__ == '__main__':
    unittest.main()
