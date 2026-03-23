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
pyflexweb account rename U1317359 "Main Account"
pyflexweb account remove U11049821
```

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

# Check status of all queries
pyflexweb status
```

## Commands

```
token set|get|unset          Manage IBKR token (global fallback)
account add <id> --token T   Add account (--name optional)
account list                 List configured accounts
account remove|rename <id>   Remove or rename an account
query add <id> --name "..."  Add query (--type, --min-interval, --account)
query remove|rename <id>     Remove or rename a query
query interval <id> [hours]  Set per-query download interval (--unset to revert)
query list [--json]          List queries with status
download                     Download reports (--query ID, --force, --output, --output-dir)
status                       Alias for query list
config set|get|unset|list    Manage defaults (output_dir, poll_interval, max_attempts)
```

## Query Types

| Type | Default Interval |
|------|-----------------|
| `activity` | 6 hours |
| `trade-confirmation` | 1 hour |

Per-query overrides: `pyflexweb query interval 123456 12` (set to 12h)

## Publishing

`make version` bumps the patch version, commits, tags, and pushes. GitHub Actions publishes to PyPI on any `v*` tag.

## License

GPL-3.0-or-later
