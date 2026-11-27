"""End-to-end tests for token rejection, request_errors, exit codes, the download
lock, `download --type`, token expiry records and `query type`.

Every test runs the real CLI against a real status.db in a temp directory; IBKR
HTTP is mocked at `pyflexweb.client.requests.get` (no network).
"""

import fcntl
import glob
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from click.testing import CliRunner

from pyflexweb import database as database_module
from pyflexweb.cli import cli, main
from pyflexweb.client import FlexError
from pyflexweb.database import FlexDatabase, MigrationError
from pyflexweb.handlers import (
    INTER_QUERY_DELAY_SECONDS,
    _token_rejected_line,
    describe_token_expiry,
    parse_token_expiry,
    token_days_left,
)

TOKEN_EXPIRED_BODY = """<FlexStatementResponse timestamp="27 November, 2026 09:00 AM EST">
<Status>Fail</Status>
<ErrorCode>1012</ErrorCode>
<ErrorMessage>Token has expired.</ErrorMessage>
</FlexStatementResponse>"""

INVALID_QUERY_BODY = """<FlexStatementResponse>
<Status>Fail</Status>
<ErrorCode>1014</ErrorCode>
<ErrorMessage>Query is invalid.</ErrorMessage>
</FlexStatementResponse>"""


def _success_body(ref: str) -> str:
    return f"<FlexStatementResponse><Status>Success</Status><ReferenceCode>{ref}</ReferenceCode></FlexStatementResponse>"


def _response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _runner() -> CliRunner:
    try:  # click < 8.2
        return CliRunner(mix_stderr=False)
    except TypeError:  # click >= 8.2 always separates stderr
        return CliRunner()


