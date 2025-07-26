"""Tests for the CLI module."""

import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pyflexweb.cli import cli, main


class TestClickCli(unittest.TestCase):
    """Test the Click-based CLI commands."""

    def setUp(self):
        self.runner = CliRunner()
        self.mock_db_patcher = patch("pyflexweb.cli.FlexDatabase")
        self.mock_db_class = self.mock_db_patcher.start()
        self.mock_db = MagicMock()
        self.mock_db_class.return_value = self.mock_db

        # Set up patchers for handlers
        self.patchers = [
            patch("pyflexweb.cli.handle_token_command", return_value=0),
            patch("pyflexweb.cli.handle_query_command", return_value=0),
            patch("pyflexweb.cli.handle_request_command", return_value=0),
            patch("pyflexweb.cli.handle_fetch_command", return_value=0),
            patch("pyflexweb.cli.handle_download_command", return_value=0),
        ]

        # Start all patchers and store mocks
        self.mocks = [patcher.start() for patcher in self.patchers]

        # Name the mocks for convenience
        self.mock_token_handler = self.mocks[0]
        self.mock_query_handler = self.mocks[1]
        self.mock_request_handler = self.mocks[2]
        self.mock_fetch_handler = self.mocks[3]
        self.mock_download_handler = self.mocks[4]

    def tearDown(self):
        self.mock_db_patcher.stop()
        for patcher in self.patchers:
            patcher.stop()

    def test_version_flag(self):
        """Test the version flag."""
        result = self.runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)

    def test_help_output(self):
        """Test the help output."""
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Download IBKR Flex reports", result.output)

    def test_no_command(self):
        """Test behavior when no command is provided."""
        result = self.runner.invoke(cli)
        self.assertEqual(result.exit_code, 1)  # Should exit with code 1
        self.assertIn("Usage:", result.output)  # Should show help

    def test_token_set_command(self):
        """Test the token set command."""
        result = self.runner.invoke(cli, ["token", "set", "test_token"])
        self.assertEqual(result.exit_code, 0)
        self.mock_token_handler.assert_called_once()
        args = self.mock_token_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "set")
        self.assertEqual(args.token, "test_token")

    def test_token_get_command(self):
        """Test the token get command."""
        result = self.runner.invoke(cli, ["token", "get"])
        self.assertEqual(result.exit_code, 0)
        self.mock_token_handler.assert_called_once()
        args = self.mock_token_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "get")

    def test_token_unset_command(self):
        """Test the token unset command."""
        result = self.runner.invoke(cli, ["token", "unset"])
        self.assertEqual(result.exit_code, 0)
        self.mock_token_handler.assert_called_once()
        args = self.mock_token_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "unset")

    def test_query_add_command(self):
        """Test the query add command."""
        result = self.runner.invoke(cli, ["query", "add", "123456", "--name", "Test Query"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "add")
        self.assertEqual(args.query_id, "123456")
        self.assertEqual(args.name, "Test Query")

    def test_query_remove_command(self):
        """Test the query remove command."""
        result = self.runner.invoke(cli, ["query", "remove", "123456"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "remove")
        self.assertEqual(args.query_id, "123456")

    def test_query_rename_command(self):
        """Test the query rename command."""
        result = self.runner.invoke(cli, ["query", "rename", "123456", "--name", "New Name"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "rename")
        self.assertEqual(args.query_id, "123456")
        self.assertEqual(args.name, "New Name")

    def test_query_list_command(self):
        """Test the query list command."""
        result = self.runner.invoke(cli, ["query", "list"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "list")

    def test_query_default_command(self):
        """Test the query command with no subcommand."""
        result = self.runner.invoke(cli, ["query"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "list")  # Default should be 'list'

    def test_status_command(self):
        """Test the status command (alias for query list)."""
        result = self.runner.invoke(cli, ["status"])
        self.assertEqual(result.exit_code, 0)
        self.mock_query_handler.assert_called_once()
        args = self.mock_query_handler.call_args[0][0]
        self.assertEqual(args.subcommand, "list")  # Status should call query handler with 'list'

    def test_request_command(self):
        """Test the request command."""
        result = self.runner.invoke(cli, ["request", "123456"])
        self.assertEqual(result.exit_code, 0)
        self.mock_request_handler.assert_called_once()
        args = self.mock_request_handler.call_args[0][0]
        self.assertEqual(args.query_id, "123456")

    def test_fetch_command(self):
        """Test the fetch command."""
        result = self.runner.invoke(cli, ["fetch", "REQ123", "--output", "report.xml", "--poll-interval", "10", "--max-attempts", "30"])
        self.assertEqual(result.exit_code, 0)
        self.mock_fetch_handler.assert_called_once()
        args = self.mock_fetch_handler.call_args[0][0]
        self.assertEqual(args.request_id, "REQ123")
        self.assertEqual(args.output, "report.xml")
        self.assertEqual(args.poll_interval, 10)
        self.assertEqual(args.max_attempts, 30)

    def test_fetch_command_defaults(self):
        """Test the fetch command with default values."""
        result = self.runner.invoke(cli, ["fetch", "REQ123"])
        self.assertEqual(result.exit_code, 0)
        self.mock_fetch_handler.assert_called_once()
        args = self.mock_fetch_handler.call_args[0][0]
        self.assertEqual(args.poll_interval, 30)  # Default value
        self.assertEqual(args.max_attempts, 20)  # Default value
        self.assertIsNone(args.output)  # Default is None

    def test_download_command(self):
        """Test the download command with all options."""
        result = self.runner.invoke(
            cli, ["download", "--query", "123456", "--output", "report.xml", "--poll-interval", "10", "--max-attempts", "30", "--force"]
        )
        self.assertEqual(result.exit_code, 0)
        self.mock_download_handler.assert_called_once()
        args = self.mock_download_handler.call_args[0][0]
        self.assertEqual(args.query, "123456")
        self.assertEqual(args.output, "report.xml")
        self.assertEqual(args.poll_interval, 10)
        self.assertEqual(args.max_attempts, 30)
        self.assertTrue(args.force)

    def test_download_command_defaults(self):
        """Test the download command with default values."""
        result = self.runner.invoke(cli, ["download"])
        self.assertEqual(result.exit_code, 0)
        self.mock_download_handler.assert_called_once()
        args = self.mock_download_handler.call_args[0][0]
        self.assertEqual(args.query, "all")  # Default value
        self.assertEqual(args.poll_interval, 30)  # Default value
        self.assertEqual(args.max_attempts, 20)  # Default value
        self.assertIsNone(args.output)  # Default is None
        self.assertFalse(args.force)  # Default is False


class TestMainFunction(unittest.TestCase):
    """Test the main entry point function."""

    def setUp(self):
        self.mock_cli_patcher = patch("pyflexweb.cli.cli")
        self.mock_cli = self.mock_cli_patcher.start()
        self.addCleanup(self.mock_cli_patcher.stop)

    def test_main_success(self):
        """Test successful execution of main."""
        self.mock_cli.return_value = 0
        with patch("sys.exit") as mock_exit:
            main()
            mock_exit.assert_called_once_with(0)

    def test_main_exception(self):
        """Test handling of exceptions in main."""
        self.mock_cli.side_effect = Exception("Test error")
        with patch("click.echo") as mock_echo:
            with patch("sys.exit") as mock_exit:
                main()
                mock_echo.assert_called_once_with("Error: Test error", err=True)
                mock_exit.assert_not_called()  # We don't call sys.exit directly on exception


if __name__ == "__main__":
    unittest.main()
