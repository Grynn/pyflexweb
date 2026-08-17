"""Client module for communicating with IBKR Flex Web Service."""

import re
import socket
import sys
import time
import xml.etree.ElementTree as ET

import requests

DNS_MAX_RETRIES = 7
DNS_RETRY_DELAYS_SECONDS = (1, 2, 4, 8, 16, 30, 30)
# IBKR's explicit "try again shortly" response has persisted beyond the old
# 90-second window in production.  Keep this bounded below the daily-sync
# scheduler ceiling while allowing a transient generation outage to clear.
REPORT_GENERATION_RETRY_DELAYS_SECONDS = (30, 60, 120, 240)
REPORT_GENERATION_TRANSIENT_MESSAGE = "statement could not be generated at this time. please try again shortly."


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


def _safe_network_error(error: BaseException) -> str:
    """Redact the Flex token if Requests includes the URL in an exception."""
    return re.sub(r"([?&]t=)[^&\s)]+", r"\1<redacted>", str(error))


def _get_with_dns_retries(url: str) -> requests.Response:
    """GET once normally, then retry DNS failures seven times."""
    for attempt in range(DNS_MAX_RETRIES + 1):
        try:
            return requests.get(url)
        except requests.exceptions.RequestException as error:
            if not _is_dns_error(error) or attempt == DNS_MAX_RETRIES:
                raise
            delay = DNS_RETRY_DELAYS_SECONDS[attempt]
            print(
                f"DNS resolution failed; retry {attempt + 1}/{DNS_MAX_RETRIES} in {delay}s...",
                file=sys.stderr,
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

    def request_report(self, query_id: str) -> str | None:
        """Request a report from IBKR and return the request ID if successful."""
        url = f"{self.REQUEST_URL}?t={self.token}&q={query_id}&v=3"

        for attempt in range(len(REPORT_GENERATION_RETRY_DELAYS_SECONDS) + 1):
            try:
                response = _get_with_dns_retries(url)
                response.raise_for_status()

                # Parse the XML response
                root = ET.fromstring(response.text)
                status = root.find(".//Status").text

                if status == "Success":
                    request_id = root.find(".//ReferenceCode").text
                    return request_id

                error_node = root.find(".//ErrorMessage")
                error = error_node.text if error_node is not None else "Unknown Flex error"
                normalized = " ".join(error.lower().split())
                if normalized == REPORT_GENERATION_TRANSIENT_MESSAGE and attempt < len(REPORT_GENERATION_RETRY_DELAYS_SECONDS):
                    delay = REPORT_GENERATION_RETRY_DELAYS_SECONDS[attempt]
                    print(
                        "IBKR report generation temporarily unavailable; "
                        f"retry {attempt + 1}/{len(REPORT_GENERATION_RETRY_DELAYS_SECONDS)} in {delay}s...",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                    continue

                print(f"Error requesting report: {error}", file=sys.stderr)
                return None

            except requests.exceptions.RequestException as e:
                print(f"Network error: {_safe_network_error(e)}", file=sys.stderr)
                return None
            except ET.ParseError as e:
                print(f"Error parsing response: {e}", file=sys.stderr)
                return None

        raise AssertionError("unreachable")

    def get_report(self, request_id: str) -> str | None:
        """Get a report using the request ID. Returns the XML content if successful."""
        url = f"{self.STATEMENT_URL}?t={self.token}&q={request_id}&v=3"

        try:
            response = _get_with_dns_retries(url)
            response.raise_for_status()

            # Check if this is an error response
            if "<ErrorCode>" in response.text:
                root = ET.fromstring(response.text)
                status = root.find(".//Status").text

                if status == "Pending":
                    return None  # Report not ready yet

                error = root.find(".//ErrorMessage")
                if error is not None:
                    print(f"Error retrieving report: {error.text}", file=sys.stderr)
                return None

            # If we got here, we have the actual report
            return response.text

        except requests.exceptions.RequestException as e:
            print(f"Network error: {_safe_network_error(e)}", file=sys.stderr)
            return None
        except ET.ParseError as e:
            print(f"Error parsing response: {e}", file=sys.stderr)
            return None
