"""
Command-line interface for PyFlexWeb.

This module provides the main entry point and argument parsing for the PyFlexWeb CLI.
"""

import sys

import click

from .database import FlexDatabase
from .handlers import (
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
        help="Directory to save reports (default: current directory)",
    )(func)
    func = click.option(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds to wait between polling attempts (default: 30)",
    )(func)
    func = click.option(
        "--max-attempts",
        type=int,
        default=20,
        help="Maximum number of polling attempts (default: 20)",
    )(func)
    return func


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
@cli.group()
@click.pass_context
def token(ctx):
    """Manage IBKR Flex token."""
    pass


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
    args = type(
        "Args",
        (),
        {
            "request_id": request_id,
            "output": output,
            "output_dir": output_dir,
            "poll_interval": poll_interval,
            "max_attempts": max_attempts,
        },
    )
    return handle_fetch_command(args, ctx.obj["db"])


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
    args = type(
        "Args",
        (),
        {
            "query": query,
            "force": force,
            "output": output,
            "output_dir": output_dir,
            "poll_interval": poll_interval,
            "max_attempts": max_attempts,
        },
    )
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
