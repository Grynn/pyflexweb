"""Tests for the database module."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from pyflexweb.database import PLACEHOLDER_ACCOUNT_ID, FlexDatabase


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

    def _add_default_account(self):
        """Add a default account for tests that don't focus on account logic."""
        self.db.add_account("U_TEST", "Test Account", "tok_test")
        return "U_TEST"

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
        acct = self._add_default_account()
        self.db.add_query("123456", "Test Query", account_id=acct)
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
        acct = self._add_default_account()
        self.db.add_query("111", "Activity Query", query_type="activity", account_id=acct)
        self.db.add_query("222", "Trade Conf", query_type="trade-confirmation", account_id=acct)

        q1 = self.db.get_query_info("111")
        self.assertEqual(q1["type"], "activity")

        q2 = self.db.get_query_info("222")
        self.assertEqual(q2["type"], "trade-confirmation")

    def test_query_with_min_interval(self):
        acct = self._add_default_account()
        self.db.add_query("111", "Custom Interval", min_interval=12, account_id=acct)
        q = self.db.get_query_info("111")
        self.assertEqual(q["min_interval"], 12)

        self.db.set_query_interval("111", 24)
        q = self.db.get_query_info("111")
        self.assertEqual(q["min_interval"], 24)

        self.db.set_query_interval("111", None)
        q = self.db.get_query_info("111")
        self.assertIsNone(q["min_interval"])

    def test_list_queries(self):
        acct = self._add_default_account()
        self.db.add_query("111", "First Query", account_id=acct)
        self.db.add_query("222", "Second Query", account_id=acct)
        self.db.add_query("333", "Third Query", account_id=acct)

        queries = self.db.list_queries()
        self.assertEqual(len(queries), 3)
        self.assertEqual([q[0] for q in queries], ["111", "222", "333"])
        self.assertEqual([q[1] for q in queries], ["First Query", "Second Query", "Third Query"])

    def test_request_operations(self):
        acct = self._add_default_account()
        self.db.add_query("123456", "Test Query", account_id=acct)
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
        acct = self._add_default_account()
        self.db.add_query("123456", "Test Query", account_id=acct)
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
        acct = self._add_default_account()
        self.db.add_query("111", "Activity", query_type="activity", account_id=acct)
        self.db.add_query("222", "Trade Conf", query_type="trade-confirmation", account_id=acct)
        self.db.add_query("333", "Never Downloaded", account_id=acct)

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
        acct = self._add_default_account()
        self.db.add_query("111", "First Query", account_id=acct)
        self.db.add_query("222", "Second Query", query_type="trade-confirmation", account_id=acct)

        self.db.add_request("REQ1", "111")
        self.db.update_request_status("REQ1", "completed", "output.xml")

        queries = self.db.get_all_queries_with_status()
        self.assertEqual(len(queries), 2)

        q111 = next(q for q in queries if q["id"] == "111")
        self.assertEqual(q111["name"], "First Query")
        self.assertEqual(q111["type"], "activity")
        self.assertEqual(q111["account_id"], acct)
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
    """Test account CRUD operations."""

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
        self.db.add_account("U111", "Account A", "tok_a")
        acct = self.db.get_account("U111")
        self.assertIsNotNone(acct)
        self.assertEqual(acct["id"], "U111")
        self.assertEqual(acct["name"], "Account A")
        self.assertEqual(acct["token"], "tok_a")

    def test_add_account_no_name(self):
        self.db.add_account("U111", None, "tok_a")
        self.assertIsNone(self.db.get_account("U111")["name"])

    def test_add_account_upsert(self):
        self.db.add_account("U111", "Old", "old_tok")
        self.db.add_account("U111", "New", "new_tok")
        acct = self.db.get_account("U111")
        self.assertEqual(acct["name"], "New")
        self.assertEqual(acct["token"], "new_tok")

    def test_list_accounts_empty(self):
        self.assertEqual(self.db.list_accounts(), [])

    def test_list_accounts(self):
        self.db.add_account("U111", "A", "ta")
        self.db.add_account("U222", "B", "tb")
        self.assertEqual(len(self.db.list_accounts()), 2)

    def test_remove_account_no_queries(self):
        self.db.add_account("U111", "A", "t")
        self.assertTrue(self.db.remove_account("U111"))
        self.assertIsNone(self.db.get_account("U111"))

    def test_remove_account_not_found(self):
        self.assertFalse(self.db.remove_account("U999"))

    def test_remove_account_blocked_by_queries(self):
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Query 1", account_id="U111")
        self.assertFalse(self.db.remove_account("U111"))
        self.assertIsNotNone(self.db.get_account("U111"))

    def test_remove_account_after_query_removed(self):
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Q", account_id="U111")
        self.db.remove_query("Q1")
        self.assertTrue(self.db.remove_account("U111"))

    def test_rename_account(self):
        self.db.add_account("U111", "Old", "t")
        self.assertTrue(self.db.rename_account("U111", "New"))
        self.assertEqual(self.db.get_account("U111")["name"], "New")

    def test_rename_account_not_found(self):
        self.assertFalse(self.db.rename_account("U999", "X"))

    def test_get_token_for_account(self):
        self.db.add_account("U111", "A", "tok_a")
        self.assertEqual(self.db.get_token_for_account("U111"), "tok_a")
        self.assertIsNone(self.db.get_token_for_account("U999"))

    def test_get_account_not_found(self):
        self.assertIsNone(self.db.get_account("nonexistent"))

    def test_placeholder_warning_unnamed(self):
        self.db.add_account("U111", None, "t")
        w = self.db.get_placeholder_warning()
        self.assertIsNotNone(w)
        self.assertIn("U111", w)

    def test_placeholder_warning_named_no_warning(self):
        self.db.add_account("U111", "Named", "t")
        self.assertIsNone(self.db.get_placeholder_warning())

    def test_placeholder_warning_clears_after_rename(self):
        self.db.add_account("U111", None, "t")
        self.assertIsNotNone(self.db.get_placeholder_warning())
        self.db.rename_account("U111", "Named")
        self.assertIsNone(self.db.get_placeholder_warning())


