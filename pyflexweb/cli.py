"""
Command-line interface for PyFlexWeb.

This module provides the main entry point and argument parsing for the PyFlexWeb CLI.
"""

import sys

import click

from .database import FlexDatabase, resolve_data_dir
from .handlers import (
    VALID_QUERY_TYPES,
    handle_account_command,
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
            effective[option_name] = db.get_config(config_key, resolve_data_dir())

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
        click.echo(f"Default output directory: {resolve_data_dir()}")
        exit(1)

    return 0


@cli.result_callback()
@click.pass_context
def _exit_with_handler_code(ctx, rv, **_params):
    """Make a handler's return value the process exit code.

    Click's standalone mode discards a command's return value and exits 0, so
    without this every command exited 0 even when its handler returned 1.
    Nested groups pass the leaf command's value up to here.
    """
    if isinstance(rv, int) and not isinstance(rv, bool) and rv != 0:
        ctx.exit(rv)


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


# --- Account commands ---


@cli.group(invoke_without_command=True)
@click.pass_context
def account(ctx):
    """Manage IBKR accounts (multi-account support)."""
    if ctx.invoked_subcommand is None:
        args = type("Args", (), {"subcommand": "list", "json_output": False})
        return handle_account_command(args, ctx.obj["db"])


@account.command("add")
@click.argument("account_id")
@click.option("--name", default=None, help="Display name for the account (e.g. 'Cerabella'). Kept from the existing account when omitted.")
@click.option("--token", "token_value", required=True, help="IBKR Flex token for this account")
@click.option(
    "--expires",
    default=None,
    help='Token expiry as shown by IBKR, e.g. "2027-10-29 11:30 EDT". Omitting it clears any stored expiry.',
)
@click.pass_context
def account_add(ctx, account_id, name, token_value, expires):
    """Add an IBKR account with its own Flex token, or replace its token.

    Re-adding an existing account replaces the token, keeps the name unless
    --name is given, resets 'added' to now, and replaces the stored expiry
    (cleared when --expires is omitted).
    """
    args = type(
        "Args",
        (),
        {"subcommand": "add", "account_id": account_id, "name": name, "token": token_value, "expires": expires},
    )
    return handle_account_command(args, ctx.obj["db"])


@account.command("expiry")
@click.argument("account_id")
@click.argument("when", nargs=-1)
@click.option("--unset", is_flag=True, help="Clear the recorded expiry")
@click.pass_context
def account_expiry(ctx, account_id, when, unset):
    """Show, set or clear the recorded expiry of an account's Flex token.

    \b
    WHEN forms (stored as UTC):
      YYYY-MM-DD                          00:00 UTC of that day
      YYYY-MM-DD HH:MM[:SS]Z              UTC
      YYYY-MM-DD HH:MM[:SS]+HH:MM         explicit UTC offset
      YYYY-MM-DD HH:MM[:SS] ET|EST|EDT    US Eastern, as IBKR's portal shows it
    \b
    Examples:
      pyflexweb account expiry U1317359                       # show
      pyflexweb account expiry U1317359 "2027-10-29 11:30 EDT"
      pyflexweb account expiry U1317359 --unset
    """
    args = type(
        "Args",
        (),
        {"subcommand": "expiry", "account_id": account_id, "when": " ".join(when) if when else None, "unset": unset},
    )
    return handle_account_command(args, ctx.obj["db"])


@account.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output JSON: id, name, added_on, token_expires_at, days_left (never the token)")
@click.pass_context
def account_list(ctx, json_output):
    """List all configured accounts with their token expiry."""
    args = type("Args", (), {"subcommand": "list", "json_output": json_output})
    return handle_account_command(args, ctx.obj["db"])


@account.command("rm")
@click.argument("account_id")
@click.pass_context
def account_rm(ctx, account_id):
    """Remove an account. Blocked if any queries still reference it."""
    args = type("Args", (), {"subcommand": "remove", "account_id": account_id})
    return handle_account_command(args, ctx.obj["db"])


@account.command("edit")
@click.argument("account_id")
@click.option("--new-id", default=None, help="New account ID")
@click.option("--name", default=None, help="New display name for the account")
@click.pass_context
def account_edit(ctx, account_id, new_id, name):
    """Edit an account (change ID and/or name)."""
    args = type("Args", (), {"subcommand": "edit", "account_id": account_id, "new_id": new_id, "name": name})
    return handle_account_command(args, ctx.obj["db"])


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
@click.option("--account", required=True, help="Account ID to associate with this query")
@click.pass_context
def query_add(ctx, query_id, name, query_type, min_interval, account):
    """Add a new query ID."""
    args = type(
        "Args",
        (),
        {
            "subcommand": "add",
            "query_id": query_id,
            "name": name,
            "query_type": query_type,
            "min_interval": min_interval,
            "account": account,
        },
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


@query.command("type")
@click.argument("query_id")
@click.argument("query_type", type=click.Choice(VALID_QUERY_TYPES), required=False)
@click.pass_context
def query_type_cmd(ctx, query_id, query_type):
    """Show or change a query's type in place.

    Only the type changes: name, account, added date, min-interval override
    and download history are kept.

    \b
    Examples:
      pyflexweb query type 12345                       # show
      pyflexweb query type 12345 trade-confirmation    # change
    """
    args = type("Args", (), {"subcommand": "type", "query_id": query_id, "query_type": query_type})
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
@click.option(
    "--type",
    "query_type",
    type=click.Choice(VALID_QUERY_TYPES),
    default=None,
    help="Only queries of this type (only with --query all)",
)
@click.option("--force", is_flag=True, help="Force download even if recently downloaded")
@click.option("--output", help="Output filename (for single report downloads only)")
@click.option("--output-dir", help="Directory to save reports")
@click.option("--poll-interval", type=int, help="Seconds to wait between polling attempts")
@click.option("--max-attempts", type=int, help="Maximum number of polling attempts")
@click.option(
    "--wait-lock",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Seconds to wait for another running download to finish (0 = give up at once)",
)
@click.pass_context
def download(ctx, query, query_type, force, output, output_dir, poll_interval, max_attempts, wait_lock):
    """Download Flex reports.

    If --query is not specified, downloads all queries that are due based on their
    type interval (activity: 6h, trade-confirmation: 1h). Per-query intervals can
    be set with 'query interval <id> <hours>'. --type limits the run to one
    query type.

    Only one download runs at a time: it holds an exclusive lock on
    download.lock in the data directory.

    \b
    Exit codes:
      0  success (including nothing due / skipped within interval)
      1  at least one query failed
      2  usage error
      3  IBKR rejected an account's Flex token (wins over 1; see the
         'TOKEN REJECTED:' line on stderr)
      4  another download holds the lock; nothing was requested
    """
    if query_type is not None and query != "all":
        raise click.UsageError("--type cannot be combined with --query <ID>; use it with --query all (the default).")

    effective_options = get_effective_options(
        ctx,
        query=query,
        query_type=query_type,
        force=force,
        output=output,
        output_dir=output_dir,
        poll_interval=poll_interval,
        max_attempts=max_attempts,
        wait_lock=wait_lock,
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
