"""Client module for communicating with IBKR Flex Web Service."""

import re
import socket
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

# IBKR has been observed to accept the TCP connection and then never send a
# byte back: a `download` hung >4h on an ESTABLISHED read with no timeout
# (2026-08-19, killed manually). Bound both the connect and read phases so a
# stuck request fails instead of hanging forever. The read timeout applies
# per-chunk (time since the last byte), not to the whole request, so this
# does not cut off a slow-but-progressing transfer.
CONNECT_TIMEOUT_SECONDS = 30
READ_TIMEOUT_SECONDS = 120
REQUEST_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

DNS_MAX_RETRIES = 7
DNS_RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 16, 30, 30)
# IBKR's explicit "try again shortly" response has persisted beyond the old
# 90-second window in production.  Keep this bounded below the daily-sync
# scheduler ceiling while allowing a transient generation outage to clear.
REPORT_GENERATION_RETRY_DELAYS_SECONDS = (30, 60, 120, 240)
REPORT_GENERATION_TRANSIENT_MESSAGE = "statement could not be generated at this time. please try again shortly."

# Flex Web Service error codes -> (kind, IBKR's standard message).
# Source: IBKR's Flex Web Service error-code list ("Error Codes" table of the
# Flex Web Service page in the IBKR Client Portal guide / IBKR Campus API docs).
# kind: 'token'      the token (or the account behind it) is refused; retrying
#                    with the same token is pointless, a human must act.
#       'rate_limit' too many requests from this token.
#       'not_ready'  IBKR's "please try again shortly" family.
#       'other'      everything else (bad query, bad reference code, ...).
# Codes not listed here classify as 'other'.
FLEX_ERROR_CODES: dict[str, tuple[str, str]] = {
    "1001": ("not_ready", "Statement could not be generated at this time. Please try again shortly."),
    "1003": ("other", "Statement is not available."),
    "1004": ("not_ready", "Statement is incomplete at this time. Please try again shortly."),
    "1005": ("not_ready", "Settlement data is not ready at this time. Please try again shortly."),
    "1006": ("not_ready", "FIFO P/L data is not ready at this time. Please try again shortly."),
    "1007": ("not_ready", "MTM P/L data is not ready at this time. Please try again shortly."),
    "1008": ("not_ready", "MTM and FIFO P/L data is not ready at this time. Please try again shortly."),
    "1009": ("not_ready", "The server is under heavy load. Statement could not be generated at this time. Please try again shortly."),
    "1010": ("other", "Legacy Flex Queries are no longer supported. Please convert over to Activity Flex."),
    "1011": ("token", "Service account is inactive."),
    "1012": ("token", "Token has expired."),
    "1013": ("token", "IP restriction."),
    "1014": ("other", "Query is invalid."),
    "1015": ("token", "Token is invalid."),
    "1016": ("other", "Account in invalid."),
    "1017": ("other", "Reference code is invalid."),
    "1018": ("rate_limit", "Too many requests have been made from this token. Please try again shortly."),
    "1019": ("not_ready", "Statement generation in progress. Please try again shortly."),
    "1020": ("other", "Invalid request or unable to validate request."),
    "1021": ("not_ready", "Statement could not be retrieved at this time. Please try again shortly."),
}

# Used only when the answer carries no (known) ErrorCode.
TOKEN_ERROR_MESSAGE_MARKERS = ("token has expired", "token is invalid")


@dataclass(frozen=True)
class FlexError:
    """The last error a Flex call returned (IBKR ErrorCode/ErrorMessage, or a network/parse failure)."""

    code: str | None
    message: str | None
    kind: str  # 'token' | 'rate_limit' | 'not_ready' | 'other'


def _normalize(message: str | None) -> str:
    return " ".join((message or "").lower().split())


def classify_flex_error(code: str | None, message: str | None) -> str:
    """Classify a Flex error as 'token', 'rate_limit', 'not_ready' or 'other'.

    The code decides. The one exception is IBKR's "statement could not be
    generated at this time. please try again shortly." text, which this client
    already treats as transient whatever code comes with it: it is classed
    'not_ready' so a transient outage is never reported as a refused token.
    With no known code, a "token has expired" / "token is invalid" message
    classes as 'token'.
    """
    normalized = _normalize(message)
    if normalized == REPORT_GENERATION_TRANSIENT_MESSAGE:
        return "not_ready"
    code = (code or "").strip() or None
    if code in FLEX_ERROR_CODES:
        return FLEX_ERROR_CODES[code][0]
    if any(marker in normalized for marker in TOKEN_ERROR_MESSAGE_MARKERS):
        return "token"
    return "other"


def _flex_error_from_xml(root: ET.Element) -> FlexError:
    """Read ErrorCode/ErrorMessage. The message is kept exactly as IBKR sent it."""
    code_node = root.find(".//ErrorCode")
    message_node = root.find(".//ErrorMessage")
    code = ((code_node.text or "").strip() or None) if code_node is not None else None
    message = message_node.text if message_node is not None else None
    return FlexError(code=code, message=message, kind=classify_flex_error(code, message))


def _is_dns_error(error: BaseException) -> bool:
    """Return True only for name-resolution failures."""
    if isinstance(error, socket.gaierror):
        return True

    pending: list[object] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        if type(current).__name__ == "NameResolutionError":
            return True
        if isinstance(current, BaseException):
            pending.extend(
                candidate
                for candidate in (
                    current.__cause__,
                    current.__context__,
                    getattr(current, "reason", None),
                    getattr(current, "_reason", None),
                    *current.args,
                )
                if candidate is not None
            )

    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "name resolution",
            "name or service not known",
            "temporary failure in name resolution",
            "failed to resolve",
            "getaddrinfo failed",
            "nodename nor servname provided",
        )
    )


