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
        self.assertIsNone(q111["account_id"])
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


class TestAccountOperations(unittest.TestCase):
    """Test account-related database operations."""

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

    def test_add_and_get_account(self):
        self.db.add_account("U1317359", "Cerabella", "token_abc")
        acct = self.db.get_account("U1317359")
        self.assertIsNotNone(acct)
        self.assertEqual(acct["id"], "U1317359")
        self.assertEqual(acct["name"], "Cerabella")
        self.assertEqual(acct["token"], "token_abc")
        self.assertIsNotNone(acct["added_on"])

    def test_add_account_no_name(self):
        self.db.add_account("U999", None, "token_xyz")
        acct = self.db.get_account("U999")
        self.assertIsNotNone(acct)
        self.assertIsNone(acct["name"])
        self.assertEqual(acct["token"], "token_xyz")

    def test_add_account_upsert(self):
        """Adding the same account ID again should update it."""
        self.db.add_account("U1317359", "Cerabella", "old_token")
        self.db.add_account("U1317359", "Cerabella Updated", "new_token")
        acct = self.db.get_account("U1317359")
        self.assertEqual(acct["name"], "Cerabella Updated")
        self.assertEqual(acct["token"], "new_token")

    def test_list_accounts_empty(self):
        self.assertEqual(self.db.list_accounts(), [])

    def test_list_accounts(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_account("U222", "Account B", "tok_b")
        accounts = self.db.list_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["id"], "U111")
        self.assertEqual(accounts[1]["id"], "U222")

    def test_remove_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.assertTrue(self.db.remove_account("U111"))
        self.assertIsNone(self.db.get_account("U111"))
        self.assertFalse(self.db.remove_account("U111"))

    def test_remove_account_clears_query_references(self):
        """Removing an account should clear account_id from queries that reference it."""
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1", account_id="U111")
        self.db.add_query("Q2", "Query 2", account_id="U111")
        self.db.add_query("Q3", "Query 3")  # no account

        self.db.remove_account("U111")

        q1 = self.db.get_query_info("Q1")
        q2 = self.db.get_query_info("Q2")
        q3 = self.db.get_query_info("Q3")
        self.assertIsNone(q1["account_id"])
        self.assertIsNone(q2["account_id"])
        self.assertIsNone(q3["account_id"])

    def test_rename_account(self):
        self.db.add_account("U111", "Old Name", "tok_a")
        self.assertTrue(self.db.rename_account("U111", "New Name"))
        acct = self.db.get_account("U111")
        self.assertEqual(acct["name"], "New Name")

    def test_rename_account_not_found(self):
        self.assertFalse(self.db.rename_account("U999", "Name"))

    def test_get_token_for_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.assertEqual(self.db.get_token_for_account("U111"), "tok_a")
        self.assertIsNone(self.db.get_token_for_account("U999"))

    def test_get_account_not_found(self):
        self.assertIsNone(self.db.get_account("nonexistent"))


