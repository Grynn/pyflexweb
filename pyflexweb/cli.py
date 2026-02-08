"""
Command-line interface for PyFlexWeb.

This module provides the main entry point and argument parsing for the PyFlexWeb CLI.
"""

import sys

import click
import platformdirs

from .database import FlexDatabase
from .handlers import (
    VALID_QUERY_TYPES,
    handle_config_command,
    handle_download_command,
    handle_query_command,
    handle_token_command,
)


def get_effective_options(ctx, **provided_options):
    """Get effective options by combining provided options with defaults from config."""
    db = ctx.obj["db"]
    effective = {}

    config_mappings = {
        "default_output_dir": "output_dir",
        "default_poll_interval": "poll_interval",
        "default_max_attempts": "max_attempts",
    }

    for config_key, option_name in config_mappings.items():
        provided_value = provided_options.get(option_name)
        if provided_value is not None:
            effective[option_name] = provided_value
        elif option_name == "poll_interval":
            effective[option_name] = int(db.get_config(config_key, "30"))
        elif option_name == "max_attempts":
            effective[option_name] = int(db.get_config(config_key, "20"))
        elif option_name == "output_dir":
            default_output_dir = str(platformdirs.user_data_path("pyflexweb"))
            effective[option_name] = db.get_config(config_key, default_output_dir)

    # Keep other options as-is
    for key, value in provided_options.items():
        if key not in config_mappings.values():
            effective[key] = value

    return effective


@click.group(invoke_without_command=True)
@click.version_option(package_name="pyflexweb")
@click.pass_context
def cli(ctx):
    """Download IBKR Flex reports using the Interactive Brokers flex web service.

    Use 'pyflexweb config' to view/modify default settings.
    """
    db = FlexDatabase()
    ctx.ensure_object(dict)
    ctx.obj["db"] = db

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        click.echo(f"\nDatabase directory: {db.db_dir}")
        default_output_dir = str(platformdirs.user_data_path("pyflexweb"))
        click.echo(f"Default output directory: {default_output_dir}")
        exit(1)

    return 0


# --- Token commands ---


@cli.group(invoke_without_command=True)
@click.pass_context
def token(ctx):
    """Manage IBKR Flex token."""
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


# --- Config commands ---


@cli.group(invoke_without_command=True)
@click.pass_context
def config(ctx):
    """Manage default configuration settings."""
    if ctx.invoked_subcommand is None:
        args = type("Args", (), {"subcommand": "list", "key": None})
        return handle_config_command(args, ctx.obj["db"])


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


# --- Query commands ---


@cli.group(invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
@click.pass_context
def query(ctx, json_output):
    """Manage Flex query IDs."""
    if ctx.invoked_subcommand is None:
        args = type("Args", (), {"subcommand": "list", "json_output": json_output})
        return handle_query_command(args, ctx.obj["db"])
    return 0


@query.command("add")
@click.argument("query_id")
@click.option("--name", required=True, help="A descriptive name for the query")
@click.option("--type", "query_type", type=click.Choice(VALID_QUERY_TYPES), default="activity", help="Query type (default: activity)")
@click.option("--min-interval", type=int, default=None, help="Min hours between downloads (overrides type default)")
@click.pass_context
def query_add(ctx, query_id, name, query_type, min_interval):
    """Add a new query ID."""
    args = type(
        "Args", (), {"subcommand": "add", "query_id": query_id, "name": name, "query_type": query_type, "min_interval": min_interval}
    )
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


@query.command("interval")
@click.argument("query_id")
@click.argument("hours", type=int, required=False)
@click.option("--unset", is_flag=True, help="Remove per-query interval override (use type default)")
@click.pass_context
def query_interval(ctx, query_id, hours, unset):
    """Set the minimum download interval (hours) for a query.

    Examples:

      pyflexweb query interval 12345 12    # set to 12 hours

      pyflexweb query interval 12345 --unset  # revert to type default
    """
    if not unset and hours is None:
        query_info = ctx.obj["db"].get_query_info(query_id)
        if not query_info:
            print(f"Query ID {query_id} not found.")
            return 1
        interval = query_info.get("min_interval")
        if interval is not None:
            print(f"Query {query_id} min interval: {interval}h")
        else:
            print(f"Query {query_id} uses the type default interval.")
        return 0
    args = type("Args", (), {"subcommand": "interval", "query_id": query_id, "hours": hours, "unset": unset})
    return handle_query_command(args, ctx.obj["db"])


@query.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
@click.pass_context
def query_list(ctx, json_output):
    """List all stored query IDs."""
    args = type("Args", (), {"subcommand": "list", "json_output": json_output})
    return handle_query_command(args, ctx.obj["db"])


# --- Download command ---


@cli.command("download")
@click.option("--query", default="all", help="The query ID to download a report for (default: all)")
@click.option("--force", is_flag=True, help="Force download even if recently downloaded")
@click.option("--output", help="Output filename (for single report downloads only)")
@click.option("--output-dir", help="Directory to save reports")
@click.option("--poll-interval", type=int, help="Seconds to wait between polling attempts")
@click.option("--max-attempts", type=int, help="Maximum number of polling attempts")
@click.pass_context
def download(ctx, query, force, output, output_dir, poll_interval, max_attempts):
    """Download Flex reports.

    If --query is not specified, downloads all queries that are due based on their
    type interval (activity: 6h, trade-confirmation: 1h). Per-query intervals can
    be set with 'query interval <id> <hours>'.
    """
    effective_options = get_effective_options(
        ctx, query=query, force=force, output=output, output_dir=output_dir, poll_interval=poll_interval, max_attempts=max_attempts
    )

    args = type("Args", (), effective_options)
    return handle_download_command(args, ctx.obj["db"])


# --- Status command (convenience alias) ---


@cli.command("status")
@click.pass_context
def status(ctx):
    """Show status of all stored queries (alias for 'query list')."""
    args = type("Args", (), {"subcommand": "list"})
    return handle_query_command(args, ctx.obj["db"])


def main():
    """Main entry point for the CLI."""
    try:
        sys.exit(cli())  # pylint: disable=no-value-for-parameter
    except Exception as e:  # pylint: disable=broad-except
        click.echo(f"Error: {e}", err=True)
        return 1
    finally:
        pass


if __name__ == "__main__":
    sys.exit(main())
