"""
Command-line interface for PyFlexWeb.

This module provides the main entry point and argument parsing for the PyFlexWeb CLI.
"""

import sys

import click

from .database import FlexDatabase
from .handlers import (
    handle_config_command,
    handle_download_command,
    handle_fetch_command,
    handle_query_command,
    handle_request_command,
    handle_token_command,
)


# Common options
def common_options(func):
    """Common options for commands that fetch reports."""
    func = click.option("--output", help="Output filename (for single report downloads only)")(func)
    func = click.option(
        "--output-dir",
        help="Directory to save reports",
    )(func)
    func = click.option(
        "--poll-interval",
        type=int,
        help="Seconds to wait between polling attempts",
    )(func)
    func = click.option(
        "--max-attempts",
        type=int,
        help="Maximum number of polling attempts",
    )(func)
    return func


def get_effective_options(ctx, **provided_options):
    """Get effective options by combining provided options with defaults from config."""
    db = ctx.obj["db"]
    effective = {}

    # Define config keys and their CLI option names
    config_mappings = {
        "default_output_dir": "output_dir",
        "default_poll_interval": "poll_interval",
        "default_max_attempts": "max_attempts",
    }

    for config_key, option_name in config_mappings.items():
        provided_value = provided_options.get(option_name)
        if provided_value is not None:
            effective[option_name] = provided_value
        else:
            # Get from config, with built-in defaults
            if option_name == "poll_interval":
                default_value = db.get_config(config_key, "30")
                effective[option_name] = int(default_value)
            elif option_name == "max_attempts":
                default_value = db.get_config(config_key, "20")
                effective[option_name] = int(default_value)
            elif option_name == "output_dir":
                effective[option_name] = db.get_config(config_key)
            else:
                effective[option_name] = provided_options.get(option_name)

    # Keep other options as-is
    for key, value in provided_options.items():
        if key not in config_mappings.values():
            effective[key] = value

    return effective


@click.group(invoke_without_command=True)
@click.version_option(package_name="pyflexweb")
@click.pass_context
def cli(ctx):
    """Download IBKR Flex reports using the Interactive Brokers flex web service."""
    db = FlexDatabase()
    ctx.ensure_object(dict)
    ctx.obj["db"] = db

    # If no command is provided, show help text
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        exit(1)

    return 0


# Token commands
@cli.group(invoke_without_command=True)
@click.pass_context
def token(ctx):
    """Manage IBKR Flex token."""
    # Default to 'get' when no subcommand is provided
    if ctx.invoked_subcommand is None:
        args = type("Args", (), {"subcommand": "get"})
        return handle_token_command(args, ctx.obj["db"])


@token.command("set")
@click.argument("token_value")
@click.pass_context
def token_set(ctx, token_value):
    """Set your IBKR token."""
    args = type("Args", (), {"subcommand": "set", "token": token_value})
    return handle_token_command(args, ctx.obj["db"])


@token.command("get")
@click.pass_context
def token_get(ctx):
    """Display your stored token."""
    args = type("Args", (), {"subcommand": "get"})
    return handle_token_command(args, ctx.obj["db"])


@token.command("unset")
@click.pass_context
def token_unset(ctx):
    """Remove your stored token."""
    args = type("Args", (), {"subcommand": "unset"})
    return handle_token_command(args, ctx.obj["db"])


# Config commands
@cli.group()
@click.pass_context
def config(ctx):
    """Manage default configuration settings."""
    pass


