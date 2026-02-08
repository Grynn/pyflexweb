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
token set|get|unset          Manage IBKR token
query add <id> --name "..."  Add query (--type activity|trade-confirmation, --min-interval N)
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

## License

GPL-3.0-or-later
