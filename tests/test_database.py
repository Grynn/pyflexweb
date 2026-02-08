"""Tests for the database module."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from pyflexweb.database import FlexDatabase


class TestFlexDatabase(unittest.TestCase):
    """Test the FlexDatabase class."""

    def setUp(self):
        self.temp_db_dir = tempfile.mkdtemp()
        self.patcher = patch("platformdirs.user_data_dir")
        self.mock_user_data_dir = self.patcher.start()
        self.mock_user_data_dir.return_value = self.temp_db_dir
        self.db = FlexDatabase()

    def tearDown(self):
        self.patcher.stop()
        try:
            self.db.close()
        except sqlite3.Error:
            pass
        if os.path.exists(self.temp_db_dir):
            shutil.rmtree(self.temp_db_dir)

    def test_get_db_path(self):
        db_path = self.db.get_db_path()
        self.assertEqual(db_path, os.path.join(self.temp_db_dir, "status.db"))

    def test_token_operations(self):
        self.assertIsNone(self.db.get_token())
        self.db.set_token("test_token")
        self.assertEqual(self.db.get_token(), "test_token")
        self.db.set_token("new_token")
        self.assertEqual(self.db.get_token(), "new_token")
        self.db.unset_token()
        self.assertIsNone(self.db.get_token())

    def test_query_operations(self):
        self.db.add_query("123456", "Test Query")
        query_info = self.db.get_query_info("123456")
        self.assertIsNotNone(query_info)
        self.assertEqual(query_info["id"], "123456")
        self.assertEqual(query_info["name"], "Test Query")
        self.assertEqual(query_info["type"], "activity")

        self.assertTrue(self.db.rename_query("123456", "Renamed Query"))
        query_info = self.db.get_query_info("123456")
        self.assertEqual(query_info["name"], "Renamed Query")

        self.assertFalse(self.db.rename_query("999999", "Should Not Work"))
        self.assertTrue(self.db.remove_query("123456"))
        self.assertIsNone(self.db.get_query_info("123456"))
        self.assertFalse(self.db.remove_query("123456"))

    def test_query_with_type(self):
        self.db.add_query("111", "Activity Query", query_type="activity")
        self.db.add_query("222", "Trade Conf", query_type="trade-confirmation")

        q1 = self.db.get_query_info("111")
        self.assertEqual(q1["type"], "activity")

        q2 = self.db.get_query_info("222")
        self.assertEqual(q2["type"], "trade-confirmation")

    def test_query_with_min_interval(self):
        self.db.add_query("111", "Custom Interval", min_interval=12)
        q = self.db.get_query_info("111")
        self.assertEqual(q["min_interval"], 12)

        self.db.set_query_interval("111", 24)
        q = self.db.get_query_info("111")
        self.assertEqual(q["min_interval"], 24)

        self.db.set_query_interval("111", None)
        q = self.db.get_query_info("111")
        self.assertIsNone(q["min_interval"])

    def test_list_queries(self):
        self.db.add_query("111", "First Query")
        self.db.add_query("222", "Second Query")
        self.db.add_query("333", "Third Query")

        queries = self.db.list_queries()
        self.assertEqual(len(queries), 3)
        self.assertEqual([q[0] for q in queries], ["111", "222", "333"])
        self.assertEqual([q[1] for q in queries], ["First Query", "Second Query", "Third Query"])

    def test_request_operations(self):
        self.db.add_query("123456", "Test Query")
        self.db.add_request("REQ123", "123456")

        request_info = self.db.get_request_info("REQ123")
        self.assertIsNotNone(request_info)
        self.assertEqual(request_info["request_id"], "REQ123")
        self.assertEqual(request_info["query_id"], "123456")
        self.assertEqual(request_info["status"], "pending")

        self.db.update_request_status("REQ123", "completed", "output.xml")
        request_info = self.db.get_request_info("REQ123")
        self.assertEqual(request_info["status"], "completed")
        self.assertEqual(request_info["output_path"], "output.xml")
        self.assertIsNotNone(request_info["completed_at"])

    def test_get_latest_request(self):
        self.db.add_query("123456", "Test Query")
        self.assertIsNone(self.db.get_latest_request("123456"))

        with patch("pyflexweb.database.datetime", autospec=True) as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 4, 12, 10, 0, 0)
            mock_datetime.isoformat = datetime.isoformat
            self.db.add_request("REQ1", "123456")

            mock_datetime.now.return_value = datetime(2025, 4, 12, 10, 1, 0)
            self.db.add_request("REQ2", "123456")

        latest = self.db.get_latest_request("123456")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["request_id"], "REQ2")

    def test_get_queries_needing_download(self):
        self.db.add_query("111", "Activity", query_type="activity")
        self.db.add_query("222", "Trade Conf", query_type="trade-confirmation")
        self.db.add_query("333", "Never Downloaded")

        old_time = datetime.now() - timedelta(hours=48)
        recent_time = datetime.now() - timedelta(minutes=30)
        current_time = datetime.now()

        with patch("pyflexweb.database.datetime", autospec=True) as mock_datetime:
            mock_datetime.now.side_effect = [
                old_time,
                old_time,  # add + update REQ1 (activity, 48h ago)
                recent_time,
                recent_time,  # add + update REQ2 (trade-conf, 30min ago)
                current_time,
                current_time,
                current_time,  # get_queries_needing_download (per query)
            ]
            mock_datetime.isoformat = datetime.isoformat

            self.db.add_request("REQ1", "111")
            self.db.update_request_status("REQ1", "completed", "output.xml")

            self.db.add_request("REQ2", "222")
            self.db.update_request_status("REQ2", "completed", "output2.xml")

            type_defaults = {"activity": 6, "trade-confirmation": 1}
            queries = self.db.get_queries_needing_download(type_defaults)

        # 111: activity, 48h ago → needs download (> 6h)
        # 222: trade-conf, 30min ago → up to date (< 1h)
        # 333: never downloaded → needs download
        query_ids = [q["id"] for q in queries]
        self.assertEqual(len(queries), 2)
        self.assertIn("111", query_ids)
        self.assertIn("333", query_ids)
        self.assertNotIn("222", query_ids)

    def test_get_all_queries_with_status(self):
        self.db.add_query("111", "First Query")
        self.db.add_query("222", "Second Query", query_type="trade-confirmation")

        self.db.add_request("REQ1", "111")
        self.db.update_request_status("REQ1", "completed", "output.xml")

        queries = self.db.get_all_queries_with_status()
        self.assertEqual(len(queries), 2)

        q111 = next(q for q in queries if q["id"] == "111")
        self.assertEqual(q111["name"], "First Query")
        self.assertEqual(q111["type"], "activity")
        self.assertIsNotNone(q111["latest_request"])
        self.assertEqual(q111["latest_request"]["status"], "completed")

        q222 = next(q for q in queries if q["id"] == "222")
        self.assertEqual(q222["name"], "Second Query")
        self.assertEqual(q222["type"], "trade-confirmation")
        self.assertIsNone(q222["latest_request"])

    def test_database_close(self):
        self.db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT 1")

    def test_config_operations(self):
        self.db.set_config("test_key", "test_value")
        self.assertEqual(self.db.get_config("test_key"), "test_value")
        self.assertEqual(self.db.get_config("nonexistent_key", "default"), "default")
        self.assertIsNone(self.db.get_config("nonexistent_key"))

        self.db.set_config("default_poll_interval", "60")
        self.db.set_config("default_max_attempts", "15")

        config_dict = self.db.list_config()
        expected_dict = {"test_key": "test_value", "default_poll_interval": "60", "default_max_attempts": "15"}
        self.assertEqual(config_dict, expected_dict)

        self.assertTrue(self.db.unset_config("test_key"))
        self.assertIsNone(self.db.get_config("test_key"))
        self.assertFalse(self.db.unset_config("test_key"))

        config_dict = self.db.list_config()
        self.assertNotIn("test_key", config_dict)
        self.assertIn("default_poll_interval", config_dict)


if __name__ == "__main__":
    unittest.main()
