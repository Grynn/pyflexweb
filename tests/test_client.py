"""Tests for the IBKR Flex Web Service client."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from pyflexweb.client import IBKRFlexClient


class TestIBKRFlexClient(unittest.TestCase):
    """Test the IBKRFlexClient class."""

    def setUp(self):
        """Set up test environment."""
        self.client = IBKRFlexClient("test_token")

    def test_request_report_success(self):
        """Test requesting a report with successful response."""
        # Create mock response with success status
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Success</Status>
            <ReferenceCode>REQ123</ReferenceCode>
            <Url>https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement</Url>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            request_id = self.client.request_report("123456")
            self.assertEqual(request_id, "REQ123")

    def test_request_report_failure_status(self):
        """Test requesting a report with error status in response."""
        # Create mock response with error status
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Fail</Status>
            <ErrorCode>1234</ErrorCode>
            <ErrorMessage>Invalid query ID</ErrorMessage>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            with patch("sys.stderr") as mock_stderr:
                request_id = self.client.request_report("123456")
                self.assertIsNone(request_id)
                # We just need to check if the right message was printed to stderr
                self.assertTrue(mock_stderr.write.called)
                self.assertIn(
                    "Error requesting report: Invalid query ID", "".join([call[0][0] for call in mock_stderr.write.call_args_list])
                )

    def test_request_report_network_error(self):
        """Test requesting a report with network error."""
        # Mock requests.get to raise an exception
        with patch("pyflexweb.client.requests.get", side_effect=requests.exceptions.RequestException("Network error")):
            with patch("sys.stderr") as mock_stderr:
                request_id = self.client.request_report("123456")
                self.assertIsNone(request_id)
                # We just need to check if the right message was printed to stderr
                self.assertTrue(mock_stderr.write.called)
                self.assertIn("Network error: Network error", "".join([call[0][0] for call in mock_stderr.write.call_args_list]))

    def test_request_report_parse_error(self):
        """Test requesting a report with XML parse error."""
        # Create mock response with invalid XML
        mock_response = MagicMock()
        mock_response.text = "Not valid XML"
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            with patch("sys.stderr") as mock_stderr:
                request_id = self.client.request_report("123456")
                self.assertIsNone(request_id)
                # The exact error message will vary, just check that stderr.write was called
                self.assertTrue(mock_stderr.write.called)

    def test_get_report_success(self):
        """Test getting a report with successful response."""
        # Create mock response with XML report
        mock_response = MagicMock()
        mock_response.text = "<FlexQueryResponse>XML report content</FlexQueryResponse>"
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            report_xml = self.client.get_report("REQ123")
            self.assertEqual(report_xml, "<FlexQueryResponse>XML report content</FlexQueryResponse>")

    def test_get_report_pending(self):
        """Test getting a report that is not ready yet."""
        # Create mock response with pending status
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Pending</Status>
            <ErrorCode>1234</ErrorCode>
            <ErrorMessage>Report not ready</ErrorMessage>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            report_xml = self.client.get_report("REQ123")
            self.assertIsNone(report_xml)

    def test_get_report_error(self):
        """Test getting a report with error status."""
        # Create mock response with error status
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Failed</Status>
            <ErrorCode>1234</ErrorCode>
            <ErrorMessage>Invalid request ID</ErrorMessage>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            with patch("sys.stderr") as mock_stderr:
                report_xml = self.client.get_report("REQ123")
                self.assertIsNone(report_xml)
                # We just need to check if the right message was printed to stderr
                self.assertTrue(mock_stderr.write.called)
                self.assertIn(
                    "Error retrieving report: Invalid request ID", "".join([call[0][0] for call in mock_stderr.write.call_args_list])
                )

    def test_get_report_network_error(self):
        """Test getting a report with network error."""
        # Mock requests.get to raise an exception
        with patch("pyflexweb.client.requests.get", side_effect=requests.exceptions.RequestException("Network error")):
            with patch("sys.stderr") as mock_stderr:
                report_xml = self.client.get_report("REQ123")
                self.assertIsNone(report_xml)
                # We just need to check if the right message was printed to stderr
                self.assertTrue(mock_stderr.write.called)
                self.assertIn("Network error: Network error", "".join([call[0][0] for call in mock_stderr.write.call_args_list]))

    def test_get_report_parse_error(self):
        """Test getting a report with XML parse error in an error response."""
        # Create mock response with invalid XML in error format
        mock_response = MagicMock()
        mock_response.text = "<ErrorCode>Not complete XML"
        mock_response.raise_for_status = MagicMock()

        # Mock the requests.get method to return our mock response
        with patch("pyflexweb.client.requests.get", return_value=mock_response):
            with patch("sys.stderr") as mock_stderr:
                report_xml = self.client.get_report("REQ123")
                self.assertIsNone(report_xml)
                # The exact error message will vary, just check that stderr.write was called
                self.assertTrue(mock_stderr.write.called)


if __name__ == "__main__":
    unittest.main()