@config.command("set")
@click.argument("key", type=click.Choice(["default_output_dir", "default_poll_interval", "default_max_attempts"]))
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Set a default configuration value.

    Available keys:
    - default_output_dir: Default directory for saving reports
    - default_poll_interval: Default seconds between polling attempts
    - default_max_attempts: Default maximum polling attempts
    """
    args = type("Args", (), {"subcommand": "set", "key": key, "value": value})
    return handle_config_command(args, ctx.obj["db"])


@config.command("get")
@click.argument("key", required=False)
@click.pass_context
def config_get(ctx, key):
    """Get configuration value(s)."""
    args = type("Args", (), {"subcommand": "get", "key": key})
    return handle_config_command(args, ctx.obj["db"])


@config.command("unset")
@click.argument("key")
@click.pass_context
def config_unset(ctx, key):
    """Remove a configuration value."""
    args = type("Args", (), {"subcommand": "unset", "key": key})
    return handle_config_command(args, ctx.obj["db"])


@config.command("list")
@click.pass_context
def config_list(ctx):
    """List all configuration values."""
    args = type("Args", (), {"subcommand": "list", "key": None})
    return handle_config_command(args, ctx.obj["db"])


# Query commands
@cli.group(invoke_without_command=True)
@click.pass_context
def query(ctx):
    """Manage Flex query IDs."""
    if ctx.invoked_subcommand is None:
        # Default to 'list' if no subcommand is provided
        args = type("Args", (), {"subcommand": "list"})
        return handle_query_command(args, ctx.obj["db"])
    return 0


@query.command("add")
@click.argument("query_id")
@click.option("--name", required=True, help="A descriptive name for the query")
@click.pass_context
def query_add(ctx, query_id, name):
    """Add a new query ID."""
    args = type("Args", (), {"subcommand": "add", "query_id": query_id, "name": name})
    return handle_query_command(args, ctx.obj["db"])


@query.command("remove")
@click.argument("query_id")
@click.pass_context
def query_remove(ctx, query_id):
    """Remove a query ID."""
    args = type("Args", (), {"subcommand": "remove", "query_id": query_id})
    return handle_query_command(args, ctx.obj["db"])


@query.command("rename")
@click.argument("query_id")
@click.option("--name", required=True, help="The new name for the query")
@click.pass_context
def query_rename(ctx, query_id, name):
    """Rename a query."""
    args = type("Args", (), {"subcommand": "rename", "query_id": query_id, "name": name})
    return handle_query_command(args, ctx.obj["db"])


@query.command("list")
@click.pass_context
def query_list(ctx):
    """List all stored query IDs."""
    args = type("Args", (), {"subcommand": "list"})
    return handle_query_command(args, ctx.obj["db"])


# Report request command
@cli.command("request")
@click.argument("query_id")
@click.pass_context
def request(ctx, query_id):
    """Request a Flex report."""
    args = type("Args", (), {"query_id": query_id})
    return handle_request_command(args, ctx.obj["db"])


# Report fetch command
@cli.command("fetch")
@click.argument("request_id")
@common_options
@click.pass_context
def fetch(ctx, request_id, output, output_dir, poll_interval, max_attempts):
    """Fetch a requested report."""
    effective_options = get_effective_options(
        ctx, request_id=request_id, output=output, output_dir=output_dir, poll_interval=poll_interval, max_attempts=max_attempts
    )

    args = type("Args", (), effective_options)
    return handle_fetch_command(args, ctx.obj["db"])


# Report status command (alias for query list)
@cli.command("status")
@click.pass_context
def status(ctx):
    """Show status of all stored queries (alias for 'query list')."""
    args = type("Args", (), {"subcommand": "list"})
    return handle_query_command(args, ctx.obj["db"])


# All-in-one download command
@cli.command("download")
@click.option("--query", default="all", help="The query ID to download a report for (default: all)")
@click.option("--force", is_flag=True, help="Force download even if report was already downloaded today")
@common_options
@click.pass_context
def download(ctx, query, force, output, output_dir, poll_interval, max_attempts):
    """Request and download a report in one step.

    If --query is not specified, downloads all queries not updated in 24 hours.
    """
    effective_options = get_effective_options(
        ctx, query=query, force=force, output=output, output_dir=output_dir, poll_interval=poll_interval, max_attempts=max_attempts
    )

    args = type("Args", (), effective_options)
    return handle_download_command(args, ctx.obj["db"])


def main():
    """Main entry point for the CLI."""
    try:
        sys.exit(cli())  # pylint: disable=no-value-for-parameter
    except Exception as e:  # pylint: disable=broad-except
        click.echo(f"Error: {e}", err=True)
        return 1
    finally:
        # No need to close db here as it's managed within the cli context
        pass


if __name__ == "__main__":
    sys.exit(main())
