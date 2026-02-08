"""Tests for the handlers module."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from pyflexweb.handlers import (
    TYPE_INTERVAL_DEFAULTS,
    handle_config_command,
    handle_download_command,
    handle_query_command,
    handle_token_command,
)


class TestTokenHandler(unittest.TestCase):
    """Test the token command handler."""

    def setUp(self):
        self.mock_db = MagicMock()

    def test_token_set(self):
        """Test setting a token."""
        args = MagicMock(subcommand="set", token="test_token")

        with patch("builtins.print") as mock_print:
            result = handle_token_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.set_token.assert_called_once_with("test_token")
            mock_print.assert_called_once_with("Token set successfully.")

    def test_token_get_success(self):
        """Test getting a token when one exists."""
        args = MagicMock(subcommand="get")
        self.mock_db.get_token.return_value = "test_token_value"

        with patch("builtins.print") as mock_print:
            result = handle_token_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_token.assert_called_once()
            mock_print.assert_called_once_with("Stored token: test_token_value")

    def test_token_get_not_found(self):
        """Test getting a token when none exists."""
        args = MagicMock(subcommand="get")
        self.mock_db.get_token.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_token_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            mock_print.assert_called_once_with("No token found. Set one with 'pyflexweb token set <token>'")

    def test_token_unset(self):
        """Test unsetting a token."""
        args = MagicMock(subcommand="unset")

        with patch("builtins.print") as mock_print:
            result = handle_token_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.unset_token.assert_called_once()
            mock_print.assert_called_once_with("Token removed.")

    def test_token_invalid_subcommand(self):
        """Test invalid token subcommand."""
        args = MagicMock(subcommand="invalid")

        with patch("builtins.print") as mock_print:
            result = handle_token_command(args, self.mock_db)
            self.assertEqual(result, 1)
            mock_print.assert_called_once_with("Missing subcommand. Use 'set', 'get', or 'unset'.")


class TestQueryHandler(unittest.TestCase):
    """Test the query command handler."""

    def setUp(self):
        self.mock_db = MagicMock()

    def test_query_add(self):
        """Test adding a query."""
        args = MagicMock()
        args.subcommand = "add"
        args.query_id = "123456"
        args.name = "Test Query"
        args.query_type = "activity"
        args.min_interval = None

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.add_query.assert_called_once_with("123456", "Test Query", query_type="activity", min_interval=None)
            mock_print.assert_called_once_with("Query ID 123456 added (activity).")

    def test_query_add_trade_confirmation(self):
        """Test adding a trade-confirmation query."""
        args = MagicMock()
        args.subcommand = "add"
        args.query_id = "789"
        args.name = "Trade Conf"
        args.query_type = "trade-confirmation"
        args.min_interval = None

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.add_query.assert_called_once_with("789", "Trade Conf", query_type="trade-confirmation", min_interval=None)
            mock_print.assert_called_once_with("Query ID 789 added (trade-confirmation).")

    def test_query_add_with_interval(self):
        """Test adding a query with custom min interval."""
        args = MagicMock()
        args.subcommand = "add"
        args.query_id = "123456"
        args.name = "Custom"
        args.query_type = "activity"
        args.min_interval = 12

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.add_query.assert_called_once_with("123456", "Custom", query_type="activity", min_interval=12)
            mock_print.assert_called_once_with("Query ID 123456 added (activity). Min interval: 12h.")

    def test_query_remove_success(self):
        """Test removing a query that exists."""
        args = MagicMock(subcommand="remove", query_id="123456")
        self.mock_db.remove_query.return_value = True

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.remove_query.assert_called_once_with("123456")
            mock_print.assert_called_once_with("Query ID 123456 removed.")

    def test_query_remove_not_found(self):
        """Test removing a query that does not exist."""
        args = MagicMock(subcommand="remove", query_id="123456")
        self.mock_db.remove_query.return_value = False

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.remove_query.assert_called_once_with("123456")
            mock_print.assert_called_once_with("Query ID 123456 not found.")

    def test_query_rename_success(self):
        """Test renaming a query that exists."""
        args = MagicMock()
        args.subcommand = "rename"
        args.query_id = "123456"
        args.name = "New Name"

        self.mock_db.rename_query.return_value = True

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.rename_query.assert_called_once_with("123456", "New Name")
            mock_print.assert_called_once_with("Query ID 123456 renamed to 'New Name'.")

    def test_query_rename_not_found(self):
        """Test renaming a query that does not exist."""
        args = MagicMock()
        args.subcommand = "rename"
        args.query_id = "123456"
        args.name = "New Name"

        self.mock_db.rename_query.return_value = False

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.rename_query.assert_called_once_with("123456", "New Name")
            mock_print.assert_called_once_with("Query ID 123456 not found.")

    def test_query_interval_set(self):
        """Test setting a query interval."""
        args = MagicMock()
        args.subcommand = "interval"
        args.query_id = "123456"
        args.hours = 12
        args.unset = False

        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test", "type": "activity", "min_interval": None}

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.set_query_interval.assert_called_once_with("123456", 12)
            mock_print.assert_called_once_with("Query 123456 min interval set to 12h.")

    def test_query_interval_unset(self):
        """Test unsetting a query interval."""
        args = MagicMock()
        args.subcommand = "interval"
        args.query_id = "123456"
        args.hours = None
        args.unset = True

        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test", "type": "activity", "min_interval": 12}

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.set_query_interval.assert_called_once_with("123456", None)
            mock_print.assert_called_once_with("Query 123456 will use the type default (6h).")

    def test_query_interval_not_found(self):
        """Test setting interval for a non-existent query."""
        args = MagicMock()
        args.subcommand = "interval"
        args.query_id = "999"
        args.hours = 12
        args.unset = False

        self.mock_db.get_query_info.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 1)
            mock_print.assert_called_once_with("Query ID 999 not found.")

    def test_query_list_with_queries(self):
        """Test listing queries when some exist."""
        args = MagicMock(subcommand="list", json_output=False)
        query1 = {
            "id": "123456",
            "name": "Test Query",
            "type": "activity",
            "min_interval": None,
            "latest_request": {
                "completed_at": datetime.now().isoformat(),
                "requested_at": datetime.now().isoformat(),
                "status": "completed",
            },
        }
        query2 = {"id": "789012", "name": "Another Query", "type": "trade-confirmation", "min_interval": 2, "latest_request": None}
        self.mock_db.get_all_queries_with_status.return_value = [query1, query2]

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_all_queries_with_status.assert_called_once()
            self.assertGreaterEqual(mock_print.call_count, 4)  # Header + separator + 2 queries

    def test_query_list_no_queries(self):
        """Test listing queries when none exist."""
        args = MagicMock(subcommand="list", json_output=False)
        self.mock_db.get_all_queries_with_status.return_value = []

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_all_queries_with_status.assert_called_once()
            mock_print.assert_called_once_with("No query IDs found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")

    def test_query_list_json_output(self):
        """Test listing queries in JSON format."""
        args = MagicMock(subcommand="list", json_output=True)
        query1 = {
            "id": "123456",
            "name": "Test Query",
            "type": "activity",
            "min_interval": None,
            "latest_request": {
                "completed_at": "2025-04-12T10:00:00",
                "requested_at": "2025-04-12T09:55:00",
                "status": "completed",
                "output_path": "output.xml",
            },
        }
        self.mock_db.get_all_queries_with_status.return_value = [query1]

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            # JSON output is a single print call
            mock_print.assert_called_once()
            import json

            output = json.loads(mock_print.call_args[0][0])
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0]["id"], "123456")
            self.assertEqual(output[0]["type"], "activity")
            self.assertEqual(output[0]["effective_interval"], 6)

    def test_query_invalid_subcommand(self):
        """Test invalid query subcommand."""
        args = MagicMock(subcommand="invalid")

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 1)
            mock_print.assert_called_once_with("Missing subcommand. Use 'add', 'remove', 'rename', 'interval', or 'list'.")


class TestDownloadHandler(unittest.TestCase):
    """Test the download command handler."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_client_patcher = patch("pyflexweb.handlers.IBKRFlexClient")
        self.mock_client_class = self.mock_client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_client_class.return_value = self.mock_client

        self.addCleanup(self.mock_client_patcher.stop)

        # Create a mock for time.sleep to avoid actual waiting
        self.mock_sleep_patcher = patch("time.sleep")
        self.mock_sleep = self.mock_sleep_patcher.start()
        self.addCleanup(self.mock_sleep_patcher.stop)

    def test_download_no_token(self):
        """Test download with no token."""
        args = MagicMock(query="123456")
        self.mock_db.get_token.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_client_class.assert_not_called()
            mock_print.assert_called_once_with("No token found. Set one with 'pyflexweb token set <token>'")

    def test_download_all_queries_up_to_date(self):
        """Test download all when all queries are up to date."""
        args = MagicMock(query="all", force=False, output=None, output_dir=None)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_queries_needing_download.return_value = []

        with patch("builtins.print") as mock_print:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_queries_needing_download.assert_called_once_with(TYPE_INTERVAL_DEFAULTS)
            mock_print.assert_any_call("All queries are up to date. Use --force to download anyway.")

    def test_download_specific_query_not_found(self):
        """Test download specific query that doesn't exist."""
        args = MagicMock(query="123456", output=None, output_dir=None)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_query_info.assert_called_once_with("123456")
            mock_print.assert_called_once_with("Query ID 123456 not found. Add it with 'pyflexweb query add 123456'")

    def test_download_already_downloaded_within_interval(self):
        """Test download when report was already downloaded within min interval."""
        args = MagicMock(query="123456", force=False, output=None, output_dir=None)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query", "type": "activity", "min_interval": None}

        now = datetime.now()
        self.mock_db.get_latest_request.return_value = {
            "status": "completed",
            "completed_at": now.isoformat(),
            "output_path": "previous_download.xml",
        }

        with patch("builtins.print") as mock_print:
            with patch("pyflexweb.handlers.datetime") as mock_datetime:
                mock_datetime.now.return_value = now
                mock_datetime.fromisoformat.return_value = now

                result = handle_download_command(args, self.mock_db)
                self.assertEqual(result, 0)

                self.mock_db.get_token.assert_called_once()
                self.mock_db.get_query_info.assert_called_once_with("123456")
                self.mock_db.get_latest_request.assert_called_once_with("123456")

                mock_print.assert_any_call("  Skipped: downloaded within the last 6h.")
                mock_print.assert_any_call("  Output file: previous_download.xml")
                mock_print.assert_any_call("  Use --force to download again.")

    def test_download_force_success(self):
        """Test forced download with successful outcome."""
        args = MagicMock(query="123456", force=True, output="forced_download.xml", output_dir=None, max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query", "type": "activity", "min_interval": None}

        self.mock_client.request_report.return_value = "REQ123"
        self.mock_client.get_report.return_value = "<xml>report_content</xml>"

        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 0)

            self.mock_db.get_token.assert_called_once()
            self.mock_client.request_report.assert_called_once_with("123456")
            self.mock_db.add_request.assert_called_once_with("REQ123", "123456")
            self.mock_client.get_report.assert_called_once_with("REQ123")

            mock_open.assert_called_once_with("./forced_download.xml", "w", encoding="utf-8")
            file_handle = mock_open()
            file_handle.write.assert_called_once_with("<xml>report_content</xml>")

            self.mock_db.update_request_status.assert_called_once_with("REQ123", "completed", "./forced_download.xml")

    def test_download_all_force(self):
        """Test forced download of all queries."""
        args = MagicMock(query="all", force=True, output=None, output_dir=".", max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_all_queries_with_status.return_value = [
            {"id": "111", "name": "Activity", "type": "activity", "min_interval": None, "latest_request": None},
            {"id": "222", "name": "Trade", "type": "trade-confirmation", "min_interval": None, "latest_request": None},
        ]

        self.mock_client.request_report.return_value = "REQ1"
        self.mock_client.get_report.return_value = "<xml>data</xml>"

        with patch("builtins.open", unittest.mock.mock_open()):
            with patch("builtins.print"):
                result = handle_download_command(args, self.mock_db)
                self.assertEqual(result, 0)
                self.mock_db.get_all_queries_with_status.assert_called_once()
                self.assertEqual(self.mock_client.request_report.call_count, 2)


class TestConfigHandler(unittest.TestCase):
    """Test the config command handler."""

    def setUp(self):
        self.mock_db = MagicMock()

    def test_config_set_string_value(self):
        """Test setting a string config value."""
        args = MagicMock(subcommand="set", key="default_output_dir", value="/path/to/reports")

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.set_config.assert_called_once_with("default_output_dir", "/path/to/reports")
            mock_print.assert_called_once_with("Set default_output_dir = /path/to/reports")

    def test_config_set_numeric_value(self):
        """Test setting a numeric config value."""
        args = MagicMock(subcommand="set", key="default_poll_interval", value="60")

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.set_config.assert_called_once_with("default_poll_interval", "60")
            mock_print.assert_called_once_with("Set default_poll_interval = 60")

    def test_config_set_invalid_numeric_value(self):
        """Test setting an invalid numeric config value."""
        args = MagicMock(subcommand="set", key="default_poll_interval", value="not_a_number")

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.set_config.assert_not_called()
            mock_print.assert_called_once_with("Error: default_poll_interval must be a number")

    def test_config_get_existing_key(self):
        """Test getting an existing config value."""
        args = MagicMock(subcommand="get", key="default_poll_interval")
        self.mock_db.get_config.return_value = "60"

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_config.assert_called_once_with("default_poll_interval")
            mock_print.assert_called_once_with("default_poll_interval = 60")

    def test_config_get_nonexistent_key(self):
        """Test getting a non-existent config value."""
        args = MagicMock(subcommand="get", key="nonexistent_key")
        self.mock_db.get_config.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_config.assert_called_once_with("nonexistent_key")
            mock_print.assert_called_once_with("nonexistent_key is not set")

    def test_config_get_all_values(self):
        """Test getting all config values."""
        args = MagicMock(subcommand="get", key=None)
        self.mock_db.list_config.return_value = {"default_poll_interval": "60", "default_output_dir": "/path/to/reports"}

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.list_config.assert_called_once()
            self.assertEqual(mock_print.call_count, 2)

    def test_config_get_all_values_empty(self):
        """Test getting all config values when none exist."""
        args = MagicMock(subcommand="get", key=None)
        self.mock_db.list_config.return_value = {}

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.list_config.assert_called_once()
            mock_print.assert_called_once_with("No configuration values set")

    def test_config_unset_existing_key(self):
        """Test unsetting an existing config value."""
        args = MagicMock(subcommand="unset", key="default_poll_interval")
        self.mock_db.unset_config.return_value = True

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.unset_config.assert_called_once_with("default_poll_interval")
            mock_print.assert_called_once_with("Unset default_poll_interval")

    def test_config_unset_nonexistent_key(self):
        """Test unsetting a non-existent config value."""
        args = MagicMock(subcommand="unset", key="nonexistent_key")
        self.mock_db.unset_config.return_value = False

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.unset_config.assert_called_once_with("nonexistent_key")
            mock_print.assert_called_once_with("nonexistent_key was not set")

    def test_config_list_command(self):
        """Test the list subcommand."""
        args = MagicMock(subcommand="list", key=None)
        self.mock_db.list_config.return_value = {"default_poll_interval": "60", "default_max_attempts": "15"}

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.list_config.assert_called_once()
            # header + note + 3 config settings + type defaults header + 2 type defaults = 8+
            self.assertGreaterEqual(mock_print.call_count, 7)
            call_args = [str(call[0][0]) for call in mock_print.call_args_list]
            self.assertIn("Configuration settings:", call_args)
            self.assertTrue(any("* indicates non-default value" in arg for arg in call_args))

    def test_config_invalid_subcommand(self):
        """Test an invalid subcommand."""
        args = MagicMock(subcommand="invalid")

        with patch("builtins.print") as mock_print:
            result = handle_config_command(args, self.mock_db)
            self.assertEqual(result, 1)
            mock_print.assert_called_once_with("Missing subcommand. Use 'set', 'get', 'unset', or 'list'.")


if __name__ == "__main__":
    unittest.main()
