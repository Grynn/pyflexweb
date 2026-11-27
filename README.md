# PyFlexWeb

CLI for downloading IBKR Flex reports.

[![CI](https://github.com/grynn/pyflexweb/actions/workflows/ci.yml/badge.svg)](https://github.com/grynn/pyflexweb/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/pyflexweb.svg)](https://pypi.org/project/pyflexweb/)

## Install

```bash
uv tool install pyflexweb
```

## Setup

1. [Create a Flex Query and generate a token](https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm) in your IBKR Account Management portal.

2. Store your token and add queries:

```bash
pyflexweb token set YOUR_TOKEN

# Add an activity query (default type, 6h download interval)
pyflexweb query add 123456 --name "Daily activity"

# Add a trade confirmation query (1h download interval)
pyflexweb query add 789012 --name "Trade confirmations" --type trade-confirmation
```

## Multi-Account Support

If you have multiple IBKR accounts, each with its own Flex token, you can
configure per-account tokens and associate queries with specific accounts:

```bash
# Add accounts
pyflexweb account add U1317359 --name "Cerabella" --token YOUR_TOKEN_1
pyflexweb account add U11049821 --name "CCUK" --token YOUR_TOKEN_2

# List configured accounts
pyflexweb account list

# Add queries tied to specific accounts
pyflexweb query add 111111 --name "Cerabella Activity" --account U1317359
pyflexweb query add 222222 --name "CCUK Activity" --account U11049821

# Rename or remove accounts
pyflexweb account edit U1317359 --name "Main Account"
pyflexweb account rm U11049821
```

### Token expiry

IBKR Flex tokens expire. Record each token's expiry when you set it, so that
`account list` (and anything reading `status.db`) can warn before it lapses:

```bash
# When adding/replacing a token
pyflexweb account add U1317359 --name "Cerabella" --token NEW_TOKEN --expires "2027-10-29 11:30 EDT"

# Or afterwards: set, show, clear
pyflexweb account expiry U1317359 "2027-10-29 11:30 EDT"
pyflexweb account expiry U1317359
pyflexweb account expiry U1317359 --unset

# Table with an expiry column, or JSON (never contains the token)
pyflexweb account list
pyflexweb account list --json   # [{id, name, added_on, token_expires_at, days_left}]
```

**Take the expiry from what the IBKR portal shows, not from the option you picked.**
IBKR's "1 year" token option gives about 336 days, not 365.

Accepted expiry forms (stored as UTC, `YYYY-MM-DDTHH:MM:SSZ`):

| Form | Meaning |
|------|---------|
| `YYYY-MM-DD` | 00:00 UTC of that day (the earliest reading) |
| `YYYY-MM-DD HH:MM[:SS]Z` | UTC |
| `YYYY-MM-DD HH:MM[:SS]+05:30` / `-04:00` | explicit UTC offset |
| `YYYY-MM-DD HH:MM[:SS] ET` / ` EST` / ` EDT` | US Eastern (`America/New_York`), as the portal shows it. The offset comes from the zone and the date, not from the abbreviation. |

A `T` may replace the space between date and time. Anything else is rejected,
including a date-time without a zone and IBKR's own day-first display
(`DD/MM/YYYY HH:MM EDT`, ambiguous): rewrite it as `YYYY-MM-DD`.

`days_left` (JSON) is the whole number of days left, rounded down: it is
negative exactly when the token has expired, and `null` when no expiry is
recorded.

Re-adding an existing account (`account add` with the same ID) replaces the
token, keeps the existing name unless `--name` is given, resets `added_on` to
now (it means "token last set"), and replaces the stored expiry. Without
`--expires` the expiry is cleared, because a new token's expiry is unknown
until you state it, and a reminder to run `account expiry` is printed.

### Token Resolution

When downloading, pyflexweb resolves the token for each query:

1. Look up the account associated with the query
2. Use that account's token
3. If the account has no token configured, the query is skipped with a clear error

Every query must be associated with an account (`--account` is required when adding queries).
Legacy global tokens are automatically migrated to a placeholder account on first run.

## Usage

```bash
# Download all queries that are due
pyflexweb download

# Download a specific query
pyflexweb download --query 123456

# Force download regardless of interval
pyflexweb download --force

# Only one query type (only with --query all, the default)
pyflexweb download --type trade-confirmation

# Check status of all queries
pyflexweb status
```

When more than one query is due, `download` waits two minutes between actual
Flex statement-generation requests to avoid IBKR's token-level burst throttle.
There is no initial or trailing delay, and skipped/up-to-date queries do not
add a wait.

Every IBKR GET has a 30s connect / 120s read timeout, so a connection IBKR
accepts but never answers fails instead of hanging indefinitely (previously
unbounded — a `download` once hung over 4 hours and had to be killed by hand).
DNS/name-resolution failures and connect/read timeouts are retried seven times
for the same request with bounded backoff (1, 2, 4, 8, 16, 30, and 30
seconds). Other network failures and Flex API errors still fail closed; these
retries do not count as a new query and do not alter the two-minute pacing
between distinct statements.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success, including "all queries are up to date" and queries skipped within their interval |
| 1 | At least one query failed |
| 2 | Usage error (bad option or argument, e.g. `--type` with `--query <ID>`) |
| 3 | IBKR rejected an account's Flex token (takes precedence over 1) |
| 4 | Another `pyflexweb download` holds the lock; nothing was requested |

Up to v0.4.1 every command exited 0 even after a failure. Every command now
exits with its handler's code (for example `query remove <unknown id>` exits 1).

### Token rejection

When IBKR refuses a token (ErrorCode 1011 service account inactive, 1012 token
expired, 1013 IP restriction, 1015 token invalid), `download` prints one line to
stderr, in addition to the existing `Error requesting report: ...` line:

```
TOKEN REJECTED: IBKR refused the Flex token of account U1317359 (Cerabella): 1012 Token has expired. Create a new token in Client Portal (Performance & Reports > Flex Queries > Flex Web Service) and run: pyflexweb account add U1317359 --name "Cerabella" --token <new token> --expires "<expiry shown by IBKR>"
```

The token itself is never printed. For the rest of that run no request is sent
with that account's token: each remaining query of the account prints
`  Skipped: token of account U1317359 was rejected earlier in this run` and is
logged in `request_errors` with stage `skipped`. Queries of other accounts
continue normally, and the run exits 3.

All lines `download` printed up to v0.4.1 are still printed, unchanged, in the
same situations; the lines above are added alongside them.

### One download at a time

`download` holds an exclusive `flock` on `download.lock` in the data directory
(next to `status.db`) for the whole run. Two overlapping runs (say a daily full
run and an hourly trade-confirmation run) therefore never send requests on the
same token without the two-minute spacing. If the lock is held, `download`
prints `Another pyflexweb download is running (lock: <path>); nothing was requested.`
to stderr and exits 4. `--wait-lock SECONDS` waits up to that long for the lock
first (default 0: give up at once). Other commands take no lock. The lock file
is never deleted.

## `status.db` contract for monitors (schema v7)

External health checks may read a **copy** of `status.db` (never open it in
place). These parts are stable:

- `queries(id, name, added_on, min_interval, type, account_id)` and
  `requests(request_id, query_id, status, requested_at, completed_at, last_updated, output_path)`
  are unchanged. `requests` timestamps are the host's **local** time, naive ISO-8601.
- `accounts.token_expires_at TEXT NULL`: the token's expiry, ISO-8601 UTC
  `YYYY-MM-DDTHH:MM:SSZ`, or NULL when not recorded. `accounts.added_on` is
  reset whenever the token is replaced (it means "token last set"; SQLite
  `CURRENT_TIMESTAMP`, UTC, `YYYY-MM-DD HH:MM:SS`).
- `request_errors`, one row per failed Flex request:

  ```sql
  CREATE TABLE request_errors (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      query_id TEXT NOT NULL,
      account_id TEXT,
      occurred_at TEXT NOT NULL,  -- ISO-8601 UTC, YYYY-MM-DDTHH:MM:SSZ
      stage TEXT NOT NULL,        -- 'send' | 'get' | 'skipped'
      error_code TEXT,            -- IBKR Flex ErrorCode, NULL for network/parse failures
      error_message TEXT,
      kind TEXT NOT NULL          -- 'token' | 'rate_limit' | 'not_ready' | 'other'
  );
  CREATE INDEX idx_request_errors_query_time ON request_errors (query_id, occurred_at);
  ```

  - `stage`: `send` = SendRequest failed; `get` = polling GetStatement gave up
    (the request also gets a `failed` row in `requests`; the code and message
    are those of the last GetStatement error, if any; with none, `kind` is
    `not_ready`); `skipped` = not sent because the account's token was
    rejected earlier in the same run.
  - `kind`: `token` = codes 1011, 1012, 1013, 1015 (or, with no known code, a
    message containing "token has expired" / "token is invalid"); `rate_limit` =
    1018; `not_ready` = 1001, 1004-1009, 1019, 1021, and IBKR's "Statement could
    not be generated at this time. Please try again shortly." text whatever
    code comes with it; `other` = everything else, including network and parse
    failures.
  - A later successful download does **not** delete error rows. A query is
    currently failing when its newest `request_errors.occurred_at` is later
    than its newest completed request (`requests` uses local time, so convert
    before comparing).
  - Rows older than 90 days are pruned, per query, whenever a new row is written.
  - Not logged here: queries whose account has no token configured, and
    failures to write the report file (both still mark the run failed, exit 1).

## Commands

```
token set|get|unset          Manage IBKR token (global fallback)
account add <id> --token T   Add an account or replace its token (--name, --expires optional)
account expiry <id> [WHEN]   Show or set the token expiry (--unset to clear)
account list [--json]        List configured accounts with token expiry
account rm <id>              Remove an account
account edit <id>            Change an account's ID (--new-id) and/or name (--name)
query add <id> --name "..."  Add query (--type, --min-interval, --account)
query remove|rename <id>     Remove or rename a query
query interval <id> [hours]  Set per-query download interval (--unset to revert)
query type <id> [TYPE]       Show or change a query's type in place
query list [--json]          List queries with status
download                     Download reports (--query ID, --type, --force, --output,
                             --output-dir, --wait-lock)
status                       Alias for query list
config set|get|unset|list    Manage defaults (output_dir, poll_interval, max_attempts)
```

## Query Types

| Type | Default Interval |
|------|-----------------|
| `activity` | 6 hours |
| `trade-confirmation` | 1 hour |

Per-query overrides: `pyflexweb query interval 123456 12` (set to 12h)

To change a query's type without touching anything else (name, account,
`added_on`, interval override, download history):
`pyflexweb query type 123456 trade-confirmation`. Do not use `query add` for
this: re-adding an existing ID replaces the whole row, which resets `added_on`
and drops any `--min-interval` override you do not repeat.

## Publishing

`make version` bumps the patch version, commits, tags, and pushes. GitHub Actions publishes to PyPI on any `v*` tag.

## License

GPL-3.0-or-later