class TestQueryAccountIntegration(unittest.TestCase):
    """Test query + account integration features."""

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

    def test_add_query_with_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1", account_id="U111")
        q = self.db.get_query_info("Q1")
        self.assertEqual(q["account_id"], "U111")

    def test_add_query_without_account(self):
        self.db.add_query("Q1", "Query 1")
        q = self.db.get_query_info("Q1")
        self.assertIsNone(q["account_id"])

    def test_set_query_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1")
        self.assertTrue(self.db.set_query_account("Q1", "U111"))
        q = self.db.get_query_info("Q1")
        self.assertEqual(q["account_id"], "U111")

    def test_clear_query_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1", account_id="U111")
        self.assertTrue(self.db.set_query_account("Q1", None))
        q = self.db.get_query_info("Q1")
        self.assertIsNone(q["account_id"])

    def test_resolve_token_with_account(self):
        """Token resolution: query with account → account token."""
        self.db.add_account("U111", "Account A", "account_token")
        self.db.set_token("global_token")
        self.db.add_query("Q1", "Query 1", account_id="U111")

        token = self.db.resolve_token("Q1")
        self.assertEqual(token, "account_token")

    def test_resolve_token_fallback_to_global(self):
        """Token resolution: query without account → global token."""
        self.db.set_token("global_token")
        self.db.add_query("Q1", "Query 1")

        token = self.db.resolve_token("Q1")
        self.assertEqual(token, "global_token")

    def test_resolve_token_no_token_available(self):
        """Token resolution: no account, no global token → None."""
        self.db.add_query("Q1", "Query 1")
        token = self.db.resolve_token("Q1")
        self.assertIsNone(token)

    def test_resolve_token_account_removed_fallback(self):
        """Token resolution: account deleted → fallback to global."""
        self.db.add_account("U111", "Account A", "account_token")
        self.db.set_token("global_token")
        self.db.add_query("Q1", "Query 1", account_id="U111")

        # Remove account — should clear query's account_id
        self.db.remove_account("U111")

        token = self.db.resolve_token("Q1")
        self.assertEqual(token, "global_token")

    def test_resolve_token_nonexistent_query(self):
        """Token resolution for a query that doesn't exist."""
        token = self.db.resolve_token("nonexistent")
        # Falls through to global token
        self.assertIsNone(token)

    def test_get_all_queries_with_status_includes_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1", account_id="U111")
        self.db.add_query("Q2", "Query 2")

        queries = self.db.get_all_queries_with_status()
        q1 = next(q for q in queries if q["id"] == "Q1")
        q2 = next(q for q in queries if q["id"] == "Q2")
        self.assertEqual(q1["account_id"], "U111")
        self.assertIsNone(q2["account_id"])

    def test_get_queries_needing_download_includes_account(self):
        self.db.add_account("U111", "Account A", "tok_a")
        self.db.add_query("Q1", "Query 1", account_id="U111")

        type_defaults = {"activity": 6}
        queries = self.db.get_queries_needing_download(type_defaults)
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["account_id"], "U111")


class TestDatabaseMigration(unittest.TestCase):
    """Test database migration from v4 to v5."""

    def setUp(self):
        self.temp_db_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_db_dir):
            shutil.rmtree(self.temp_db_dir)

    def test_migration_from_v4_to_v5(self):
        """Simulate a v4 database and verify migration to v5."""
        db_path = os.path.join(self.temp_db_dir, "status.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create v4 schema
        cursor.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cursor.execute("CREATE TABLE queries (id TEXT PRIMARY KEY, name TEXT, added_on DATETIME DEFAULT CURRENT_TIMESTAMP, min_interval INTEGER, type TEXT DEFAULT 'activity')")
        cursor.execute("CREATE TABLE requests (request_id TEXT PRIMARY KEY, query_id TEXT, status TEXT, requested_at DATETIME, completed_at DATETIME, last_updated DATETIME, output_path TEXT)")
        cursor.execute("INSERT INTO config VALUES ('db_version', '4')")
        cursor.execute("INSERT INTO config VALUES ('token', 'global_tok')")
        cursor.execute("INSERT INTO queries (id, name, type) VALUES ('Q1', 'Old Query', 'activity')")
        conn.commit()
        conn.close()

        # Now open with FlexDatabase (should migrate)
        with patch("platformdirs.user_data_dir", return_value=self.temp_db_dir):
            db = FlexDatabase()

        # Verify version upgraded
        cursor = db.conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'db_version'")
        self.assertEqual(cursor.fetchone()[0], "5")

        # Verify accounts table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
        self.assertIsNotNone(cursor.fetchone())

        # Verify queries table has account_id column
        cursor.execute("PRAGMA table_info(queries)")
        columns = [col[1] for col in cursor.fetchall()]
        self.assertIn("account_id", columns)

        # Verify existing data preserved
        self.assertEqual(db.get_token(), "global_tok")
        q = db.get_query_info("Q1")
        self.assertEqual(q["name"], "Old Query")
        self.assertIsNone(q["account_id"])

        db.close()


if __name__ == "__main__":
    unittest.main()
