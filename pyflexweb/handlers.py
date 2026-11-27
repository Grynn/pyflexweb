"""Command handlers for CLI commands."""

import errno
import fcntl
import json
import math
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .client import FlexError, IBKRFlexClient
from .database import UTC_TIMESTAMP_FORMAT, FlexDatabase

# Default minimum interval between downloads (hours) per query type
TYPE_INTERVAL_DEFAULTS = {
    "activity": 6,
    "trade-confirmation": 1,
}

# IBKR throttles bursts of Flex statement generation requests even when the
# individual queries satisfy their own minimum download intervals.
INTER_QUERY_DELAY_SECONDS = 2 * 60

VALID_QUERY_TYPES = list(TYPE_INTERVAL_DEFAULTS.keys())

# `download` exit codes (also documented in `download --help` and the README).
EXIT_OK = 0
EXIT_QUERY_FAILED = 1
EXIT_TOKEN_REJECTED = 3  # wins over EXIT_QUERY_FAILED
EXIT_LOCKED = 4  # another download holds the lock; nothing was requested

# Cross-process lock so overlapping `download` runs never send requests on the
# same token without the inter-request pacing. Lives next to status.db.
DOWNLOAD_LOCK_FILENAME = "download.lock"
LOCK_POLL_SECONDS = 1

# IBKR's portal shows token expiry in US Eastern time.
EASTERN = ZoneInfo("America/New_York")

