"""Tests for the IBKR Flex Web Service client."""

import socket
import unittest
from unittest.mock import MagicMock, patch

import requests

from pyflexweb.client import (
    DNS_MAX_RETRIES,
    DNS_RETRY_DELAYS_SECONDS,
    REPORT_GENERATION_RETRY_DELAYS_SECONDS,
    REQUEST_TIMEOUT,
    FlexError,
    IBKRFlexClient,
    classify_flex_error,
)


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

    def test_request_report_retries_transient_generation_failure_then_succeeds(self):
        """IBKR's explicit try-again-shortly response gets a bounded retry."""
        transient = MagicMock()
        transient.text = """
        <FlexStatementResponse>
            <Status>Fail</Status>
            <ErrorCode>1012</ErrorCode>
            <ErrorMessage>Statement could not be generated at this time. Please try again shortly.</ErrorMessage>
        </FlexStatementResponse>
        """
        transient.raise_for_status = MagicMock()
        success = MagicMock()
        success.text = """
        <FlexStatementResponse>
            <Status>Success</Status>
            <ReferenceCode>REQ123</ReferenceCode>
        </FlexStatementResponse>
        """
        success.raise_for_status = MagicMock()

        with patch("pyflexweb.client.requests.get", side_effect=[transient, success]) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertEqual(request_id, "REQ123")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(REPORT_GENERATION_RETRY_DELAYS_SECONDS[0])

    def test_request_report_stops_after_transient_retry_budget(self):
        """Persistent provider generation failures remain a visible failure."""
        transient = MagicMock()
        transient.text = """
        <FlexStatementResponse>
            <Status>Fail</Status>
            <ErrorCode>1012</ErrorCode>
            <ErrorMessage>Statement could not be generated at this time. Please try again shortly.</ErrorMessage>
        </FlexStatementResponse>
        """
        transient.raise_for_status = MagicMock()

        attempts = len(REPORT_GENERATION_RETRY_DELAYS_SECONDS) + 1
        with patch("pyflexweb.client.requests.get", return_value=transient) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertIsNone(request_id)
        self.assertEqual(mock_get.call_count, attempts)
        self.assertEqual(
            [call.args[0] for call in mock_sleep.call_args_list],
            list(REPORT_GENERATION_RETRY_DELAYS_SECONDS),
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

    def test_request_report_retries_dns_failure_seven_times_then_succeeds(self):
        """DNS failures get seven retries without reissuing a Flex query later."""
        dns_error = requests.exceptions.ConnectionError(socket.gaierror(-3, "Temporary failure in name resolution"))
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Success</Status>
            <ReferenceCode>REQ123</ReferenceCode>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        side_effects = [dns_error] * DNS_MAX_RETRIES + [mock_response]
        with patch("pyflexweb.client.requests.get", side_effect=side_effects) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertEqual(request_id, "REQ123")
        self.assertEqual(mock_get.call_count, DNS_MAX_RETRIES + 1)
        self.assertEqual(mock_sleep.call_count, DNS_MAX_RETRIES)
        self.assertEqual(
            [call.args[0] for call in mock_sleep.call_args_list],
            [1, 2, 4, 8, 16, 30, 30],
        )

    def test_request_report_does_not_retry_non_retryable_network_error(self):
        """Only DNS failures and timeouts receive the extra retry budget."""
        error = requests.exceptions.SSLError("certificate verify failed")
        with patch("pyflexweb.client.requests.get", side_effect=error) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertIsNone(request_id)
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    def test_request_report_passes_connect_and_read_timeout(self):
        """Every IBKR GET must bound both the connect and read phases.

        Regression guard for the 2026-08-19 incident: a `download` hung >4h on
        an ESTABLISHED read with no socket timeout and had to be killed by hand.
        """
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Success</Status>
            <ReferenceCode>REQ123</ReferenceCode>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        with patch("pyflexweb.client.requests.get", return_value=mock_response) as mock_get:
            self.client.request_report("123456")

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs.get("timeout"), REQUEST_TIMEOUT)

    def test_request_report_retries_read_timeout_then_succeeds(self):
        """A hung/never-responding read now gets a bounded retry instead of hanging forever."""
        timeout_error = requests.exceptions.ReadTimeout("Read timed out.")
        mock_response = MagicMock()
        mock_response.text = """
        <FlexStatementResponse>
            <Status>Success</Status>
            <ReferenceCode>REQ123</ReferenceCode>
        </FlexStatementResponse>
        """
        mock_response.raise_for_status = MagicMock()

        with patch("pyflexweb.client.requests.get", side_effect=[timeout_error, mock_response]) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertEqual(request_id, "REQ123")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(DNS_RETRY_DELAYS_SECONDS[0])

    def test_request_report_stops_after_timeout_retry_budget(self):
        """A connection IBKR never answers eventually surfaces as a failure, not a hang."""
        timeout_error = requests.exceptions.ConnectTimeout("connection timed out")
        with patch("pyflexweb.client.requests.get", side_effect=timeout_error) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                request_id = self.client.request_report("123456")

        self.assertIsNone(request_id)
        self.assertEqual(mock_get.call_count, DNS_MAX_RETRIES + 1)
        self.assertEqual(mock_sleep.call_count, DNS_MAX_RETRIES)

    def test_network_error_redacts_flex_token(self):
        """Requests errors must not leak the Flex token through the URL."""
        error = requests.exceptions.SSLError("failed for https://example.test/path?t=test_token&q=123456&v=3")
        with patch("pyflexweb.client.requests.get", side_effect=error):
            with patch("sys.stderr") as mock_stderr:
                self.client.request_report("123456")

        output = "".join(call[0][0] for call in mock_stderr.write.call_args_list)
        self.assertNotIn("test_token", output)
        self.assertIn("t=<redacted>", output)

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

    def test_get_report_retries_dns_failure_seven_times_then_succeeds(self):
        """Statement retrieval receives the same DNS-only retry policy."""
        dns_error = requests.exceptions.ConnectionError(socket.gaierror(-3, "Temporary failure in name resolution"))
        mock_response = MagicMock()
        mock_response.text = "<FlexQueryResponse>XML report content</FlexQueryResponse>"
        mock_response.raise_for_status = MagicMock()

        side_effects = [dns_error] * DNS_MAX_RETRIES + [mock_response]
        with patch("pyflexweb.client.requests.get", side_effect=side_effects) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                report_xml = self.client.get_report("REQ123")

        self.assertEqual(report_xml, "<FlexQueryResponse>XML report content</FlexQueryResponse>")
        self.assertEqual(mock_get.call_count, DNS_MAX_RETRIES + 1)
        self.assertEqual(mock_sleep.call_count, DNS_MAX_RETRIES)

    def test_get_report_passes_connect_and_read_timeout(self):
        """Statement retrieval must bound both the connect and read phases too."""
        mock_response = MagicMock()
        mock_response.text = "<FlexQueryResponse>XML report content</FlexQueryResponse>"
        mock_response.raise_for_status = MagicMock()

        with patch("pyflexweb.client.requests.get", return_value=mock_response) as mock_get:
            self.client.get_report("REQ123")

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs.get("timeout"), REQUEST_TIMEOUT)

    def test_get_report_retries_read_timeout_then_succeeds(self):
        """Statement retrieval receives the same bounded timeout-retry policy."""
        timeout_error = requests.exceptions.ReadTimeout("Read timed out.")
        mock_response = MagicMock()
        mock_response.text = "<FlexQueryResponse>XML report content</FlexQueryResponse>"
        mock_response.raise_for_status = MagicMock()

        with patch("pyflexweb.client.requests.get", side_effect=[timeout_error, mock_response]) as mock_get:
            with patch("pyflexweb.client.time.sleep") as mock_sleep:
                report_xml = self.client.get_report("REQ123")

        self.assertEqual(report_xml, "<FlexQueryResponse>XML report content</FlexQueryResponse>")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(DNS_RETRY_DELAYS_SECONDS[0])

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


