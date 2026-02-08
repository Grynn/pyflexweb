"""Command handlers for CLI commands."""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any

from .client import IBKRFlexClient
from .database import FlexDatabase

# Default minimum interval between downloads (hours) per query type
TYPE_INTERVAL_DEFAULTS = {
    "activity": 6,
    "trade-confirmation": 1,
}

VALID_QUERY_TYPES = list(TYPE_INTERVAL_DEFAULTS.keys())


def _effective_interval(query_info: dict) -> int:
    """Return the effective min-interval hours for a query."""
    if query_info.get("min_interval") is not None:
        return query_info["min_interval"]
    return TYPE_INTERVAL_DEFAULTS.get(query_info.get("type", "activity"), 6)


def handle_token_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'token' command and its subcommands."""
    if args.subcommand == "set":
        db.set_token(args.token)
        print("Token set successfully.")
        return 0
    elif args.subcommand == "get":
        token = db.get_token()
        if token:
            print(f"Stored token: {token}")
        else:
            print("No token found. Set one with 'pyflexweb token set <token>'")
            return 1
        return 0
    elif args.subcommand == "unset":
        db.unset_token()
        print("Token removed.")
        return 0
    else:
        print("Missing subcommand. Use 'set', 'get', or 'unset'.")
        return 1


def handle_query_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'query' command and its subcommands."""
    if args.subcommand == "add":
        query_type = getattr(args, "query_type", "activity") or "activity"
        min_interval = getattr(args, "min_interval", None)
        db.add_query(args.query_id, args.name, query_type=query_type, min_interval=min_interval)
        parts = [f"Query ID {args.query_id} added ({query_type})."]
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

    elif args.subcommand == "list":
        queries = db.get_all_queries_with_status()
        json_output = getattr(args, "json_output", False)

        if not queries:
            if json_output:
                print("[]")
            else:
                print("No query IDs found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")
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

        print(f"{'ID':<10} {'Name':<35} {'Type':<20} {'Interval':<10} {'Last Download':<20} {'Status':<10}")
        print(f"{'-' * 10} {'-' * 35} {'-' * 20} {'-' * 10} {'-' * 20} {'-' * 10}")

        for query in queries:
            query_id = query["id"]
            name_display = query["name"] if query["name"] else "unnamed"
            type_display = query.get("type", "activity")
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

            print(f"{query_id:<10} {name_display[:35]:<35} {type_display:<20} {interval_display:<10} {last_time:<20} {status:<10}")

        return 0

    else:
        print("Missing subcommand. Use 'add', 'remove', 'rename', 'interval', or 'list'.")
        return 1


def handle_download_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'download' command."""
    token = db.get_token()
    if not token:
        print("No token found. Set one with 'pyflexweb token set <token>'")
        return 1

    # Determine which queries to download
    if args.query == "all":
        if args.force:
            queries_to_download = db.get_all_queries_with_status()
            if not queries_to_download:
                print("No queries found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")
                return 0
            print(f"Force downloading all {len(queries_to_download)} queries")
        else:
            queries_to_download = db.get_queries_needing_download(TYPE_INTERVAL_DEFAULTS)
            if not queries_to_download:
                print("All queries are up to date. Use --force to download anyway.")
                return 0
            print(f"Found {len(queries_to_download)} queries that need updating")
    else:
        query_info = db.get_query_info(args.query)
        if not query_info:
            print(f"Query ID {args.query} not found. Add it with 'pyflexweb query add {args.query}'")
            return 1
        queries_to_download = [query_info]

    # Validate options
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

    client = IBKRFlexClient(token)
    overall_success = True

    for query_info in queries_to_download:
        query_id = query_info["id"]
        query_name = query_info["name"] or query_id

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

        # Request report from IBKR
        request_id = client.request_report(query_id)
        if not request_id:
            print("  Failed to request report.")
            overall_success = False
            continue

        db.add_request(request_id, query_id)

        # Determine output filename
        if len(queries_to_download) == 1 and args.output:
            output_file = os.path.join(output_dir, args.output)
        else:
            today = datetime.now().strftime("%Y%m%d")
            safe_desc = "".join(c if c.isalnum() else "_" for c in (query_info["name"] or query_id))
            output_file = os.path.join(output_dir, f"{safe_desc}_{today}.xml")

        # Poll for the report
        print(f"  Polling (max {args.max_attempts} attempts, {args.poll_interval}s interval)...")
        report_xml = None

        for attempt in range(1, args.max_attempts + 1):
            print(f"  Attempt {attempt}/{args.max_attempts}...", end="", flush=True)
            if attempt == 1:
                time.sleep(args.poll_interval / 2)
            report_xml = client.get_report(request_id)

            if report_xml:
                print(" OK")
                break

            print(" waiting...")
            if attempt < args.max_attempts:
                time.sleep(args.poll_interval)

        if not report_xml:
            print(f"  Report not available after {args.max_attempts} attempts.")
            db.update_request_status(request_id, "failed")
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

    return 0 if overall_success else 1


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
        import platformdirs

        config_defaults = {
            "default_output_dir": str(platformdirs.user_data_path("pyflexweb")),
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