_EXPIRY_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[ T](?P<h>\d{2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?"
    r"(?:\s*(?P<offset>Z|[+-]\d{2}:\d{2})|\s+(?P<zone>ET|EST|EDT)))?$",
    re.IGNORECASE,
)

EXPIRY_FORMS_HELP = """Accepted forms:
  YYYY-MM-DD                          taken as 00:00 UTC of that day
  YYYY-MM-DD HH:MM[:SS]Z              UTC
  YYYY-MM-DD HH:MM[:SS]+HH:MM         explicit UTC offset (e.g. +05:30, -04:00)
  YYYY-MM-DD HH:MM[:SS] ET|EST|EDT    US Eastern (America/New_York), as IBKR's portal shows it
A 'T' may replace the space between date and time. Example: 2027-10-29 11:30 EDT
IBKR's day-first display (DD/MM/YYYY HH:MM EDT) is not accepted because it is ambiguous;
rewrite it as YYYY-MM-DD."""


def parse_token_expiry(text: str) -> str:
    """Parse a token expiry into an ISO-8601 UTC string (YYYY-MM-DDTHH:MM:SSZ).

    ET/EST/EDT all mean the America/New_York zone; the offset is resolved from
    the zone and the date, never from the abbreviation. Raises ValueError with
    the accepted forms on anything else (including a naive date-time).
    """
    raw = (text or "").strip()
    match = _EXPIRY_RE.match(raw)
    if not match:
        raise ValueError(f'Unrecognised token expiry "{text}".\n{EXPIRY_FORMS_HELP}')
    try:
        year, month, day = (int(x) for x in match["date"].split("-"))
        if match["h"] is None:
            moment = datetime(year, month, day, tzinfo=UTC)
        else:
            naive = datetime(year, month, day, int(match["h"]), int(match["m"]), int(match["s"] or 0))
            if match["zone"]:
                moment = naive.replace(tzinfo=EASTERN)
            elif match["offset"].upper() == "Z":
                moment = naive.replace(tzinfo=UTC)
            else:
                sign = -1 if match["offset"][0] == "-" else 1
                hours, minutes = (int(x) for x in match["offset"][1:].split(":"))
                if hours > 23 or minutes > 59:
                    raise ValueError("offset out of range")
                moment = naive.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    except ValueError as e:
        raise ValueError(f'Invalid token expiry "{text}": {e}.\n{EXPIRY_FORMS_HELP}') from None
    return moment.astimezone(UTC).strftime(UTC_TIMESTAMP_FORMAT)


def token_days_left(token_expires_at: str | None, now: datetime | None = None) -> int | None:
    """Whole days until expiry, floored (negative once expired); None if unknown."""
    if not token_expires_at:
        return None
    expires = datetime.strptime(token_expires_at, UTC_TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return math.floor((expires - now).total_seconds() / 86400)


def describe_token_expiry(token_expires_at: str | None, now: datetime | None = None) -> str:
    """'2027-10-29 15:30Z (in 336 days)', '... (EXPIRED 3 days ago)' or 'unknown'."""
    days = token_days_left(token_expires_at, now)
    if days is None:
        return "unknown"
    stamp = f"{token_expires_at[:10]} {token_expires_at[11:16]}Z"
    if days >= 0:
        return f"{stamp} (in {days} day{'' if days == 1 else 's'})"
    ago = -days
    return f"{stamp} (EXPIRED {ago} day{'' if ago == 1 else 's'} ago)"


EXPIRY_NOT_RECORDED_NOTE = 'Token expiry not recorded. Record it with: pyflexweb account expiry {account_id} "<expiry shown by IBKR>"'


def _effective_interval(query_info: dict) -> int:
    """Return the effective min-interval hours for a query."""
    if query_info.get("min_interval") is not None:
        return query_info["min_interval"]
    return TYPE_INTERVAL_DEFAULTS.get(query_info.get("type", "activity"), 6)


def handle_token_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'token' command and its subcommands.

    NOTE: The global token is a legacy concept. IBKR tokens are account-specific.
    Use 'pyflexweb account add' to configure per-account tokens instead.
    """
    if args.subcommand == "set":
        print("Note: 'pyflexweb token set' is deprecated. Use 'pyflexweb account add <id> --token <token>' instead.")
        db.set_token(args.token)
        print("Legacy global token set. It will be used as a fallback only during migration.")
        return 0
    elif args.subcommand == "get":
        token = db.get_token()
        if token:
            print(f"Legacy global token: {token}")
            print("Note: use 'pyflexweb account list' to see per-account tokens.")
        else:
            print("No legacy global token found.")
            print("Use 'pyflexweb account list' to see configured accounts and tokens.")
        return 0
    elif args.subcommand == "unset":
        db.unset_token()
        print("Legacy global token removed.")
        return 0
    else:
        print("Missing subcommand. Use 'set', 'get', or 'unset'.")
        return 1


def handle_account_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'account' command and its subcommands."""
    if args.subcommand == "add":
        name = getattr(args, "name", None)
        expires_text = getattr(args, "expires", None)
        expires_at = None
        if expires_text is not None:
            try:
                expires_at = parse_token_expiry(expires_text)
            except ValueError as e:
                print(f"Error: {e}")
                return 1
        existed = db.add_account(args.account_id, name, args.token, token_expires_at=expires_at)
        display = f"{args.account_id}"
        if name:
            display += f" ({name})"
        print(f"Account {display} added.")  # unchanged pre-v7 line
        if existed:
            if name is None:
                account = db.get_account(args.account_id)
                kept = account.get("name") if isinstance(account, dict) else None
                print(f"  Existing account: token replaced, name kept ({kept or 'unnamed'}).")
            else:
                print("  Existing account: token replaced.")
        if expires_at:
            print(f"Token expires {describe_token_expiry(expires_at)}.")
        else:
            print(EXPIRY_NOT_RECORDED_NOTE.format(account_id=args.account_id))
        return 0

    elif args.subcommand == "expiry":
        account = db.get_account(args.account_id)
        if not account:
            print(f"Account '{args.account_id}' not found.")
            return 1
        when = getattr(args, "when", None)
        unset = getattr(args, "unset", False) is True
        if when is not None and unset:
            print("Error: give either an expiry or --unset, not both.")
            return 1
        if unset:
            db.set_token_expiry(args.account_id, None)
            print(f"Token expiry of account {args.account_id} cleared.")
            return 0
        if when is not None:
            try:
                expires_at = parse_token_expiry(when)
            except ValueError as e:
                print(f"Error: {e}")
                return 1
            db.set_token_expiry(args.account_id, expires_at)
            print(f"Token of account {args.account_id} expires {expires_at} ({describe_token_expiry(expires_at).split(' (', 1)[1]}.")
            return 0
        expires_at = account.get("token_expires_at")
        if expires_at:
            print(f"Token of account {args.account_id} expires {expires_at} ({describe_token_expiry(expires_at).split(' (', 1)[1]}.")
        else:
            print(EXPIRY_NOT_RECORDED_NOTE.format(account_id=args.account_id))
        return 0

    elif args.subcommand == "list":
        accounts = db.list_accounts()
        if getattr(args, "json_output", False) is True:
            now = datetime.now(UTC)
            output = [
                {
                    "id": acct["id"],
                    "name": acct["name"],
                    "added_on": acct["added_on"],
                    "token_expires_at": acct.get("token_expires_at"),
                    "days_left": token_days_left(acct.get("token_expires_at"), now),
                }
                for acct in accounts
            ]
            print(json.dumps(output, indent=2))
            return 0

        if not accounts:
            print("No accounts configured. Add one with 'pyflexweb account add <id> --token <token>'")
            return 0

        now = datetime.now(UTC)
        # Pre-v7 columns first, unchanged; the expiry column is appended.
        print(f"{'ID':<20} {'Name':<25} {'Token':<20} {'Added':<20} {'Token expires (UTC)'}")
        print(f"{'-' * 20} {'-' * 25} {'-' * 20} {'-' * 20} {'-' * 38}")
        for acct in accounts:
            acct_id = acct["id"]
            name = acct["name"] or "(unnamed)"
            token_display = acct["token"][:8] + "..." if len(acct["token"]) > 8 else acct["token"]
            expiry = describe_token_expiry(acct.get("token_expires_at"), now)
            added = acct["added_on"][:19] if acct["added_on"] else "-"
            print(f"{acct_id:<20} {name:<25} {token_display:<20} {added:<20} {expiry}")
        return 0

    elif args.subcommand == "remove":
        result = db.remove_account(args.account_id)
        if result is None:
            print(f"Account '{args.account_id}' not found.")
            return 1
        elif result is False:
            print(f"Cannot remove account '{args.account_id}': queries are still associated with it.")
            print("Reassign or remove those queries first (pyflexweb query list).")
            return 1
        else:
            print(f"Account '{args.account_id}' removed.")
        return 0

    elif args.subcommand == "edit":
        new_id = getattr(args, "new_id", None)
        new_name = getattr(args, "name", None)
        if not new_id and new_name is None:
            print("Nothing to update. Use --new-id and/or --name.")
            return 1
        if db.update_account(args.account_id, new_id=new_id, new_name=new_name):
            parts = [f"Account '{args.account_id}' updated."]
            if new_id:
                parts.append(f"ID changed to '{new_id}'.")
            if new_name is not None:
                parts.append(f"Name set to '{new_name}'.")
            print(" ".join(parts))
        else:
            print(f"Account '{args.account_id}' not found.")
            return 1
        return 0

    else:
        print("Missing subcommand. Use 'add', 'list', 'rm', or 'edit'.")
        return 1


def handle_query_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'query' command and its subcommands."""
    if args.subcommand == "add":
        query_type = getattr(args, "query_type", "activity") or "activity"
        min_interval = getattr(args, "min_interval", None)
        account_id = getattr(args, "account", None)

        # account_id is required — every query must belong to an account
        if not account_id:
            print("Error: --account <account_id> is required.")
            print("Add an account first: pyflexweb account add <id> --token <token>")
            print("Then: pyflexweb query add <query_id> --name <name> --account <id>")
            accounts = db.list_accounts()
            if accounts:
                print(f"\nAvailable accounts: {', '.join(a['id'] for a in accounts)}")
            return 1

        account = db.get_account(account_id)
        if not account:
            print(f"Account '{account_id}' not found. Add it first with:")
            print(f"  pyflexweb account add {account_id} --token <token>")
            return 1

        db.add_query(args.query_id, args.name, query_type=query_type, min_interval=min_interval, account_id=account_id)
        parts = [f"Query ID {args.query_id} added ({query_type}), account: {account_id}."]
        if min_interval is not None:
            parts.append(f"Min interval: {min_interval}h.")
        print(" ".join(parts))
        return 0

    elif args.subcommand == "remove":
        if db.remove_query(args.query_id):
            print(f"Query ID {args.query_id} removed.")
        else:
            print(f"Query ID {args.query_id} not found.")
            return 1
        return 0

    elif args.subcommand == "rename":
        if db.rename_query(args.query_id, args.name):
            print(f"Query ID {args.query_id} renamed to '{args.name}'.")
        else:
            print(f"Query ID {args.query_id} not found.")
            return 1
        return 0

    elif args.subcommand == "interval":
        query_info = db.get_query_info(args.query_id)
        if not query_info:
            print(f"Query ID {args.query_id} not found.")
            return 1
        if hasattr(args, "unset") and args.unset:
            db.set_query_interval(args.query_id, None)
            default = TYPE_INTERVAL_DEFAULTS.get(query_info["type"], 6)
            print(f"Query {args.query_id} will use the type default ({default}h).")
        else:
            db.set_query_interval(args.query_id, args.hours)
            print(f"Query {args.query_id} min interval set to {args.hours}h.")
        return 0

    elif args.subcommand == "type":
        query_info = db.get_query_info(args.query_id)
        if not query_info:
            print(f"Query ID {args.query_id} not found.")
            return 1
        new_type = getattr(args, "query_type", None)
        if new_type is None:
            print(f"Query {args.query_id} type: {query_info['type']}")
            return 0
        if new_type not in VALID_QUERY_TYPES:
            print(f"Error: type must be one of {', '.join(VALID_QUERY_TYPES)}.")
            return 1
        db.set_query_type(args.query_id, new_type)
        query_info["type"] = new_type
        interval = _effective_interval(query_info)
        source = "per-query override" if query_info.get("min_interval") is not None else "type default"
        print(f"Query {args.query_id} type set to {new_type} (effective interval {interval}h, {source}).")
        return 0

    elif args.subcommand == "list":
        queries = db.get_all_queries_with_status()
        json_output = getattr(args, "json_output", False)

        if not queries:
            if json_output:
                print("[]")
            else:
                print("No query IDs found. Add one with 'pyflexweb query add <query_id> --name \"Query name\" --account <account_id>'")
            return 0

        if json_output:
            output = []
            for query in queries:
                item = {
                    "id": query["id"],
                    "name": query["name"],
                    "type": query.get("type", "activity"),
                    "min_interval": query.get("min_interval"),
                    "effective_interval": _effective_interval(query),
                    "account_id": query.get("account_id"),
                    "last_download": None,
                    "status": None,
                }
                if query["latest_request"]:
                    req = query["latest_request"]
                    item["last_download"] = req["completed_at"] or req["requested_at"]
                    item["status"] = req["status"]
                    item["output_path"] = req.get("output_path")
                output.append(item)
            print(json.dumps(output, indent=2))
            return 0

        print(f"{'ID':<10} {'Name':<30} {'Type':<20} {'Account':<12} {'Interval':<10} {'Last Download':<20} {'Status':<10}")
        print(f"{'-' * 10} {'-' * 30} {'-' * 20} {'-' * 12} {'-' * 10} {'-' * 20} {'-' * 10}")

        for query in queries:
            query_id = query["id"]
            name_display = query["name"] if query["name"] else "unnamed"
            type_display = query.get("type", "activity")
            account_display = query.get("account_id") or "-"
            if query.get("min_interval") is not None:
                interval_display = f"{query['min_interval']}h"
            else:
                interval_display = f"{_effective_interval(query)}h"

            if query["latest_request"]:
                req = query["latest_request"]
                ts = req["completed_at"] or req["requested_at"]
                last_time = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
                status = req["status"]
            else:
                last_time = "Never"
                status = "-"

            print(
                f"{query_id:<10} {name_display[:30]:<30} {type_display:<20}"
                f" {account_display:<12} {interval_display:<10} {last_time:<20} {status:<10}"
            )

        return 0

    else:
        print("Missing subcommand. Use 'add', 'remove', 'rename', 'interval', or 'list'.")
        return 1


def _acquire_download_lock(lock_path: str, wait_seconds: int) -> int | None:
    """Take an exclusive flock on lock_path; return the fd, or None if still held after wait_seconds.

    The file is created with mode 0664 if missing and never deleted (deleting a
    lock file lets two processes lock different inodes).
    """
    created = not os.path.exists(lock_path)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o664)
    if created:
        try:
            os.fchmod(fd, 0o664)  # not narrowed by the umask
        except OSError:
            pass
    attempts = max(0, math.ceil(wait_seconds / LOCK_POLL_SECONDS)) if wait_seconds else 0
    for attempt in range(attempts + 1):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                os.close(fd)
                raise
        if attempt < attempts:
            time.sleep(LOCK_POLL_SECONDS)
    os.close(fd)
    return None


def _release_download_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _as_flex_error(error: object, default_kind: str = "other") -> FlexError:
    """Normalise client.last_error (may be missing on a stub client) into a FlexError."""
    if isinstance(error, FlexError):
        return error
    return FlexError(code=None, message=None, kind=default_kind)


def _token_rejected_line(account_id: str, account_name: str | None, error: FlexError) -> str:
    """The one-line TOKEN REJECTED alert. Never includes the token."""
    who = f"{account_id} ({account_name})" if account_name else account_id
    reason = " ".join(part for part in (error.code, error.message or "Unknown Flex error") if part)
    if not reason.endswith("."):
        reason += "."
    name_opt = f' --name "{account_name}"' if account_name else ""
    return (
        f"TOKEN REJECTED: IBKR refused the Flex token of account {who}: {reason} "
        "Create a new token in Client Portal (Performance & Reports > Flex Queries > Flex Web Service) "
        f'and run: pyflexweb account add {account_id}{name_opt} --token <new token> --expires "<expiry shown by IBKR>"'
    )


def handle_download_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'download' command.

    Exit codes: 0 ok (incl. nothing due), 1 a query failed, 3 a token was
    rejected (wins over 1), 4 another download holds the lock.
    """
    query_type = getattr(args, "query_type", None)
    if not isinstance(query_type, str):
        query_type = None

    # --- Validate options (no DB access, no HTTP) ---
    if query_type is not None and args.query != "all":
        print("Error: --type cannot be combined with --query <ID>.")
        return 1

    # --- Cross-process lock: held until this command returns ---
    wait_lock = getattr(args, "wait_lock", 0)
    wait_lock = wait_lock if isinstance(wait_lock, int) else 0
    lock_path = os.path.join(db.db_dir, DOWNLOAD_LOCK_FILENAME)
    lock_fd = _acquire_download_lock(lock_path, wait_lock)
    if lock_fd is None:
        print(f"Another pyflexweb download is running (lock: {lock_path}); nothing was requested.", file=sys.stderr, flush=True)
        return EXIT_LOCKED
    try:
        return _run_download(args, db, query_type)
    finally:
        _release_download_lock(lock_fd)


def _run_download(args: dict[str, Any], db: FlexDatabase, query_type: str | None) -> int:
    # Determine which queries to download
    if args.query == "all":
        if query_type is not None:
            registered = [q for q in db.get_all_queries_with_status() if q.get("type", "activity") == query_type]
            if not registered:
                print(f"No {query_type} queries registered. Nothing to download.")
                return EXIT_OK
        if args.force:
            queries_to_download = db.get_all_queries_with_status()
            if query_type is not None:
                queries_to_download = [q for q in queries_to_download if q.get("type", "activity") == query_type]
            if not queries_to_download:
                print("No queries found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")
                return EXIT_OK
            print(f"Force downloading all {len(queries_to_download)} {query_type + ' ' if query_type else ''}queries")
        else:
            queries_to_download = db.get_queries_needing_download(TYPE_INTERVAL_DEFAULTS)
            if query_type is not None:
                queries_to_download = [q for q in queries_to_download if q.get("type", "activity") == query_type]
            if not queries_to_download:
                label = f"{query_type} " if query_type else ""
                print(f"All {label}queries are up to date. Use --force to download anyway.")
                return EXIT_OK
            print(f"Found {len(queries_to_download)} {query_type + ' ' if query_type else ''}queries that need updating")
    else:
        query_info = db.get_query_info(args.query)
        if not query_info:
            print(f"Query ID {args.query} not found. Add it with 'pyflexweb query add {args.query}'")
            return 1
        queries_to_download = [query_info]

    # Validate options (kept after query selection, as before v7, so existing
    # output is unchanged)
    if args.query == "all" and args.output:
        print("Error: --output cannot be used with multiple queries/all mode.")
        print("Use --output-dir to specify a directory for all reports.")
        return 1

    # Create output directory if needed
    output_dir = args.output_dir if hasattr(args, "output_dir") and args.output_dir else "."
    if output_dir != "." and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")
        except OSError as e:
            print(f"Error creating output directory: {e}")
            return 1

    overall_success = True
    token_rejected = False
    # account_id -> the error that rejected its token earlier in this run
    rejected_accounts: dict[str, FlexError] = {}
    requests_issued = 0

    def reject_token(account_id: str, error: FlexError) -> None:
        nonlocal token_rejected
        token_rejected = True
        if account_id in rejected_accounts:
            return
        rejected_accounts[account_id] = error
        account = db.get_account(account_id)
        name = account.get("name") if isinstance(account, dict) else None
        print(_token_rejected_line(account_id, name, error), file=sys.stderr, flush=True)

    for query_info in queries_to_download:
        query_id = query_info["id"]
        query_name = query_info["name"] or query_id
        account_id = query_info.get("account_id")

        # Resolve token for this query via its account
        token = db.resolve_token(query_id)
        if not token:
            print(f"\nSkipping: {query_name} (ID: {query_id}) — token not found.")
            if account_id:
                print(f"  Account '{account_id}' has no token configured.")
                print(f"  Run: pyflexweb account add {account_id} --token <token>")
            else:
                print("  No account is associated with this query.")
                print("  Use 'pyflexweb account list' and re-associate via 'pyflexweb query add ... --account <id>'")
            overall_success = False
            continue

        print(f"\nDownloading: {query_name} (ID: {query_id})")

        # Check interval (skip if recently downloaded)
        if not args.force:
            latest = db.get_latest_request(query_id)
            if latest and latest["status"] == "completed":
                completed_at = datetime.fromisoformat(latest["completed_at"])
                interval_hours = _effective_interval(query_info)
                cutoff = datetime.now() - timedelta(hours=interval_hours)

                if completed_at > cutoff:
                    print(f"  Skipped: downloaded within the last {interval_hours}h.")
                    print(f"  Output file: {latest['output_path']}")
                    print("  Use --force to download again.")
                    continue

        # Never send another request with a token IBKR refused earlier in this run.
        if account_id in rejected_accounts:
            error = rejected_accounts[account_id]
            print(f"  Skipped: token of account {account_id} was rejected earlier in this run")
            db.add_request_error(query_id, account_id, "skipped", error.code, error.message, error.kind)
            overall_success = False
            token_rejected = True
            continue

        # Request report from IBKR. Space actual network requests—not skipped
        # queries—so multi-query runs do not trip the token's burst throttle.
        # Waiting before each request after the first avoids both an initial
        # delay and an unnecessary trailing delay.
        if requests_issued:
            print(f"  Waiting {INTER_QUERY_DELAY_SECONDS}s before the next Flex request...")
            time.sleep(INTER_QUERY_DELAY_SECONDS)

        client = IBKRFlexClient(token)
        requests_issued += 1
        request_id = client.request_report(query_id)
        if not request_id:
            print("  Failed to request report.")
            error = _as_flex_error(getattr(client, "last_error", None))
            db.add_request_error(query_id, account_id, "send", error.code, error.message, error.kind)
            if error.kind == "token" and account_id:
                reject_token(account_id, error)
            overall_success = False
            continue

        db.add_request(request_id, query_id)

        # Determine output filename
        if len(queries_to_download) == 1 and args.output:
            output_file = os.path.join(output_dir, args.output)
        else:
            today = datetime.now().strftime("%Y%m%d")
            safe_name = "".join(c if c.isalnum() else "_" for c in (query_info["name"] or query_id))
            output_file = os.path.join(output_dir, f"{account_id or 'unknown'}_{query_id}_{safe_name}_{today}.xml")

        # Poll for the report
        print(f"  Polling (max {args.max_attempts} attempts, {args.poll_interval}s interval)...")
        report_xml = None
        last_get_error: FlexError | None = None

        for attempt in range(1, args.max_attempts + 1):
            print(f"  Attempt {attempt}/{args.max_attempts}...", end="", flush=True)
            if attempt == 1:
                time.sleep(args.poll_interval / 2)
            report_xml = client.get_report(request_id)

            if report_xml:
                print(" OK")
                break

            error = getattr(client, "last_error", None)
            if isinstance(error, FlexError):
                last_get_error = error

            print(" waiting...")
            if attempt < args.max_attempts:
                time.sleep(args.poll_interval)

        if not report_xml:
            print(f"  Report not available after {args.max_attempts} attempts.")
            db.update_request_status(request_id, "failed")
            error = last_get_error or FlexError(code=None, message=None, kind="not_ready")
            db.add_request_error(query_id, account_id, "get", error.code, error.message, error.kind)
            if error.kind == "token" and account_id:
                reject_token(account_id, error)
            overall_success = False
            continue

        # Save the report
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report_xml)
            print(f"  Saved to {output_file}")
        except OSError as e:
            print(f"  Error saving report: {e}")
            db.update_request_status(request_id, "failed")
            overall_success = False
            continue

        db.update_request_status(request_id, "completed", output_file)

    if token_rejected:
        return EXIT_TOKEN_REJECTED
    return EXIT_OK if overall_success else EXIT_QUERY_FAILED


def handle_config_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'config' command and its subcommands."""
    if args.subcommand == "set":
        if args.key in ["default_poll_interval", "default_max_attempts"]:
            try:
                int(args.value)
            except ValueError:
                print(f"Error: {args.key} must be a number")
                return 1

        db.set_config(args.key, args.value)
        print(f"Set {args.key} = {args.value}")
        return 0
    elif args.subcommand == "get":
        if args.key:
            value = db.get_config(args.key)
            if value is not None:
                print(f"{args.key} = {value}")
            else:
                print(f"{args.key} is not set")
        else:
            config_dict = db.list_config()
            if config_dict:
                for k, v in config_dict.items():
                    print(f"{k} = {v}")
            else:
                print("No configuration values set")
        return 0
    elif args.subcommand == "unset":
        if db.unset_config(args.key):
            print(f"Unset {args.key}")
        else:
            print(f"{args.key} was not set")
        return 0
    elif args.subcommand == "list":
        from .database import resolve_data_dir

        config_defaults = {
            "default_output_dir": resolve_data_dir(),
            "default_poll_interval": "30",
            "default_max_attempts": "20",
        }

        current_config = db.list_config()

        print("Configuration settings:")
        print("(* indicates non-default value)\n")

        for key, default_value in sorted(config_defaults.items()):
            current_value = current_config.get(key)
            if current_value is not None and current_value != default_value:
                print(f"* {key} = {current_value}")
            elif current_value is not None:
                print(f"  {key} = {current_value}")
            else:
                print(f"  {key} = {default_value} (default)")

        print("\nQuery type interval defaults:")
        for qtype, hours in sorted(TYPE_INTERVAL_DEFAULTS.items()):
            print(f"  {qtype}: {hours}h")

        return 0
    else:
        print("Missing subcommand. Use 'set', 'get', 'unset', or 'list'.")
        return 1
