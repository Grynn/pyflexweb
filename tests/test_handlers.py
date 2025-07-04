"""Tests for the handlers module."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from pyflexweb.handlers import (
    handle_download_command,
    handle_fetch_command,
    handle_query_command,
    handle_request_command,
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
            # Check that mask was applied correctly (first/last 4 chars)
            mock_print.assert_called_once_with("Stored token: test...alue")

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
        # Use real values instead of MagicMock objects for the properties
        args = MagicMock()
        args.subcommand = "add"
        args.query_id = "123456"
        args.name = "Test Query"

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.add_query.assert_called_once_with("123456", "Test Query")
            mock_print.assert_called_once_with("Query ID 123456 added successfully.")

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
        # Use real values instead of MagicMock objects for the properties
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
        # Use real values instead of MagicMock objects for the properties
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

    def test_query_list_with_queries(self):
        """Test listing queries when some exist."""
        args = MagicMock(subcommand="list")
        query1 = {
            "id": "123456",
            "name": "Test Query",
            "latest_request": {
                "completed_at": datetime.now().isoformat(),
                "requested_at": datetime.now().isoformat(),
                "status": "completed",
            },
        }
        query2 = {"id": "789012", "name": "Another Query", "latest_request": None}
        self.mock_db.get_all_queries_with_status.return_value = [query1, query2]

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_all_queries_with_status.assert_called_once()
            # Just verify the call count as the formatting is complex
            self.assertGreaterEqual(mock_print.call_count, 4)  # Header + separator + 2 queries

    def test_query_list_no_queries(self):
        """Test listing queries when none exist."""
        args = MagicMock(subcommand="list")
        self.mock_db.get_all_queries_with_status.return_value = []

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_all_queries_with_status.assert_called_once()
            mock_print.assert_called_once_with("No query IDs found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")

    def test_query_invalid_subcommand(self):
        """Test invalid query subcommand."""
        args = MagicMock(subcommand="invalid")

        with patch("builtins.print") as mock_print:
            result = handle_query_command(args, self.mock_db)
            self.assertEqual(result, 1)
            mock_print.assert_called_once_with("Missing subcommand. Use 'add', 'remove', 'rename', or 'list'.")


class TestRequestHandler(unittest.TestCase):
    """Test the request command handler."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_client_patcher = patch("pyflexweb.handlers.IBKRFlexClient")
        self.mock_client_class = self.mock_client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_client_class.return_value = self.mock_client

        self.addCleanup(self.mock_client_patcher.stop)

    def test_request_no_token(self):
        """Test request with no token."""
        args = MagicMock(query_id="123456")
        self.mock_db.get_token.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_request_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_client_class.assert_not_called()
            mock_print.assert_called_once_with("No token found. Set one with 'pyflexweb token set <token>'")

    def test_request_query_not_found(self):
        """Test request with invalid query ID."""
        args = MagicMock(query_id="123456")
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_request_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_query_info.assert_called_once_with("123456")
            self.mock_client_class.assert_not_called()
            mock_print.assert_called_once_with("Query ID 123456 not found. Add it with 'pyflexweb query add 123456'")

    def test_request_success(self):
        """Test successful request."""
        args = MagicMock(query_id="123456")
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query"}
        self.mock_client.request_report.return_value = "REQ123"

        with patch("builtins.print") as mock_print:
            result = handle_request_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_query_info.assert_called_once_with("123456")
            self.mock_client_class.assert_called_once_with("test_token")
            self.mock_client.request_report.assert_called_once_with("123456")
            self.mock_db.add_request.assert_called_once_with("REQ123", "123456")
            mock_print.assert_called_once_with("REQ123")

    def test_request_failure(self):
        """Test failed request."""
        args = MagicMock(query_id="123456")
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query"}
        self.mock_client.request_report.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_request_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_query_info.assert_called_once_with("123456")
            self.mock_client_class.assert_called_once_with("test_token")
            self.mock_client.request_report.assert_called_once_with("123456")
            self.mock_db.add_request.assert_not_called()
            mock_print.assert_called_once_with("Failed to request report.")


