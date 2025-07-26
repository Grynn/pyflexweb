"""Client module for communicating with IBKR Flex Web Service."""

import sys
import xml.etree.ElementTree as ET

import requests


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

        try:
            response = requests.get(url)
            response.raise_for_status()

            # Parse the XML response
            root = ET.fromstring(response.text)
            status = root.find(".//Status").text

            if status == "Success":
                request_id = root.find(".//ReferenceCode").text
                return request_id
            else:
                error = root.find(".//ErrorMessage").text
                print(f"Error requesting report: {error}", file=sys.stderr)
                return None

        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}", file=sys.stderr)
            return None
        except ET.ParseError as e:
            print(f"Error parsing response: {e}", file=sys.stderr)
            return None

    def get_report(self, request_id: str) -> str | None:
        """Get a report using the request ID. Returns the XML content if successful."""
        url = f"{self.STATEMENT_URL}?t={self.token}&q={request_id}&v=3"

        try:
            response = requests.get(url)
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
            print(f"Network error: {e}", file=sys.stderr)
            return None
        except ET.ParseError as e:
            print(f"Error parsing response: {e}", file=sys.stderr)
            return None
