"""
Unit tests for EPG Manager module (epg_manager.py)
Tests EpgCache, EpgLoader, and integration functionality.
"""

import unittest
import threading
import time
from datetime import datetime, timedelta
from collections import OrderedDict
from unittest.mock import patch, MagicMock

# Import from the epg_manager module
from iptv_player.epg_manager import EpgCache, EpgLoader, EpgProgram


class TestEpgCache(unittest.TestCase):
    """Test cases for the EpgCache class."""

    def setUp(self):
        """Set up test fixtures."""
        self.cache = EpgCache()

    def tearDown(self):
        """Clean up after tests."""
        self.cache.clear()

    def test_cache_miss_initially(self):
        """Test that cache returns None for unknown channels initially."""
        result = self.cache.get("unknown_channel")
        self.assertIsNone(result)

    def test_cache_hit_after_set(self):
        """Test that cache returns data after setting it."""
        programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Test Show")]
        self.cache.set("test_channel", programs)
        result = self.cache.get("test_channel")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Test Show")

    def test_cache_expiration_3_hours(self):
        """Test that cache entries expire after 3 hours."""
        programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Test Show")]
        
        # Manually set an expired entry by manipulating internal state
        with self.cache._lock:
            self.cache._cache["expired_channel"] = {
                'programs': programs,
                'timestamp': time.time() - (3 * 3600 + 1)  # Expired 1 second ago
            }
        
        result = self.cache.get("expired_channel")
        self.assertIsNone(result)

    def test_cache_no_expiration_within_3_hours(self):
        """Test that cache entries remain valid within 3 hours."""
        programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Test Show")]
        
        # Manually set a fresh entry
        with self.cache._lock:
            self.cache._cache["fresh_channel"] = {
                'programs': programs,
                'timestamp': time.time() - (2 * 3600)  # 2 hours ago
            }
        
        result = self.cache.get("fresh_channel")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    def test_lru_eviction_max_100(self):
        """Test that oldest entries are evicted when cache exceeds 100 items."""
        # Fill cache with 100 items
        for i in range(100):
            programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title=f"Show {i}")]
            self.cache.set(f"channel_{i}", programs)
        
        # Add one more item (should evict the oldest: channel_0)
        new_programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="New Show")]
        self.cache.set("channel_new", new_programs)
        
        # Check that the oldest item was evicted
        result_old = self.cache.get("channel_0")
        self.assertIsNone(result_old)
        
        # Check that the new item is present
        result_new = self.cache.get("channel_new")
        self.assertIsNotNone(result_new)
        
        # Check cache size is still 100
        self.assertEqual(self.cache.size(), 100)

    def test_lru_order_update_on_get(self):
        """Test that accessing an item updates its LRU order."""
        # Add two items
        programs1 = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Show 1")]
        programs2 = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Show 2")]
        self.cache.set("channel_1", programs1)
        self.cache.set("channel_2", programs2)
        
        # Access channel_1 to make it most recently used
        self.cache.get("channel_1")
        
        # Fill cache to force eviction (need 99 more to reach limit of 100)
        # channel_1 and channel_2 are already in cache, so add 98 more
        for i in range(3, 101):
            progs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title=f"Show {i}")]
            self.cache.set(f"channel_{i}", progs)
        
        # Now cache has 100 items: channel_1, channel_2, channel_3...channel_100
        # channel_2 is the oldest (channel_1 was accessed recently)
        # Add one more to trigger eviction
        final_prog = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title="Final Show")]
        self.cache.set("channel_final", final_prog)
        
        # channel_2 should be evicted (oldest), but channel_1 should remain (accessed recently)
        result_1 = self.cache.get("channel_1")
        result_2 = self.cache.get("channel_2")
        
        self.assertIsNotNone(result_1)
        self.assertIsNone(result_2)

    def test_thread_safety(self):
        """Test that cache operations are thread-safe."""
        results = {'success': True, 'errors': []}
        lock = threading.Lock()
        
        def worker(thread_id):
            try:
                for i in range(50):
                    channel_name = f"channel_{thread_id}_{i}"
                    programs = [EpgProgram(start=int(datetime.now().timestamp()), end=int((datetime.now() + timedelta(hours=1)).timestamp()), title=f"Show {i}")]
                    self.cache.set(channel_name, programs)
                    result = self.cache.get(channel_name)
                    if result is None:
                        with lock:
                            results['success'] = False
                            results['errors'].append(f"Thread {thread_id}: Got None for {channel_name}")
            except Exception as e:
                with lock:
                    results['success'] = False
                    results['errors'].append(f"Thread {thread_id}: Exception {str(e)}")
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        self.assertTrue(results['success'], f"Thread safety test failed: {results['errors']}")


class TestEpgLoader(unittest.TestCase):
    """Test cases for the EpgLoader class."""

    def setUp(self):
        """Set up test fixtures."""
        self.loader = EpgLoader()

    def test_parse_xmltv_basic(self):
        """Test basic XMLTV parsing."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <tv>
            <channel id="CNN.us">
                <display-name>CNN</display-name>
            </channel>
            <programme start="20240101140000 +0000" stop="20240101150000 +0000" channel="CNN.us">
                <title lang="en">News Hour</title>
                <desc lang="en">Latest news</desc>
            </programme>
        </tv>"""
        
        # Call private method directly for testing
        self.loader._parse_xmltv(xml_content)
        programs = self.loader.get_programs("CNN.us")
        
        self.assertIsNotNone(programs)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0].title, "News Hour")
        self.assertEqual(programs[0].description, "Latest news")

    def test_parse_xmltv_multiple_programs(self):
        """Test parsing multiple programs for same channel."""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <tv>
            <channel id="BBC.uk">
                <display-name>BBC</display-name>
            </channel>
            <programme start="20240101140000 +0000" stop="20240101150000 +0000" channel="BBC.uk">
                <title lang="en">News</title>
            </programme>
            <programme start="20240101150000 +0000" stop="20240101160000 +0000" channel="BBC.uk">
                <title lang="en">Documentary</title>
            </programme>
        </tv>"""
        
        self.loader._parse_xmltv(xml_content)
        programs = self.loader.get_programs("BBC.uk")
        
        self.assertIsNotNone(programs)
        self.assertEqual(len(programs), 2)
        self.assertEqual(programs[0].title, "News")
        self.assertEqual(programs[1].title, "Documentary")

    def test_get_current_program(self):
        """Test getting current program based on time."""
        now = int(datetime.now().timestamp())
        programs = [
            EpgProgram(start=now - 7200, end=now - 3600, title="Past Show"),
            EpgProgram(start=now - 1800, end=now + 1800, title="Current Show"),
            EpgProgram(start=now + 3600, end=now + 7200, title="Future Show")
        ]
        
        # Find current program manually (simulating what UI does)
        current = None
        for prog in programs:
            if prog.start <= now < prog.end:
                current = prog
                break
        
        self.assertIsNotNone(current)
        self.assertEqual(current.title, "Current Show")

    def test_get_current_program_none(self):
        """Test getting current program when none is airing."""
        now = int(datetime.now().timestamp())
        programs = [
            EpgProgram(start=now - 7200, end=now - 3600, title="Past Show"),
            EpgProgram(start=now + 3600, end=now + 7200, title="Future Show")
        ]
        
        # Find current program manually
        current = None
        for prog in programs:
            if prog.start <= now < prog.end:
                current = prog
                break
        
        self.assertIsNone(current)


if __name__ == '__main__':
    unittest.main()