def _flex_body(status: str, code: str | None, message: str | None) -> MagicMock:
    parts = [f"<Status>{status}</Status>"]
    if code is not None:
        parts.append(f"<ErrorCode>{code}</ErrorCode>")
    if message is not None:
        parts.append(f"<ErrorMessage>{message}</ErrorMessage>")
    resp = MagicMock()
    resp.text = "<FlexStatementResponse>" + "".join(parts) + "</FlexStatementResponse>"
    resp.raise_for_status = MagicMock()
    return resp


class TestFlexErrorParsing(unittest.TestCase):
    """ErrorCode/ErrorMessage parsing, classification and client.last_error."""

    def setUp(self):
        self.client = IBKRFlexClient("test_token")

    def _send(self, response):
        with patch("pyflexweb.client.requests.get", return_value=response), patch("sys.stderr") as err:
            with patch("pyflexweb.client.time.sleep"):
                result = self.client.request_report("123")
        return result, "".join(c[0][0] for c in err.write.call_args_list)

    def test_1012_token_expired(self):
        result, stderr = self._send(_flex_body("Fail", "1012", "Token has expired."))
        self.assertIsNone(result)
        self.assertEqual(self.client.last_error, FlexError(code="1012", message="Token has expired.", kind="token"))
        # Legacy line, byte for byte (external wrappers parse it).
        self.assertIn("Error requesting report: Token has expired.\n", stderr)
        self.assertNotIn("test_token", stderr)

    def test_1018_rate_limit(self):
        msg = "Too many requests have been made from this token. Please try again shortly."
        self._send(_flex_body("Fail", "1018", msg))
        self.assertEqual(self.client.last_error, FlexError(code="1018", message=msg, kind="rate_limit"))

    def test_error_message_only(self):
        self._send(_flex_body("Fail", None, "Token is invalid."))
        self.assertEqual(self.client.last_error, FlexError(code=None, message="Token is invalid.", kind="token"))
        self._send(_flex_body("Fail", None, "Something else went wrong"))
        self.assertEqual(self.client.last_error.kind, "other")

    def test_1019_getstatement_not_ready(self):
        msg = "Statement generation in progress. Please try again shortly."
        with patch("pyflexweb.client.requests.get", return_value=_flex_body("Warn", "1019", msg)), patch("sys.stderr") as err:
            self.assertIsNone(self.client.get_report("REF"))
        self.assertEqual(self.client.last_error, FlexError(code="1019", message=msg, kind="not_ready"))
        self.assertIn(f"Error retrieving report: {msg}", "".join(c[0][0] for c in err.write.call_args_list))

    def test_success_clears_last_error(self):
        self._send(_flex_body("Fail", "1012", "Token has expired."))
        ok = MagicMock(text="<FlexStatementResponse><Status>Success</Status><ReferenceCode>R1</ReferenceCode></FlexStatementResponse>")
        self.assertEqual(self._send(ok)[0], "R1")
        self.assertIsNone(self.client.last_error)

    def test_network_and_parse_errors(self):
        with patch("pyflexweb.client.requests.get", side_effect=requests.exceptions.ConnectionError("refused")), patch("sys.stderr"):
            self.client.request_report("123")
        self.assertEqual((self.client.last_error.code, self.client.last_error.kind), (None, "other"))
        self._send(MagicMock(text="<ErrorCode>broken"))
        self.assertEqual((self.client.last_error.code, self.client.last_error.kind), (None, "other"))

    def test_transient_retry_unchanged_and_never_token(self):
        transient = "Statement could not be generated at this time. Please try again shortly."
        with patch("pyflexweb.client.requests.get", return_value=_flex_body("Fail", "1012", transient)) as get:
            with patch("pyflexweb.client.time.sleep"), patch("sys.stderr"):
                self.assertIsNone(self.client.request_report("123"))
        self.assertEqual(get.call_count, len(REPORT_GENERATION_RETRY_DELAYS_SECONDS) + 1)
        self.assertEqual(self.client.last_error.kind, "not_ready")

    def test_classification_table(self):
        cases = {
            ("1011", None): "token",
            ("1012", None): "token",
            ("1013", None): "token",
            ("1015", None): "token",
            ("1018", None): "rate_limit",
            ("1001", None): "not_ready",
            ("1004", None): "not_ready",
            ("1009", None): "not_ready",
            ("1019", None): "not_ready",
            ("1021", None): "not_ready",
            ("1003", None): "other",
            ("1014", None): "other",
            ("1020", None): "other",
            (None, "TOKEN HAS EXPIRED."): "token",
            (None, "Token is invalid."): "token",
            (None, None): "other",
        }
        for (code, message), kind in cases.items():
            with self.subTest(code=code, message=message):
                self.assertEqual(classify_flex_error(code, message), kind)


if __name__ == "__main__":
    unittest.main()
