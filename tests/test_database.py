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
        """Set up a temporary database for testing."""
        self.temp_db_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_db_dir, "test_status.db")

        # Patch the platformdirs.user_data_dir to return our temp directory
        self.patcher = patch("platformdirs.user_data_dir")
        self.mock_user_data_dir = self.patcher.start()
        self.mock_user_data_dir.return_value = self.temp_db_dir

        # Create a test database
        self.db = FlexDatabase()

    def tearDown(self):
        """Clean up after tests."""
        self.patcher.stop()

        # Close the database connection
        try:
            self.db.close()
        except sqlite3.Error:
            pass

        # Use shutil.rmtree to remove directory and all its contents
        if os.path.exists(self.temp_db_dir):
            shutil.rmtree(self.temp_db_dir)

    def test_get_db_path(self):
        """Test getting the database path."""
        db_path = self.db.get_db_path()
        self.assertEqual(db_path, os.path.join(self.temp_db_dir, "status.db"))

    def test_token_operations(self):
        """Test token operations (set, get, unset)."""
        # Initial state: no token
        self.assertIsNone(self.db.get_token())

        # Set token
        self.db.set_token("test_token")
        self.assertEqual(self.db.get_token(), "test_token")

        # Update token
        self.db.set_token("new_token")
        self.assertEqual(self.db.get_token(), "new_token")

        # Unset token
        self.db.unset_token()
        self.assertIsNone(self.db.get_token())

    def test_query_operations(self):
        """Test query operations (add, rename, remove)."""
        # Add a query
        self.db.add_query("123456", "Test Query")

        # Verify query was added
        query_info = self.db.get_query_info("123456")
        self.assertIsNotNone(query_info)
        self.assertEqual(query_info["id"], "123456")
        self.assertEqual(query_info["name"], "Test Query")

        # Rename the query
        self.assertTrue(self.db.rename_query("123456", "Renamed Query"))

        # Verify rename worked
        query_info = self.db.get_query_info("123456")
        self.assertEqual(query_info["name"], "Renamed Query")

        # Try to rename non-existent query
        self.assertFalse(self.db.rename_query("999999", "Should Not Work"))

        # Remove the query
        self.assertTrue(self.db.remove_query("123456"))

        # Verify query was removed
        self.assertIsNone(self.db.get_query_info("123456"))

        # Try to remove non-existent query
        self.assertFalse(self.db.remove_query("123456"))

    def test_list_queries(self):
        """Test listing queries."""
        # Add some queries
        self.db.add_query("111", "First Query")
        self.db.add_query("222", "Second Query")
        self.db.add_query("333", "Third Query")

        # List queries
        queries = self.db.list_queries()

        # Verify the result
        self.assertEqual(len(queries), 3)

        # Check that the queries are returned in insertion order
        query_ids = [q[0] for q in queries]
        self.assertEqual(query_ids, ["111", "222", "333"])

        query_names = [q[1] for q in queries]
        self.assertEqual(query_names, ["First Query", "Second Query", "Third Query"])

    def test_request_operations(self):
        """Test request operations."""
        # Add a query first
        self.db.add_query("123456", "Test Query")

        # Add a request
        self.db.add_request("REQ123", "123456")

        # Verify request was added
        request_info = self.db.get_request_info("REQ123")
        self.assertIsNotNone(request_info)
        self.assertEqual(request_info["request_id"], "REQ123")
        self.assertEqual(request_info["query_id"], "123456")
        self.assertEqual(request_info["status"], "pending")

        # Update request status
        self.db.update_request_status("REQ123", "completed", "output.xml")

        # Verify status was updated
        request_info = self.db.get_request_info("REQ123")
        self.assertEqual(request_info["status"], "completed")
        self.assertEqual(request_info["output_path"], "output.xml")
        self.assertIsNotNone(request_info["completed_at"])

    def test_get_latest_request(self):
        """Test getting the latest request for a query."""
        # Add a query
        self.db.add_query("123456", "Test Query")

        # No requests yet
        self.assertIsNone(self.db.get_latest_request("123456"))

        # Add some requests with timestamps a minute apart
        with patch("pyflexweb.database.datetime", autospec=True) as mock_datetime:
            # Create mock datetime objects for our tests
            first_datetime = datetime(2025, 4, 12, 10, 0, 0)
            second_datetime = datetime(2025, 4, 12, 10, 1, 0)

            # Configure the mock
            mock_datetime.now.return_value = first_datetime
            mock_datetime.isoformat = datetime.isoformat  # Use the real isoformat method

            # First request at 10:00
            self.db.add_request("REQ1", "123456")

            # Second request at 10:01
            mock_datetime.now.return_value = second_datetime
            self.db.add_request("REQ2", "123456")

        # Get the latest request
        latest_request = self.db.get_latest_request("123456")
        self.assertIsNotNone(latest_request)
        self.assertEqual(latest_request["request_id"], "REQ2")

    def test_get_queries_not_updated(self):
        """Test getting queries that haven't been updated recently."""
        # Add some queries
        self.db.add_query("111", "First Query")
        self.db.add_query("222", "Second Query")
        self.db.add_query("333", "Third Query")

        # Create datetime objects for our tests
        old_time = datetime.now() - timedelta(hours=48)
        recent_time = datetime.now() - timedelta(hours=12)
        current_time = datetime.now()

        with patch("pyflexweb.database.datetime", autospec=True) as mock_datetime:
            # Configure the mock to return our datetime objects
            mock_datetime.now.side_effect = [old_time, old_time, recent_time, recent_time, current_time]
            # Make sure isoformat is available
            mock_datetime.isoformat = datetime.isoformat

            # Add a request for query 111 with timestamp 48 hours ago (old)
            self.db.add_request("REQ1", "111")
            self.db.update_request_status("REQ1", "completed", "output.xml")

            # Add a request for query 222 with timestamp 12 hours ago (recent)
            self.db.add_request("REQ2", "222")
            self.db.update_request_status("REQ2", "completed", "output2.xml")

            # Query 333 has never had a request

            # Now get queries not updated in last 24 hours
            mock_datetime.now.return_value = current_time
            queries = self.db.get_queries_not_updated(hours=24)

        # We should get queries 111 and 333 (old and never updated)
        self.assertEqual(len(queries), 2)

        # Extract the IDs for easier comparison
        query_ids = [q["id"] for q in queries]
        self.assertIn("111", query_ids)
        self.assertIn("333", query_ids)
        self.assertNotIn("222", query_ids)  # This one was updated recently

    def test_get_all_queries_with_status(self):
        """Test getting all queries with their latest request status."""
        # Add some queries
        self.db.add_query("111", "First Query")
        self.db.add_query("222", "Second Query")

        # Add a request for query 111
        self.db.add_request("REQ1", "111")
        self.db.update_request_status("REQ1", "completed", "output.xml")

        # Get all queries with status
        queries = self.db.get_all_queries_with_status()

        # Should have 2 queries
        self.assertEqual(len(queries), 2)

        # Find query 111
        query111 = next(q for q in queries if q["id"] == "111")
        self.assertIsNotNone(query111)
        self.assertEqual(query111["name"], "First Query")
        self.assertIsNotNone(query111["latest_request"])
        self.assertEqual(query111["latest_request"]["status"], "completed")

        # Find query 222 (no request)
        query222 = next(q for q in queries if q["id"] == "222")
        self.assertIsNotNone(query222)
        self.assertEqual(query222["name"], "Second Query")
        self.assertIsNone(query222["latest_request"])

    def test_database_close(self):
        """Test closing the database connection."""
        # This mainly tests that close doesn't raise any exceptions
        self.db.close()

        # Try to perform an operation after closing
        # This should raise an exception, which we'll catch and assert on
        with self.assertRaises(sqlite3.ProgrammingError):
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