class FakeIBKR:
    """Routes mocked requests.get calls by endpoint and token."""

    def __init__(self, send_by_token: dict[str, str]):
        self.send_by_token = send_by_token
        self.calls: list[tuple[str, str, str]] = []  # (endpoint, token, q)
        self.sent = 0

    def __call__(self, url, timeout=None):
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        token, q = params["t"][0], params["q"][0]
        endpoint = parsed.path.rsplit(".", 1)[-1]
        self.calls.append((endpoint, token, q))
        if endpoint == "SendRequest":
            body = self.send_by_token[token]
            self.sent += 1  # unique reference code per SendRequest, as IBKR issues
            return _response(body.replace("{q}", f"{q}-{self.sent}"))
        return _response(f"<FlexQueryResponse queryName='{q}'>report</FlexQueryResponse>")

    def requests_for(self, token: str) -> list:
        return [c for c in self.calls if c[1] == token]


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        self.addCleanup(shutil.rmtree, self.out_dir, True)
        self.runner = _runner()
        sleep_patcher = patch("time.sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def invoke(self, *argv):
        return self.runner.invoke(cli, list(argv), env={"PYFLEXWEB_DATA_DIR": self.data_dir})

    def db(self) -> FlexDatabase:
        db = FlexDatabase(self.data_dir)
        self.addCleanup(db.close)
        return db

    def download(self, fake: FakeIBKR, *extra):
        with patch("pyflexweb.client.requests.get", side_effect=fake):
            return self.invoke("download", "--output-dir", self.out_dir, "--poll-interval", "1", "--max-attempts", "2", *extra)


class TestTokenRejection(CliTestCase):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add_account("U1317359", "Cerabella/Master", "tok_expired_secret")
        db.add_account("U11049821", "CCUK", "tok_good_secret")
        db.add_query("111", "Cera activity", account_id="U1317359")
        db.add_query("222", "CCUK activity", account_id="U11049821")
        db.add_query("333", "Cera trades", query_type="trade-confirmation", account_id="U1317359")
        db.close()

    def test_token_rejection_writes_errors_skips_account_and_exits_3(self):
        fake = FakeIBKR({"tok_expired_secret": TOKEN_EXPIRED_BODY, "tok_good_secret": _success_body("REF-{q}")})
        result = self.download(fake)

        self.assertEqual(result.exit_code, 3, result.output + result.stderr)

        # Only ONE request was sent with the rejected token; query 333 never hit HTTP.
        self.assertEqual(fake.requests_for("tok_expired_secret"), [("SendRequest", "tok_expired_secret", "111")])
        self.assertNotIn("333", [c[2] for c in fake.calls])
        # The other account still downloaded (SendRequest + GetStatement).
        self.assertEqual([c[0] for c in fake.requests_for("tok_good_secret")], ["SendRequest", "GetStatement"])

        # Legacy lines are still printed, byte for byte, alongside the new one.
        self.assertIn("Error requesting report: Token has expired.\n", result.stderr)
        self.assertIn("  Failed to request report.\n", result.output)
        self.assertIn("Downloading: Cera activity (ID: 111)\n", result.output)
        token_lines = [line for line in result.stderr.splitlines() if line.startswith("TOKEN REJECTED:")]
        self.assertEqual(
            token_lines,
            [
                "TOKEN REJECTED: IBKR refused the Flex token of account U1317359 (Cerabella/Master): 1012 Token has expired. "
                "Create a new token in Client Portal (Performance & Reports > Flex Queries > Flex Web Service) and run: "
                'pyflexweb account add U1317359 --name "Cerabella/Master" --token <new token> --expires "<expiry shown by IBKR>"'
            ],
        )
        self.assertIn("  Skipped: token of account U1317359 was rejected earlier in this run\n", result.output)

        # Tokens are never printed.
        for text in (result.output, result.stderr):
            self.assertNotIn("tok_expired_secret", text)
            self.assertNotIn("tok_good_secret", text)

        db = self.db()
        errors = db.list_request_errors()
        self.assertEqual(
            [(e["query_id"], e["account_id"], e["stage"], e["error_code"], e["error_message"], e["kind"]) for e in errors],
            [
                ("111", "U1317359", "send", "1012", "Token has expired.", "token"),
                ("333", "U1317359", "skipped", "1012", "Token has expired.", "token"),
            ],
        )
        for e in errors:
            datetime.strptime(e["occurred_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(db.get_latest_request("222")["status"], "completed")

        # Pacing: exactly one 120 s wait (before the 2nd request actually sent).
        waits = [c.args[0] for c in self.sleep.call_args_list if c.args and c.args[0] == INTER_QUERY_DELAY_SECONDS]
        self.assertEqual(len(waits), 1)

    def test_non_token_failure_exits_1(self):
        fake = FakeIBKR({"tok_expired_secret": INVALID_QUERY_BODY, "tok_good_secret": _success_body("REF-{q}")})
        result = self.download(fake)
        self.assertEqual(result.exit_code, 1, result.output + result.stderr)
        self.assertNotIn("TOKEN REJECTED", result.stderr)
        self.assertIn("Error requesting report: Query is invalid.\n", result.stderr)
        # A non-token failure does not stop the account's other queries.
        self.assertIn("333", [c[2] for c in fake.calls])
        kinds = {(e["query_id"], e["stage"], e["kind"]) for e in self.db().list_request_errors()}
        self.assertEqual(kinds, {("111", "send", "other"), ("333", "send", "other")})

    def test_success_exits_0_and_up_to_date_exits_0(self):
        fake = FakeIBKR({"tok_expired_secret": _success_body("REF-{q}"), "tok_good_secret": _success_body("REF-{q}")})
        self.assertEqual(self.download(fake).exit_code, 0)
        again = self.download(fake)
        self.assertEqual(again.exit_code, 0)
        self.assertIn("All queries are up to date. Use --force to download anyway.", again.output)
        self.assertEqual(self.db().list_request_errors(), [])

    def test_success_keeps_old_error_rows(self):
        db = self.db()
        db.add_request_error("222", "U11049821", "send", "1018", "Too many requests", "rate_limit")
        fake = FakeIBKR({"tok_expired_secret": _success_body("REF-{q}"), "tok_good_secret": _success_body("REF-{q}")})
        self.assertEqual(self.download(fake, "--query", "222").exit_code, 0)
        self.assertEqual(len(self.db().list_request_errors("222")), 1)

    def test_get_stage_failure_records_last_getstatement_error(self):
        pending = (
            "<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
            "<ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage></FlexStatementResponse>"
        )
        fake = FakeIBKR({"tok_good_secret": _success_body("REF-{q}")})

        def route(url, timeout=None):
            if "GetStatement" in url:
                fake.calls.append(("GetStatement", "tok_good_secret", "REF"))
                return _response(pending)
            return fake(url, timeout)

        with patch("pyflexweb.client.requests.get", side_effect=route):
            result = self.invoke("download", "--query", "222", "--output-dir", self.out_dir, "--poll-interval", "1", "--max-attempts", "2")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("  Report not available after 2 attempts.", result.output)
        self.assertIn("Error retrieving report: Statement generation in progress. Please try again shortly.", result.stderr)
        db = self.db()
        self.assertEqual(db.get_latest_request("222")["status"], "failed")
        [row] = db.list_request_errors("222")
        self.assertEqual((row["stage"], row["error_code"], row["kind"]), ("get", "1019", "not_ready"))

    def test_main_entry_point_returns_handler_exit_code(self):
        fake = FakeIBKR({"tok_expired_secret": TOKEN_EXPIRED_BODY, "tok_good_secret": _success_body("REF-{q}")})
        argv = ["pyflexweb", "download", "--query", "111", "--output-dir", self.out_dir]
        with patch.dict(os.environ, {"PYFLEXWEB_DATA_DIR": self.data_dir}):
            with patch("sys.argv", argv), patch("pyflexweb.client.requests.get", side_effect=fake):
                with self.assertRaises(SystemExit) as cm:
                    main()
        self.assertEqual(cm.exception.code, 3)

    def test_main_entry_point_usage_and_help_codes_unchanged(self):
        with patch.dict(os.environ, {"PYFLEXWEB_DATA_DIR": self.data_dir}):
            for argv, code in ((["pyflexweb", "--help"], 0), (["pyflexweb", "download", "--bogus"], 2)):
                with patch("sys.argv", argv), self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, code, argv)

    def test_other_commands_propagate_exit_code(self):
        self.assertEqual(self.invoke("query", "remove", "nope").exit_code, 1)
        self.assertEqual(self.invoke("account", "rm", "nope").exit_code, 1)
        self.assertEqual(self.invoke("query", "list").exit_code, 0)


class TestDownloadType(CliTestCase):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add_account("U1", "One", "tok1")
        db.add_query("A1", "Activity 1", query_type="activity", account_id="U1")
        db.add_query("T1", "Trades 1", query_type="trade-confirmation", account_id="U1")
        db.add_query("T2", "Trades 2", query_type="trade-confirmation", account_id="U1")
        db.close()

    def test_type_filter_only_requests_that_type(self):
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake, "--type", "trade-confirmation")
        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        sent = [c[2] for c in fake.calls if c[0] == "SendRequest"]
        self.assertEqual(sent, ["T1", "T2"])
        self.assertIsNone(self.db().get_latest_request("A1"))
        waits = [c for c in self.sleep.call_args_list if c.args and c.args[0] == INTER_QUERY_DELAY_SECONDS]
        self.assertEqual(len(waits), 1)

    def test_type_with_force_and_up_to_date(self):
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        self.download(fake, "--type", "trade-confirmation")
        again = self.download(fake, "--type", "trade-confirmation")
        self.assertEqual(again.exit_code, 0)
        self.assertIn("All trade-confirmation queries are up to date.", again.output)
        fake.calls.clear()
        forced = self.download(fake, "--type", "trade-confirmation", "--force")
        self.assertEqual(forced.exit_code, 0, forced.output + forced.stderr + repr(forced.exception))
        self.assertEqual([c[2] for c in fake.calls if c[0] == "SendRequest"], ["T1", "T2"])

    def test_type_with_specific_query_is_usage_error(self):
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake, "--type", "activity", "--query", "A1")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(fake.calls, [])

    def test_no_query_of_type_registered_exits_0(self):
        db = self.db()
        db.remove_query("T1")
        db.remove_query("T2")
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake, "--type", "trade-confirmation")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No trade-confirmation queries registered.", result.output)
        self.assertEqual(fake.calls, [])


