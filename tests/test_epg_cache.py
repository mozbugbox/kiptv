import unittest
import time
from collections import OrderedDict
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory to path to import iptv_player
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the EpgCache class from iptv_player.epg_manager
try:
    from iptv_player.epg_manager import EpgCache
except ImportError as e:
    raise ImportError(f"EpgCache class not found in iptv_player.epg_manager: {e}")

class TestEpgCache(unittest.TestCase):
    def setUp(self):
        self.cache = EpgCache()
        self.sample_data = [
            {"start": "10:00", "stop": "11:00", "title": "Show 1"},
            {"start": "11:00", "stop": "12:00", "title": "Show 2"}
        ]

    def test_cache_miss_initially(self):
        """Test that cache returns None for unknown channel"""
        result = self.cache.get("unknown_channel")
        self.assertIsNone(result)

    def test_cache_hit_after_set(self):
        """Test that cache returns data after setting it"""
        self.cache.set("channel_1", self.sample_data)
        result = self.cache.get("channel_1")
        self.assertEqual(result, self.sample_data)

    def test_cache_expiration_3_hours(self):
        """Test that cache entries expire after 3 hours"""
        self.cache.set("channel_1", self.sample_data)
        
        # Manually manipulate the timestamp to simulate expiration
        # We access the internal _cache OrderedDict
        if "channel_1" in self.cache._cache:
            # Set timestamp to 3 hours + 1 minute ago (10860 seconds)
            self.cache._cache["channel_1"] = {'timestamp': time.time() - 10860, 'programs': self.sample_data}
            
        result = self.cache.get("channel_1")
        self.assertIsNone(result, "Cache should return None for expired entry")

    def test_cache_no_expiration_within_3_hours(self):
        """Test that cache entries remain valid within 3 hours"""
        self.cache.set("channel_1", self.sample_data)
        
        # Set timestamp to 2 hours 59 minutes ago (10740 seconds)
        if "channel_1" in self.cache._cache:
            self.cache._cache["channel_1"] = {'timestamp': time.time() - 10740, 'programs': self.sample_data}
            
        result = self.cache.get("channel_1")
        self.assertEqual(result, self.sample_data, "Cache should return data for valid entry")

    def test_lru_eviction_max_100(self):
        """Test that oldest entries are evicted when limit of 100 is reached"""
        # Fill cache with 100 items
        for i in range(100):
            self.cache.set(f"channel_{i}", [{"title": f"Show {i}"}])
        
        # Add 101st item
        self.cache.set("channel_100", [{"title": "Show 100"}])
        
        # Check size is still 100
        self.assertEqual(len(self.cache._cache), 100)
        
        # The oldest (channel_0) should be evicted
        result_0 = self.cache.get("channel_0")
        self.assertIsNone(result_0, "Oldest entry should be evicted")
        
        # The newest (channel_100) should exist
        result_100 = self.cache.get("channel_100")
        self.assertIsNotNone(result_100, "Newest entry should exist")

    def test_lru_order_update_on_get(self):
        """Test that accessing an item updates its position in LRU order"""
        self.cache = EpgCache() # Reset
        
        # Add 100 items: 0 to 99
        for i in range(100):
            self.cache.set(f"ch_{i}", [{"title": f"Data {i}"}])
            
        # Access ch_0 to move it to end (most recent)
        self.cache.get("ch_0")
        
        # Add ch_100. This should evict ch_1 (the new oldest), NOT ch_0.
        self.cache.set("ch_100", [{"title": "Data 100"}])
        
        self.assertIsNone(self.cache.get("ch_1"), "ch_1 should be evicted as it became oldest")
        self.assertIsNotNone(self.cache.get("ch_0"), "ch_0 should survive because it was accessed")
        self.assertIsNotNone(self.cache.get("ch_100"), "ch_100 should exist")

if __name__ == '__main__':
    unittest.main()
