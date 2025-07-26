# PyFlexWeb

A command-line tool for downloading IBKR Flex reports using the Interactive Brokers flex web service.

[![CI](https://github.com/grynn/pyflexweb/actions/workflows/ci.yml/badge.svg)](https://github.com/grynn/pyflexweb/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/pyflexweb.svg)](https://pypi.org/project/pyflexweb/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyflexweb.svg)](https://pypi.org/project/pyflexweb/)
[![License](https://img.shields.io/github/license/grynn/pyflexweb.svg)](https://github.com/grynn/pyflexweb/blob/main/LICENSE)

## Features

- Store and manage your IBKR Flex Web Service token securely
- Manage multiple query IDs with descriptive names
- Download activity reports and trade confirmations
- Automatic handling of request/response workflow
- Track download history to avoid unnecessary downloads
- Batch download all reports that need updating

## Installation

```bash
# Clone the repository
git clone https://github.com/grynn/pyflexweb.git
cd pyflexweb

# Install the package
uv tool install . # or pip install -e .
```

## Usage

### Basic Setup

First, set up your IBKR Flex Web Service token:

```bash
pyflexweb token set YOUR_TOKEN_HERE
```

Add query IDs for your reports:

```bash
# Add a flex query
pyflexweb query add 123456 --name "Daily activity report"

# Add another query
pyflexweb query add 789012 --name "Trade confirmations"
```

### Listing Queries

To see all your stored queries with their last download status:

```bash
pyflexweb query
```

### Downloading Reports

Download all reports that haven't been updated in the last 24 hours:

```bash
pyflexweb download
```

Download a specific report:

```bash
pyflexweb download --query 123456
```

Force download even if the report was already downloaded today:

```bash
pyflexweb download --query 123456 --force
```

### Advanced Usage

For more control, you can use the two-step process:

```bash
# Request a report
request_id=$(pyflexweb request 123456)

# Fetch it later
pyflexweb fetch $request_id --output my_report.xml
```

#### Scripting Example

```bash
#!/bin/bash
# Daily report download script

# Request activity report
request_id=$(pyflexweb request 123456)
if [ $? -ne 0 ]; then
    echo "Failed to request report" >&2
    exit 1
fi

# Download the report
pyflexweb fetch $request_id --output "activity_$(date +%Y%m%d).xml"
```

#### Download Multiple Reports

```bash
#!/bin/bash
# Download all configured reports

# Get list of query IDs
queries=$(pyflexweb query list | tail -n +3 | awk '{print $1}')

for query in $queries; do
    echo "Downloading report for query $query..."
    pyflexweb download --query $query
done
```

### Other Commands

Check version information:

```bash
pyflexweb --version
```

Get help on any command:

```bash
pyflexweb --help
```

## License

This project is licensed under the terms of the GNU General Public License v3.0 or later. See the [LICENSE](LICENSE) file for details.

## Command Reference

### Token Management

- `token set <token_value>` - Store your IBKR token
- `token get` - Display your stored token (masked for security)
- `token unset` - Remove your stored token

### Query Management

- `query add <query_id> --name "Query Name"` - Add a query
- `query list` - List all stored queries
- `query` - List all queries with last download status (shorthand for `query list`)
- `query remove <query_id>` - Remove a query
- `query rename <query_id> --name "New Name"` - Rename a query

### Report Operations

- `request <query_id>` - Request a report
- `fetch <request_id> [--output filename.xml] [--poll-interval SECONDS] [--max-attempts NUM]` - Fetch a requested report
- `download [--query QUERY_ID|all] [--output filename.xml] [--force] [--poll-interval SECONDS] [--max-attempts NUM]` - Download reports

## Prerequisites

Before using PyFlexWeb, you need to:

1. Create a Flex Query in your IBKR Account Management portal
2. Generate a Flex Web Service token

For detailed instructions, see [IBKR's documentation](https://www.interactivebrokers.com/en/software/am/am/reports/flex_web_service_version_3.htm).

## Report Types

IBKR Flex reports provide data including:

- Total equity
- Open positions
- Trades
- Cash transactions
- Account statement information

The specific content depends on how you've configured your Flex Query in the IBKR Account Management portal.

## Data Storage

PyFlexWeb stores its data in a SQLite database located in your user data directory:

- **Windows**: `C:\Users\<username>\AppData\Local\pyflexweb\pyflexweb`
- **macOS**: `~/Library/Application Support/pyflexweb`
- **Linux**: `~/.local/share/pyflexweb`

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Clone the repository
git clone https://github.com/grynn/pyflexweb.git
cd pyflexweb

# Install development dependencies using uv
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest

# Run linting and formatting
make lint
# or manually:
uv run pre-commit run --all-files
```

### Releasing

This project uses automated PyPI publishing via GitHub Actions. To create a release:

```bash
# Bump version (choose one)
make bump-patch  # 0.1.1 -> 0.1.2
make bump-minor  # 0.1.1 -> 0.2.0
make bump-major  # 0.1.1 -> 1.0.0

# Create GitHub release (automatically publishes to PyPI)
make release
```

The release process will:

1. Run linting and tests
2. Build the package
3. Create a git tag and commit
4. Push to GitHub and create a release
5. Automatically publish to PyPI via GitHub Actions

For initial PyPI setup, run `make setup-pypi` for detailed instructions.

### Code Quality

This project uses pre-commit hooks to ensure code quality:

- **ruff**: Fast Python linter and formatter (handles both linting and formatting)
- **Standard hooks**: trailing whitespace, end-of-file fixes, etc.

The pre-commit hooks will run automatically on each commit. You can also run them manually:

```bash
# Run all pre-commit hooks
make pre-commit-run

# Run just ruff linting
uv run ruff check --fix .

# Run just ruff formatting
uv run ruff format .
```

## Acknowledgments

- [Interactive Brokers](https://www.interactivebrokers.com) for providing the Flex Web Service
- [platformdirs](https://github.com/platformdirs/platformdirs) for cross-platform data directory support
- [requests](https://github.com/psf/requests) for simplified HTTP handling