class TestDownloadLock(CliTestCase):
    def setUp(self):
        super().setUp()
        db = self.db()
        db.add_account("U1", "One", "tok1")
        db.add_query("A1", "Activity 1", account_id="U1")
        db.close()
        self.lock_path = os.path.join(self.data_dir, "download.lock")

    def _hold_lock(self):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o664)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(os.close, fd)
        return fd

    def test_held_lock_exits_4_without_http(self):
        self._hold_lock()
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake)
        self.assertEqual(result.exit_code, 4)
        self.assertEqual(fake.calls, [])
        self.assertIn(f"Another pyflexweb download is running (lock: {self.lock_path}); nothing was requested.\n", result.stderr)

    def test_wait_lock_polls_then_gives_up(self):
        self._hold_lock()
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake, "--wait-lock", "3")
        self.assertEqual(result.exit_code, 4)
        self.assertEqual(fake.calls, [])
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1, 1, 1])

    def test_lock_released_after_run_and_file_kept(self):
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        self.assertEqual(self.download(fake).exit_code, 0)
        self.assertTrue(os.path.exists(self.lock_path))
        self.assertEqual(os.stat(self.lock_path).st_mode & 0o777, 0o664)
        fd = os.open(self.lock_path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if still held
        finally:
            os.close(fd)

    def test_other_commands_take_no_lock(self):
        self._hold_lock()
        self.assertEqual(self.invoke("query", "list").exit_code, 0)
        self.assertEqual(self.invoke("account", "list").exit_code, 0)


class TestAccountExpiry(CliTestCase):
    def test_add_with_expiry_then_readd_keeps_name_clears_expiry_resets_added_on(self):
        result = self.invoke("account", "add", "U1", "--name", "Main", "--token", "tok_a", "--expires", "2027-10-29 11:30 EDT")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Account U1 (Main) added.", result.output)
        db = self.db()
        acct = db.get_account("U1")
        self.assertEqual(acct["token_expires_at"], "2027-10-29T15:30:00Z")
        # Age the added_on so the reset is observable.
        db.conn.execute("UPDATE accounts SET added_on = '2025-01-01 00:00:00' WHERE id = 'U1'")
        db.conn.commit()

        result = self.invoke("account", "add", "U1", "--token", "tok_b")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Account U1 added.\n  Existing account: token replaced, name kept (Main).", result.output)
        self.assertIn('Token expiry not recorded. Record it with: pyflexweb account expiry U1 "<expiry shown by IBKR>"', result.output)
        acct = self.db().get_account("U1")
        self.assertEqual(acct["name"], "Main")
        self.assertEqual(acct["token"], "tok_b")
        self.assertIsNone(acct["token_expires_at"])
        self.assertGreater(acct["added_on"], "2026-01-01")

    def test_add_with_invalid_expiry_changes_nothing(self):
        self.invoke("account", "add", "U1", "--name", "Main", "--token", "tok_a")
        result = self.invoke("account", "add", "U1", "--token", "tok_b", "--expires", "29/10/2027 11:30 EDT")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Example: 2027-10-29 11:30 EDT", result.output)
        self.assertEqual(self.db().get_account("U1")["token"], "tok_a")

    def test_expiry_command_set_show_unset_unknown(self):
        self.invoke("account", "add", "U1", "--token", "tok_a")
        # Unquoted words are joined, so the portal text can be pasted as-is.
        result = self.invoke("account", "expiry", "U1", "2027-01-15", "11:30", "EST")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.db().get_account("U1")["token_expires_at"], "2027-01-15T16:30:00Z")
        shown = self.invoke("account", "expiry", "U1")
        self.assertIn("2027-01-15T16:30:00Z", shown.output)
        self.assertEqual(self.invoke("account", "expiry", "U1", "--unset").exit_code, 0)
        self.assertIsNone(self.db().get_account("U1")["token_expires_at"])
        self.assertIn("Token expiry not recorded", self.invoke("account", "expiry", "U1").output)
        self.assertEqual(self.invoke("account", "expiry", "NOPE").exit_code, 1)
        self.assertEqual(self.invoke("account", "expiry", "NOPE", "2027-01-01").exit_code, 1)
        self.assertEqual(self.invoke("account", "expiry", "U1", "garbage").exit_code, 1)

    def test_list_json_has_no_token(self):
        soon = (datetime.now(UTC) + timedelta(days=10, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        past = (datetime.now(UTC) - timedelta(days=3, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = self.db()
        db.add_account("U1", "One", "tok_secret_one_123", token_expires_at=soon)
        db.add_account("U2", None, "tok_secret_two_456", token_expires_at=past)
        db.add_account("U3", "Three", "tok_secret_three_789")
        result = self.invoke("account", "list", "--json")
        self.assertEqual(result.exit_code, 0)
        for secret in ("tok_secret", "tok_secr", "tok_"):
            self.assertNotIn(secret, result.output)
        rows = {r["id"]: r for r in json.loads(result.output)}
        self.assertEqual(set(rows["U1"]), {"id", "name", "added_on", "token_expires_at", "days_left"})
        self.assertEqual(rows["U1"]["days_left"], 10)
        self.assertEqual(rows["U2"]["days_left"], -4)
        self.assertIsNone(rows["U3"]["days_left"])
        self.assertIsNone(rows["U3"]["token_expires_at"])

        table = self.invoke("account", "list").output
        self.assertIn("(in 10 days)", table)
        self.assertIn("(EXPIRED 3 days ago)", table)  # JSON days_left is floored (-4); the text is not
        self.assertIn("unknown", table)


class TestParseTokenExpiry(unittest.TestCase):
    def test_accepted_forms(self):
        cases = {
            "2027-10-29": "2027-10-29T00:00:00Z",
            "2027-10-29 11:30Z": "2027-10-29T11:30:00Z",
            "2027-10-29T11:30:45Z": "2027-10-29T11:30:45Z",
            "2027-10-29 11:30+05:30": "2027-10-29T06:00:00Z",
            "2027-10-29 11:30 -04:00": "2027-10-29T15:30:00Z",
            "2027-10-29T11:30:00-04:00": "2027-10-29T15:30:00Z",
            "2027-10-29 11:30 EDT": "2027-10-29T15:30:00Z",
            "2027-10-29 11:30 ET": "2027-10-29T15:30:00Z",
            "2027-10-29 11:30:15 est": "2027-10-29T15:30:15Z",  # zone decides, not the abbreviation
            "2027-01-15 11:30 EST": "2027-01-15T16:30:00Z",
            "2027-01-15 11:30 EDT": "2027-01-15T16:30:00Z",  # wrong abbreviation still resolves by date
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_token_expiry(text), expected)

    def test_dst_boundaries(self):
        # US DST 2027 starts Sun 14 Mar 02:00 and ends Sun 7 Nov 02:00 (America/New_York).
        self.assertEqual(parse_token_expiry("2027-03-13 12:00 EST"), "2027-03-13T17:00:00Z")
        self.assertEqual(parse_token_expiry("2027-03-14 12:00 EST"), "2027-03-14T16:00:00Z")  # already EDT
        self.assertEqual(parse_token_expiry("2027-11-06 12:00 EDT"), "2027-11-06T16:00:00Z")
        self.assertEqual(parse_token_expiry("2027-11-07 12:00 EDT"), "2027-11-07T17:00:00Z")  # already EST

    def test_rejected_forms(self):
        for text in (
            "",
            "29/10/2027 11:30 EDT",
            "10/29/2027",
            "2027-10-29 11:30",  # naive
            "2027-10-29T11:30:00",  # naive
            "2027-10-29 11:30 PST",
            "2027-10-29 11:30 IST",
            "2027-02-30",
            "2027-10-29 25:00Z",
            "2027-10-29 11:30+24:00",
            "Oct 29, 2027",
            "2027-10-29 11:30 EDT extra",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as cm:
                    parse_token_expiry(text)
                self.assertIn("Example: 2027-10-29 11:30 EDT", str(cm.exception))

    def test_days_left_floors(self):
        now = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
        self.assertEqual(token_days_left("2027-01-11T13:00:00Z", now), 10)
        self.assertEqual(token_days_left("2027-01-01T13:00:00Z", now), 0)
        self.assertEqual(token_days_left("2027-01-01T11:00:00Z", now), -1)
        self.assertIsNone(token_days_left(None, now))


class TestQueryType(CliTestCase):
    def test_query_type_changes_only_type(self):
        db = self.db()
        db.add_account("U1", "One", "tok1")
        db.conn.execute(
            "INSERT INTO queries (id, name, added_on, min_interval, type, account_id)"
            " VALUES ('127178', 'Trades', '2025-01-01 00:00:00', NULL, 'activity', 'U1')"
        )
        db.conn.commit()
        db.add_request("R1", "127178")
        db.update_request_status("R1", "completed", "/x.xml")
        before = db.conn.execute("SELECT id, name, added_on, min_interval, account_id FROM queries").fetchall()

        shown = self.invoke("query", "type", "127178")
        self.assertEqual(shown.exit_code, 0)
        self.assertIn("Query 127178 type: activity", shown.output)

        result = self.invoke("query", "type", "127178", "trade-confirmation")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("effective interval 1h, type default", result.output)

        db = self.db()
        self.assertEqual(db.conn.execute("SELECT id, name, added_on, min_interval, account_id FROM queries").fetchall(), before)
        self.assertEqual(db.get_query_info("127178")["type"], "trade-confirmation")
        self.assertEqual(db.get_latest_request("127178")["request_id"], "R1")
        listed = json.loads(self.invoke("query", "list", "--json").output)
        self.assertEqual(listed[0]["effective_interval"], 1)

        self.assertEqual(self.invoke("query", "type", "nope", "activity").exit_code, 1)
        self.assertEqual(self.invoke("query", "type", "127178", "bogus").exit_code, 2)


class TestMigrationV6toV7(unittest.TestCase):
    def setUp(self):
        self.temp_db_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_db_dir, True)

    def _make_v6_db(self):
        conn = sqlite3.connect(os.path.join(self.temp_db_dir, "status.db"))
        c = conn.cursor()
        c.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute(
            "CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, token TEXT NOT NULL, added_on DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        c.execute(
            "CREATE TABLE queries (id TEXT PRIMARY KEY, name TEXT, added_on DATETIME DEFAULT CURRENT_TIMESTAMP,"
            " min_interval INTEGER, type TEXT DEFAULT 'activity', account_id TEXT NOT NULL REFERENCES accounts(id))"
        )
        c.execute(
            "CREATE TABLE requests (request_id TEXT PRIMARY KEY, query_id TEXT, status TEXT, requested_at DATETIME,"
            " completed_at DATETIME, last_updated DATETIME, output_path TEXT, FOREIGN KEY (query_id) REFERENCES queries(id))"
        )
        c.execute("INSERT INTO config VALUES ('db_version', '6')")
        c.execute("INSERT INTO config VALUES ('default_poll_interval', '45')")
        c.execute("INSERT INTO accounts VALUES ('U1', 'Main', 'tok_v6', '2026-01-02 03:04:05')")
        c.execute("INSERT INTO queries VALUES ('Q1', 'Activity', '2026-01-02 03:04:06', 12, 'trade-confirmation', 'U1')")
        c.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("R1", "Q1", "completed", "2026-01-03T00:00:00", "2026-01-03T00:01:00", "2026-01-03T00:01:00", "/a.xml"),
        )
        conn.commit()
        conn.close()

    def _open(self) -> FlexDatabase:
        db = FlexDatabase(self.temp_db_dir)
        self.addCleanup(db.close)
        return db

    def test_v6_to_v7_keeps_data_and_adds_schema(self):
        self._make_v6_db()
        db = self._open()
        c = db.conn.cursor()
        self.assertEqual(c.execute("SELECT value FROM config WHERE key='db_version'").fetchone()[0], "7")
        self.assertEqual(db.get_config("default_poll_interval"), "45")
        acct = db.get_account("U1")
        self.assertEqual(
            (acct["name"], acct["token"], acct["added_on"], acct["token_expires_at"]), ("Main", "tok_v6", "2026-01-02 03:04:05", None)
        )
        self.assertEqual(
            c.execute("SELECT * FROM queries").fetchall(), [("Q1", "Activity", "2026-01-02 03:04:06", 12, "trade-confirmation", "U1")]
        )
        self.assertEqual(db.get_request_info("R1")["output_path"], "/a.xml")
        cols = [(r[1], r[2], r[3]) for r in c.execute("PRAGMA table_info(request_errors)")]
        self.assertEqual(
            cols,
            [
                ("id", "INTEGER", 0),
                ("query_id", "TEXT", 1),
                ("account_id", "TEXT", 0),
                ("occurred_at", "TEXT", 1),
                ("stage", "TEXT", 1),
                ("error_code", "TEXT", 0),
                ("error_message", "TEXT", 0),
                ("kind", "TEXT", 1),
            ],
        )
        index_cols = [r[2] for r in c.execute("PRAGMA index_info(idx_request_errors_query_time)")]
        self.assertEqual(index_cols, ["query_id", "occurred_at"])
        self.assertTrue(os.path.exists(os.path.join(self.temp_db_dir, "status.db.v6.bak")))

    def test_migration_is_idempotent(self):
        self._make_v6_db()
        FlexDatabase(self.temp_db_dir).close()
        # Force the v7 step to run again on an already-migrated DB.
        conn = sqlite3.connect(os.path.join(self.temp_db_dir, "status.db"))
        conn.execute("UPDATE config SET value = '6' WHERE key = 'db_version'")
        conn.commit()
        conn.close()
        db = self._open()
        self.assertEqual(db.get_config("db_version"), "7")
        self.assertEqual(db.get_account("U1")["token"], "tok_v6")

    def test_fresh_db_has_v7_schema(self):
        db = self._open()
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(accounts)")]
        self.assertEqual(cols, ["id", "name", "token", "added_on", "token_expires_at"])
        self.assertTrue(db.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'request_errors'").fetchone())

    def test_request_errors_pruned_after_90_days_per_query(self):
        db = self._open()
        db.add_account("U1", None, "t")
        old = (datetime.now(UTC) - timedelta(days=91)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = (datetime.now(UTC) - timedelta(days=89)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for qid, ts in (("Q1", old), ("Q1", recent), ("Q2", old)):
            db.conn.execute(
                "INSERT INTO request_errors (query_id, account_id, occurred_at, stage, kind) VALUES (?, 'U1', ?, 'send', 'other')",
                (qid, ts),
            )
        db.conn.commit()
        db.add_request_error("Q1", "U1", "send", None, "Network error: x", "other")
        self.assertEqual([e["occurred_at"] for e in db.list_request_errors("Q1")][0], recent)
        self.assertEqual(len(db.list_request_errors("Q1")), 2)
        self.assertEqual(len(db.list_request_errors("Q2")), 1)  # other queries untouched
        with self.assertRaises(ValueError):
            db.add_request_error("Q1", "U1", "bogus", None, None, "other")
        with self.assertRaises(ValueError):
            db.add_request_error("Q1", "U1", "send", None, None, "bogus")


V6_SCHEMA = """
CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE accounts (id TEXT PRIMARY KEY, name TEXT, token TEXT NOT NULL, added_on DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE queries (id TEXT PRIMARY KEY, name TEXT, added_on DATETIME DEFAULT CURRENT_TIMESTAMP, min_interval INTEGER,
    type TEXT DEFAULT 'activity', account_id TEXT NOT NULL REFERENCES accounts(id));
CREATE TABLE requests (request_id TEXT PRIMARY KEY, query_id TEXT, status TEXT, requested_at DATETIME, completed_at DATETIME,
    last_updated DATETIME, output_path TEXT, FOREIGN KEY (query_id) REFERENCES queries(id));
INSERT INTO config VALUES ('db_version', '6');
INSERT INTO accounts (id, name, token) VALUES ('U1', 'One', 'tok1');
INSERT INTO queries (id, name, account_id) VALUES ('A1', 'Activity 1', 'U1');
"""


def make_v6_db(data_dir: str, wal: bool = False) -> sqlite3.Connection:
    """Create a v6 status.db; return its (open) connection."""
    conn = sqlite3.connect(os.path.join(data_dir, "status.db"))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript(V6_SCHEMA)
    conn.commit()
    return conn


def db_version(data_dir: str) -> str:
    conn = sqlite3.connect(os.path.join(data_dir, "status.db"))
    try:
        return conn.execute("SELECT value FROM config WHERE key = 'db_version'").fetchone()[0]
    finally:
        conn.close()


class TestMigrationBackup(unittest.TestCase):
    """Finding A: WAL-complete backup, never overwritten, failure aborts before any schema change."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _open(self) -> FlexDatabase:
        db = FlexDatabase(self.dir)
        self.addCleanup(db.close)
        return db

    def test_backup_includes_uncheckpointed_wal_rows(self):
        writer = make_v6_db(self.dir, wal=True)
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO accounts (id, name, token) VALUES ('U2', 'In WAL only', 'tok2')")
        writer.commit()
        self.assertGreater(os.path.getsize(os.path.join(self.dir, "status.db-wal")), 0)

        self._open()
        backup = sqlite3.connect(os.path.join(self.dir, "status.db.v6.bak"))
        self.addCleanup(backup.close)
        self.assertEqual(backup.execute("SELECT id FROM accounts ORDER BY id").fetchall(), [("U1",), ("U2",)])
        self.assertEqual(backup.execute("SELECT value FROM config WHERE key='db_version'").fetchone()[0], "6")

    def test_existing_read_only_backup_is_kept_and_migration_succeeds(self):
        make_v6_db(self.dir).close()
        old = os.path.join(self.dir, "status.db.v6.bak")
        with open(old, "w") as f:
            f.write("older backup")
        os.chmod(old, 0o444)
        self.addCleanup(os.chmod, old, 0o644)

        db = self._open()
        self.assertEqual(db.get_config("db_version"), "7")
        with open(old) as f:
            self.assertEqual(f.read(), "older backup")
        [stamped] = glob.glob(os.path.join(self.dir, "status.db.v6.*.bak"))
        self.assertRegex(os.path.basename(stamped), r"^status\.db\.v6\.\d{8}T\d{6}Z\.bak$")
        conn = sqlite3.connect(stamped)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT value FROM config WHERE key='db_version'").fetchone()[0], "6")

    def test_backup_failure_aborts_before_schema_change(self):
        make_v6_db(self.dir).close()
        unwritable = os.path.join(self.dir, "no-such-dir", "status.db.v6.bak")
        with patch.object(FlexDatabase, "_backup_path", return_value=unwritable):
            with self.assertRaises(MigrationError) as cm:
                FlexDatabase(self.dir)
        self.assertIn("status.db was not changed (still schema v6)", str(cm.exception))
        self.assertEqual(db_version(self.dir), "6")
        conn = sqlite3.connect(os.path.join(self.dir, "status.db"))
        self.addCleanup(conn.close)
        self.assertNotIn("token_expires_at", [r[1] for r in conn.execute("PRAGMA table_info(accounts)")])

    def test_fresh_db_writes_no_backup(self):
        self._open()
        self.assertEqual(glob.glob(os.path.join(self.dir, "*.bak")), [])


class TestLazyOpenAndMigrationLock(unittest.TestCase):
    """Finding B: --help never opens the registry; migration is serialised across processes."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.runner = _runner()

    def invoke(self, *argv):
        return self.runner.invoke(cli, list(argv), env={"PYFLEXWEB_DATA_DIR": self.dir})

    HELP_AND_USAGE = (
        (["--help"], 0),
        (["--version"], 0),
        (["download", "--help"], 0),
        (["account", "expiry", "--help"], 0),
        (["query", "type", "--help"], 0),
        (["download", "--bogus"], 2),
        (["download", "--type", "activity", "--query", "A1"], 2),
        (["account", "add", "U1"], 2),
    )

    def test_help_and_usage_errors_leave_v6_db_untouched(self):
        make_v6_db(self.dir).close()
        before = sorted(os.listdir(self.dir))
        for argv, code in self.HELP_AND_USAGE:
            with self.subTest(argv=argv):
                result = self.invoke(*argv)
                self.assertEqual(result.exit_code, code, result.output)
        self.assertEqual(db_version(self.dir), "6")
        self.assertEqual(sorted(os.listdir(self.dir)), before)

    def test_help_creates_nothing_in_empty_dir(self):
        data_dir = os.path.join(self.dir, "data")
        os.mkdir(data_dir)
        for argv, _code in self.HELP_AND_USAGE:
            self.runner.invoke(cli, argv, env={"PYFLEXWEB_DATA_DIR": data_dir})
        self.runner.invoke(cli, [], env={"PYFLEXWEB_DATA_DIR": data_dir})  # bare `pyflexweb` prints help too
        self.assertEqual(os.listdir(data_dir), [])

    def test_download_help_lists_type_and_wait_lock(self):
        result = self.invoke("download", "--help")
        self.assertIn("--type [activity|trade-confirmation]", result.output)
        self.assertIn("--wait-lock", result.output)

    def test_concurrent_first_opens_migrate_once(self):
        make_v6_db(self.dir).close()
        original = FlexDatabase._migrate
        migrations: list[int] = []

        def slow_migrate(db_self, conn, version):
            migrations.append(version)
            time.sleep(0.3)  # widen the race window
            original(db_self, conn, version)

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def open_db():
            try:
                barrier.wait()
                FlexDatabase(self.dir).close()
            except BaseException as e:  # noqa: BLE001 - surfaced below
                errors.append(e)

        with patch.object(FlexDatabase, "_migrate", slow_migrate):
            threads = [threading.Thread(target=open_db) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(migrations, [6])  # the second opener re-read the version under the lock and skipped
        self.assertEqual(db_version(self.dir), "7")
        self.assertEqual(len(glob.glob(os.path.join(self.dir, "status.db.v6*.bak"))), 1)

    def test_migration_lock_wait_is_bounded(self):
        make_v6_db(self.dir).close()
        fd = os.open(os.path.join(self.dir, "migrate.lock"), os.O_RDONLY | os.O_CREAT, 0o664)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        with patch.object(database_module, "MIGRATE_LOCK_WAIT_SECONDS", 0.2):
            with self.assertRaises(MigrationError) as cm:
                FlexDatabase(self.dir)
        self.assertIn("another pyflexweb process is migrating", str(cm.exception))
        self.assertEqual(db_version(self.dir), "6")

    def test_download_that_must_migrate_does_not_deadlock(self):
        make_v6_db(self.dir).close()
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        with patch("pyflexweb.client.requests.get", side_effect=fake), patch("time.sleep"):
            result = self.invoke("download", "--output-dir", out, "--max-attempts", "1")
        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        self.assertEqual(db_version(self.dir), "7")


class TestReadOnlyLockFile(CliTestCase):
    """Finding C: an existing lock file without write permission still locks."""

    def test_read_only_lock_file_still_locks(self):
        db = self.db()
        db.add_account("U1", "One", "tok1")
        db.add_query("A1", "Activity 1", account_id="U1")
        lock_path = os.path.join(self.data_dir, "download.lock")
        with open(lock_path, "w"):
            pass
        os.chmod(lock_path, 0o444)
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})
        result = self.download(fake)
        self.assertEqual(result.exit_code, 0, result.output + result.stderr)
        self.assertEqual([c[0] for c in fake.calls], ["SendRequest", "GetStatement"])
        self.assertEqual(os.stat(lock_path).st_mode & 0o777, 0o444)


class TestTokenRejectedWhilePolling(CliTestCase):
    """Finding D: a token-class GetStatement answer stops polling at once."""

    def test_getstatement_token_error_stops_polling_and_skips_account(self):
        db = self.db()
        db.add_account("U1", "One", "tok1")
        db.add_query("A1", "Activity 1", account_id="U1")
        db.add_query("A2", "Activity 2", account_id="U1")
        fake = FakeIBKR({"tok1": _success_body("REF-{q}")})

        def route(url, timeout=None):
            if "GetStatement" in url:
                fake.calls.append(("GetStatement", "tok1", "REF"))
                return _response(TOKEN_EXPIRED_BODY)
            return fake(url, timeout)

        with patch("pyflexweb.client.requests.get", side_effect=route):
            result = self.invoke("download", "--output-dir", self.out_dir, "--poll-interval", "1", "--max-attempts", "5")

        self.assertEqual(result.exit_code, 3, result.output + result.stderr)
        self.assertEqual([c[0] for c in fake.calls], ["SendRequest", "GetStatement"])  # one poll, A2 never sent
        self.assertIn("Error retrieving report: Token has expired.\n", result.stderr)
        self.assertIn("  Attempt 1/5... token rejected\n", result.output)
        self.assertNotIn("waiting...", result.output)
        self.assertIn("  Report not retrieved: IBKR rejected the token.\n", result.output)
        self.assertIn("  Skipped: token of account U1 was rejected earlier in this run\n", result.output)
        self.assertEqual(
            [line for line in result.stderr.splitlines() if line.startswith("TOKEN REJECTED:")],
            [
                "TOKEN REJECTED: IBKR refused the Flex token of account U1 (One): 1012 Token has expired. Create a new token in "
                "Client Portal (Performance & Reports > Flex Queries > Flex Web Service) and run: "
                'pyflexweb account add U1 --name "One" --token <new token> --expires "<expiry shown by IBKR>"'
            ],
        )
        db = self.db()
        self.assertEqual(db.get_latest_request("A1")["status"], "failed")
        rows = [(e["query_id"], e["stage"], e["error_code"], e["kind"]) for e in db.list_request_errors()]
        self.assertEqual(rows, [("A1", "get", "1012", "token"), ("A2", "skipped", "1012", "token")])


class TestTokenRejectedRemedies(unittest.TestCase):
    """Finding E: the remedy depends on the code; kind stays 'token'."""

    PREFIX = "TOKEN REJECTED: IBKR refused the Flex token of account U1 (Main): "
    STORE = 'pyflexweb account add U1 --name "Main" --token <new token> --expires "<expiry shown by IBKR>"'
    PAGE = "Client Portal (Performance & Reports > Flex Queries > Flex Web Service)"

    def line(self, code, message):
        return _token_rejected_line("U1", "Main", FlexError(code=code, message=message, kind="token"))

    def test_1012_and_1015_create_new_token(self):
        for code, message in (("1012", "Token has expired."), ("1015", "Token is invalid.")):
            with self.subTest(code=code):
                self.assertEqual(
                    self.line(code, message),
                    f"{self.PREFIX}{code} {message} Create a new token in {self.PAGE} and run: {self.STORE}",
                )

    def test_1013_ip_restriction(self):
        self.assertEqual(
            self.line("1013", "IP restriction."),
            f"{self.PREFIX}1013 IP restriction. The request came from an IP address the token does not allow: "
            f"add this host's public IP to the token's allowed list in {self.PAGE}, "
            f"or create a token without the restriction and run: {self.STORE}",
        )

    def test_1011_service_inactive(self):
        self.assertEqual(
            self.line("1011", "Service account is inactive."),
            f"{self.PREFIX}1011 Service account is inactive. Flex Web Service is inactive for this login: "
            f"re-activate it in {self.PAGE}, then, if the old token no longer works, create a new token and run: {self.STORE}",
        )

    def test_message_only_token_error(self):
        self.assertEqual(
            self.line(None, "Token has expired."),
            f"{self.PREFIX}Token has expired. Create a new token in {self.PAGE} and run: {self.STORE}",
        )


class TestExpiryWording(unittest.TestCase):
    """Finding F: human text truncates toward zero; JSON days_left stays floored."""

    NOW = datetime(2027, 1, 10, 12, 0, tzinfo=UTC)

    def at(self, delta: timedelta) -> str:
        return (self.NOW + delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_wording(self):
        cases = (
            (timedelta(hours=-26), "EXPIRED 1 day ago", -2),
            (timedelta(hours=-5), "EXPIRED 5 hours ago", -1),
            (timedelta(minutes=-10), "EXPIRED less than an hour ago", -1),
            (timedelta(minutes=10), "in less than an hour", 0),
            (timedelta(hours=1), "in 1 hour", 0),
            (timedelta(hours=5), "in 5 hours", 0),
            (timedelta(hours=47), "in 1 day", 1),
            (timedelta(days=336, hours=3), "in 336 days", 336),
            (timedelta(days=-3, hours=-1), "EXPIRED 3 days ago", -4),
        )
        for delta, text, days_left in cases:
            with self.subTest(delta=delta):
                stamp = self.at(delta)
                self.assertTrue(describe_token_expiry(stamp, self.NOW).endswith(f"({text})"))
                self.assertEqual(token_days_left(stamp, self.NOW), days_left)
        self.assertEqual(describe_token_expiry(None, self.NOW), "unknown")


if __name__ == "__main__":
    unittest.main()