def _is_retryable_network_error(error: BaseException) -> bool:
    """Return True for DNS failures and connect/read timeouts — worth a bounded retry.

    Everything else (refused connections, TLS errors, HTTP-level failures)
    still fails closed on the first attempt.
    """
    if isinstance(error, requests.exceptions.Timeout):
        return True
    return _is_dns_error(error)


def _safe_network_error(error: BaseException) -> str:
    """Redact the Flex token if Requests includes the URL in an exception."""
    return re.sub(r"([?&]t=)[^&\s)]+", r"\1<redacted>", str(error))


def _get_with_dns_retries(url: str) -> requests.Response:
    """GET with a connect/read timeout, retrying DNS failures and timeouts.

    Both failure modes share the same bounded backoff schedule (seven
    retries, up to 30s apart) so a transient blip — a resolver hiccup or a
    connection IBKR accepted but never answered — clears without a human
    having to kill a hung process.
    """
    for attempt in range(DNS_MAX_RETRIES + 1):
        try:
            return requests.get(url, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as error:
            if not _is_retryable_network_error(error) or attempt == DNS_MAX_RETRIES:
                raise
            delay = DNS_RETRY_DELAYS_SECONDS[attempt]
            reason = "Request timed out" if isinstance(error, requests.exceptions.Timeout) else "DNS resolution failed"
            print(
                f"{reason}; retry {attempt + 1}/{DNS_MAX_RETRIES} in {delay}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


class IBKRFlexClient:
    """Handles communication with the IBKR Flex Web Service."""

    BASE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet"
    REQUEST_URL = f"{BASE_URL}/FlexStatementService.SendRequest"
    STATEMENT_URL = f"{BASE_URL}/FlexStatementService.GetStatement"

    def __init__(self, token: str):
        self.token = token
        # Error from the most recent request_report()/get_report() call, or None
        # if that call succeeded (or, for get_report, the answer was not an error).
        self.last_error: FlexError | None = None

    def request_report(self, query_id: str) -> str | None:
        """Request a report from IBKR and return the request ID if successful.

        On failure returns None and leaves the reason in self.last_error.
        """
        url = f"{self.REQUEST_URL}?t={self.token}&q={query_id}&v=3"
        self.last_error = None

        for attempt in range(len(REPORT_GENERATION_RETRY_DELAYS_SECONDS) + 1):
            try:
                response = _get_with_dns_retries(url)
                response.raise_for_status()

                # Parse the XML response
                root = ET.fromstring(response.text)
                status_node = root.find(".//Status")
                status = status_node.text if status_node is not None else None

                if status == "Success":
                    request_id = root.find(".//ReferenceCode").text
                    return request_id

                error = _flex_error_from_xml(root)
                self.last_error = error
                normalized = _normalize(error.message)
                if normalized == REPORT_GENERATION_TRANSIENT_MESSAGE and attempt < len(REPORT_GENERATION_RETRY_DELAYS_SECONDS):
                    delay = REPORT_GENERATION_RETRY_DELAYS_SECONDS[attempt]
                    print(
                        "IBKR report generation temporarily unavailable; "
                        f"retry {attempt + 1}/{len(REPORT_GENERATION_RETRY_DELAYS_SECONDS)} in {delay}s...",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(delay)
                    continue

                # Byte-for-byte the pre-v7 line: external wrappers parse it.
                legacy_text = error.message if root.find(".//ErrorMessage") is not None else "Unknown Flex error"
                print(f"Error requesting report: {legacy_text}", file=sys.stderr, flush=True)
                return None

            except requests.exceptions.RequestException as e:
                message = f"Network error: {_safe_network_error(e)}"
                self.last_error = FlexError(code=None, message=message, kind="other")
                print(message, file=sys.stderr, flush=True)
                return None
            except ET.ParseError as e:
                message = f"Error parsing response: {e}"
                self.last_error = FlexError(code=None, message=message, kind="other")
                print(message, file=sys.stderr, flush=True)
                return None

        raise AssertionError("unreachable")

    def get_report(self, request_id: str) -> str | None:
        """Get a report using the request ID. Returns the XML content if successful.

        Returns None when the report is not ready or on error; the IBKR answer
        (or network/parse failure) is left in self.last_error.
        """
        url = f"{self.STATEMENT_URL}?t={self.token}&q={request_id}&v=3"
        self.last_error = None

        try:
            response = _get_with_dns_retries(url)
            response.raise_for_status()

            # Check if this is an error response
            if "<ErrorCode>" in response.text:
                root = ET.fromstring(response.text)
                status_node = root.find(".//Status")
                status = status_node.text if status_node is not None else None
                self.last_error = _flex_error_from_xml(root)

                if status == "Pending":
                    return None  # Report not ready yet

                # Byte-for-byte the pre-v7 line: external wrappers parse it.
                if root.find(".//ErrorMessage") is not None:
                    print(f"Error retrieving report: {self.last_error.message}", file=sys.stderr, flush=True)
                return None

            # If we got here, we have the actual report
            return response.text

        except requests.exceptions.RequestException as e:
            message = f"Network error: {_safe_network_error(e)}"
            self.last_error = FlexError(code=None, message=message, kind="other")
            print(message, file=sys.stderr, flush=True)
            return None
        except ET.ParseError as e:
            message = f"Error parsing response: {e}"
            self.last_error = FlexError(code=None, message=message, kind="other")
            print(message, file=sys.stderr, flush=True)
            return None