class TestFetchHandler(unittest.TestCase):
    """Test the fetch command handler."""

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

    def test_fetch_no_token(self):
        """Test fetch with no token."""
        args = MagicMock(request_id="REQ123", output=None, output_dir=None, max_attempts=5, poll_interval=1)
        self.mock_db.get_token.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_fetch_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_client_class.assert_not_called()
            mock_print.assert_called_once_with("No token found. Set one with 'pyflexweb token set <token>'")

    def test_fetch_success_with_custom_output(self):
        """Test successful fetch with custom output filename."""
        args = MagicMock(request_id="REQ123", output="custom_report.xml", output_dir=None, max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_request_info.return_value = {"query_id": "123456", "status": "pending"}
        self.mock_client.get_report.return_value = "<xml>report_content</xml>"

        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            result = handle_fetch_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_token.assert_called_once()
            self.mock_client_class.assert_called_once_with("test_token")
            self.mock_client.get_report.assert_called_once_with("REQ123")
            mock_open.assert_called_once_with("./custom_report.xml", "w", encoding="utf-8")
            file_handle = mock_open()
            file_handle.write.assert_called_once_with("<xml>report_content</xml>")
            self.mock_db.update_request_status.assert_called_once_with("REQ123", "completed", "./custom_report.xml")

    def test_fetch_success_default_output(self):
        """Test successful fetch with default output filename."""
        args = MagicMock(request_id="REQ123", output=None, output_dir=None, max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_request_info.return_value = {"query_id": "123456", "status": "pending"}
        self.mock_client.get_report.return_value = "<xml>report_content</xml>"

        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            # Need to patch datetime.now() to get consistent filename
            with patch("pyflexweb.handlers.datetime") as mock_datetime:
                mock_datetime.now.return_value.strftime.return_value = "20250412"
                result = handle_fetch_command(args, self.mock_db)

                self.assertEqual(result, 0)
                self.mock_db.get_token.assert_called_once()
                self.mock_client_class.assert_called_once_with("test_token")
                self.mock_client.get_report.assert_called_once_with("REQ123")

                # Check that the default filename was used
                expected_filename = "./123456_20250412.xml"
                mock_open.assert_called_once_with(expected_filename, "w", encoding="utf-8")

                file_handle = mock_open()
                file_handle.write.assert_called_once_with("<xml>report_content</xml>")
                self.mock_db.update_request_status.assert_called_once_with("REQ123", "completed", expected_filename)

    def test_fetch_no_request_info(self):
        """Test fetch when request info is not in database."""
        args = MagicMock(request_id="REQ123", output=None, output_dir=None, max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_request_info.return_value = None
        self.mock_client.get_report.return_value = "<xml>report_content</xml>"

        with patch("builtins.print") as mock_print:
            with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
                # Need to patch datetime.now() to get consistent filename
                with patch("pyflexweb.handlers.datetime") as mock_datetime:
                    mock_datetime.now.return_value.strftime.return_value = "20250412"
                    result = handle_fetch_command(args, self.mock_db)

                    self.assertEqual(result, 0)
                    self.mock_db.get_token.assert_called_once()
                    mock_print.assert_any_call("Request ID REQ123 not found in local database.")
                    mock_print.assert_any_call("It may still be valid if created outside this tool or in another session.")

                    # Check that the default filename was used without query_id
                    expected_filename = "./flex_report_20250412.xml"
                    mock_open.assert_called_once_with(expected_filename, "w", encoding="utf-8")

    def test_fetch_not_available(self):
        """Test fetch when report is not available after max attempts."""
        args = MagicMock(request_id="REQ123", output=None, output_dir=None, max_attempts=2, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_request_info.return_value = {"query_id": "123456", "status": "pending"}
        self.mock_client.get_report.return_value = None

        with patch("builtins.print") as mock_print:
            result = handle_fetch_command(args, self.mock_db)
            self.assertEqual(result, 1)
            self.mock_db.get_token.assert_called_once()
            self.mock_client_class.assert_called_once_with("test_token")

            # Should try max_attempts times
            self.assertEqual(self.mock_client.get_report.call_count, 2)

            # Should update status to failed
            self.mock_db.update_request_status.assert_called_once_with("REQ123", "failed")
            mock_print.assert_any_call("Report not available after 2 attempts.")


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
        args = MagicMock(query="all", output=None, output_dir=None)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_queries_not_updated.return_value = []

        with patch("builtins.print") as mock_print:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 0)
            self.mock_db.get_token.assert_called_once()
            self.mock_db.get_queries_not_updated.assert_called_once_with(hours=24)
            mock_print.assert_called_once_with("All queries have been updated within the last 24 hours.")

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

    def test_download_already_downloaded_today(self):
        """Test download when report was already downloaded today."""
        args = MagicMock(query="123456", force=False, output=None, output_dir=None)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query"}

        # Create a mock datetime for today
        today = datetime.now()

        # Mock latest request shows it was downloaded today
        self.mock_db.get_latest_request.return_value = {
            "status": "completed",
            "completed_at": today.isoformat(),
            "output_path": "previous_download.xml",
        }

        with patch("builtins.print") as mock_print:
            with patch("pyflexweb.handlers.datetime") as mock_datetime:
                mock_datetime.now.return_value = today
                mock_datetime.fromisoformat.return_value = today

                result = handle_download_command(args, self.mock_db)
                self.assertEqual(result, 0)

                self.mock_db.get_token.assert_called_once()
                self.mock_db.get_query_info.assert_called_once_with("123456")
                self.mock_db.get_latest_request.assert_called_once_with("123456")

                mock_print.assert_any_call("Already downloaded a report for query 123456 today.")
                mock_print.assert_any_call("Output file: previous_download.xml")
                mock_print.assert_any_call("Use --force to download again.")

    def test_download_force_success(self):
        """Test forced download with successful outcome."""
        args = MagicMock(query="123456", force=True, output="forced_download.xml", output_dir=None, max_attempts=1, poll_interval=1)
        self.mock_db.get_token.return_value = "test_token"
        self.mock_db.get_query_info.return_value = {"id": "123456", "name": "Test Query"}

        # Even though it was downloaded today, force will ignore this
        today = datetime.now()
        self.mock_db.get_latest_request.return_value = {
            "status": "completed",
            "completed_at": today.isoformat(),
            "output_path": "previous_download.xml",
        }

        # Mock successful report request and fetch
        self.mock_client.request_report.return_value = "REQ123"
        self.mock_client.get_report.return_value = "<xml>report_content</xml>"

        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            result = handle_download_command(args, self.mock_db)
            self.assertEqual(result, 0)

            self.mock_db.get_token.assert_called_once()
            self.mock_client.request_report.assert_called_once_with("123456")
            self.mock_db.add_request.assert_called_once_with("REQ123", "123456")
            self.mock_client.get_report.assert_called_once_with("REQ123")

            # Should use the custom output filename
            mock_open.assert_called_once_with("./forced_download.xml", "w", encoding="utf-8")
            file_handle = mock_open()
            file_handle.write.assert_called_once_with("<xml>report_content</xml>")

            # Should update request status to completed
            self.mock_db.update_request_status.assert_called_once_with("REQ123", "completed", "./forced_download.xml")


if __name__ == "__main__":
    unittest.main()