class TestQueryAccountIntegration(unittest.TestCase):
    """Test query + account integration: NOT NULL account_id, token resolution."""

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
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Query", account_id="U111")
        self.assertEqual(self.db.get_query_info("Q1")["account_id"], "U111")

    def test_add_query_without_account_raises(self):
        with self.assertRaises(ValueError):
            self.db.add_query("Q1", "Query")

    def test_set_query_account(self):
        self.db.add_account("U111", "A", "ta")
        self.db.add_account("U222", "B", "tb")
        self.db.add_query("Q1", "Q", account_id="U111")
        self.db.set_query_account("Q1", "U222")
        self.assertEqual(self.db.get_query_info("Q1")["account_id"], "U222")

    def test_set_query_account_empty_raises(self):
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Q", account_id="U111")
        with self.assertRaises(ValueError):
            self.db.set_query_account("Q1", "")

    def test_resolve_token_with_account(self):
        self.db.add_account("U111", "A", "account_token")
        self.db.add_query("Q1", "Q", account_id="U111")
        self.assertEqual(self.db.resolve_token("Q1"), "account_token")

    def test_resolve_token_missing_account_returns_none(self):
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Q", account_id="U111")
        # Temporarily disable FK enforcement to simulate a corrupt/missing account row
        self.db.conn.execute("PRAGMA foreign_keys = OFF")
        self.db.conn.execute("DELETE FROM accounts WHERE id = 'U111'")
        self.db.conn.commit()
        self.db.conn.execute("PRAGMA foreign_keys = ON")
        self.assertIsNone(self.db.resolve_token("Q1"))

    def test_resolve_token_nonexistent_query(self):
        self.assertIsNone(self.db.resolve_token("nonexistent"))

    def test_get_all_queries_includes_account(self):
        self.db.add_account("U111", "A", "ta")
        self.db.add_account("U222", "B", "tb")
        self.db.add_query("Q1", "Q1", account_id="U111")
        self.db.add_query("Q2", "Q2", account_id="U222")
        qs = {q["id"]: q for q in self.db.get_all_queries_with_status()}
        self.assertEqual(qs["Q1"]["account_id"], "U111")
        self.assertEqual(qs["Q2"]["account_id"], "U222")

    def test_get_queries_needing_download_includes_account(self):
        self.db.add_account("U111", "A", "t")
        self.db.add_query("Q1", "Q", account_id="U111")
        qs = self.db.get_queries_needing_download({"activity": 6})
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["account_id"], "U111")


class TestDatabaseMigration(unittest.TestCase):
    """Test DB migration from v4 to v6."""

    def setUp(self):
        self.temp_db_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_db_dir):
            shutil.rmtree(self.temp_db_dir)

    def _make_v4_db(self, with_token=True, with_query=True):
        db_path = os.path.join(self.temp_db_dir, "status.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("CREATE TABLE queries (id TEXT PRIMARY KEY, name TEXT, added_on DATETIME DEFAULT CURRENT_TIMESTAMP, min_interval INTEGER, type TEXT DEFAULT 'activity')")
        c.execute("CREATE TABLE requests (request_id TEXT PRIMARY KEY, query_id TEXT, status TEXT, requested_at DATETIME, completed_at DATETIME, last_updated DATETIME, output_path TEXT)")
        c.execute("INSERT INTO config VALUES ('db_version', '4')")
        if with_token:
            c.execute("INSERT INTO config VALUES ('token', 'global_tok')")
        if with_query:
            c.execute("INSERT INTO queries (id, name, type) VALUES ('Q1', 'Old Query', 'activity')")
        conn.commit()
        conn.close()

    def test_migration_v4_with_token(self):
        """v4 + global token → placeholder account, queries assigned, warning shown."""
        self._make_v4_db(with_token=True, with_query=True)
        with patch("platformdirs.user_data_dir", return_value=self.temp_db_dir):
            db = FlexDatabase()

        c = db.conn.cursor()
        c.execute("SELECT value FROM config WHERE key = 'db_version'")
        self.assertEqual(c.fetchone()[0], "6")

        placeholder = db.get_account(PLACEHOLDER_ACCOUNT_ID)
        self.assertIsNotNone(placeholder)
        self.assertEqual(placeholder["token"], "global_tok")
        self.assertIsNone(placeholder["name"])

        q = db.get_query_info("Q1")
        self.assertEqual(q["account_id"], PLACEHOLDER_ACCOUNT_ID)
        self.assertEqual(db.resolve_token("Q1"), "global_tok")

        self.assertIsNotNone(db.get_placeholder_warning())
        db.rename_account(PLACEHOLDER_ACCOUNT_ID, "Mine")
        self.assertIsNone(db.get_placeholder_warning())

        # account_id column is NOT NULL
        c.execute("PRAGMA table_info(queries)")
        col_info = {col[1]: col for col in c.fetchall()}
        self.assertEqual(col_info["account_id"][3], 1)

        db.close()

    def test_migration_v4_no_token_orphans_dropped(self):
        """v4 without global token: orphan queries dropped (can't satisfy NOT NULL)."""
        self._make_v4_db(with_token=False, with_query=True)
        with patch("platformdirs.user_data_dir", return_value=self.temp_db_dir):
            db = FlexDatabase()

        self.assertEqual(db.list_accounts(), [])
        self.assertIsNone(db.get_query_info("Q1"))
        db.close()


if __name__ == "__main__":
    unittest.main()
