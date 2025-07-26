"""Command handlers for CLI commands."""

import os
import time
from datetime import datetime
from typing import Any

from .client import IBKRFlexClient
from .database import FlexDatabase


def handle_token_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'token' command and its subcommands."""
    if args.subcommand == "set":
        db.set_token(args.token)
        print("Token set successfully.")
        return 0
    elif args.subcommand == "get":
        token = db.get_token()
        if token:
            # Only show first/last 4 chars for security
            masked = f"{token[:4]}...{token[-4:]}"
            print(f"Stored token: {masked}")
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
        db.add_query(args.query_id, args.name)
        print(f"Query ID {args.query_id} added successfully.")
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
    elif args.subcommand == "list":
        queries = db.get_all_queries_with_status()
        if not queries:
            print("No query IDs found. Add one with 'pyflexweb query add <query_id> --name \"Query name\"'")
            return 0

        # Print table header for extended view
        print(f"{'ID':<10} {'Name':<40} {'Last Request':<20} {'Status':<10}")
        print(f"{'-' * 10} {'-' * 40} {'-' * 20} {'-' * 10}")

        # Print each query with its status
        for query in queries:
            query_id = query["id"]
            name_display = query["name"] if query["name"] else "unnamed"

            if query["latest_request"]:
                req = query["latest_request"]
                if req["completed_at"]:
                    last_time = datetime.fromisoformat(req["completed_at"]).strftime("%Y-%m-%d %H:%M")
                else:
                    last_time = datetime.fromisoformat(req["requested_at"]).strftime("%Y-%m-%d %H:%M")
                status = req["status"]
            else:
                last_time = "Never"
                status = "-"

            print(f"{query_id:<10} {name_display[:40]:<40} {last_time:<20} {status:<10}")

        return 0

    else:
        print("Missing subcommand. Use 'add', 'remove', 'rename', or 'list'.")
        return 1


def handle_request_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'request' command."""
    token = db.get_token()
    if not token:
        print("No token found. Set one with 'pyflexweb token set <token>'")
        return 1

    query_info = db.get_query_info(args.query_id)
    if not query_info:
        print(f"Query ID {args.query_id} not found. Add it with 'pyflexweb query add {args.query_id}'")
        return 1

    client = IBKRFlexClient(token)
    request_id = client.request_report(args.query_id)

    if not request_id:
        print("Failed to request report.")
        return 1

    # Store the request in the database
    db.add_request(request_id, args.query_id)

    # Just print the request ID so it can be captured in scripts
    print(request_id)
    return 0


def handle_fetch_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'fetch' command."""
    token = db.get_token()
    if not token:
        print("No token found. Set one with 'pyflexweb token set <token>'")
        return 1

    request_info = db.get_request_info(args.request_id)
    if not request_info:
        print(f"Request ID {args.request_id} not found in local database.")
        print("It may still be valid if created outside this tool or in another session.")

    client = IBKRFlexClient(token)

    # Setup output directory if provided
    output_dir = args.output_dir if hasattr(args, "output_dir") and args.output_dir else "."
    if output_dir != "." and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")
        except OSError as e:
            print(f"Error creating output directory: {e}")
            return 1

    # Determine output filename
    if args.output:
        output_file = os.path.join(output_dir, args.output)
    else:
        today = datetime.now().strftime("%Y%m%d")
        if request_info and request_info["query_id"]:
            output_file = os.path.join(output_dir, f"{request_info['query_id']}_{today}.xml")
        else:
            output_file = os.path.join(output_dir, f"flex_report_{today}.xml")

    # Poll for the report
    print(f"Polling for report (max {args.max_attempts} attempts, {args.poll_interval}s interval)...")
    report_xml = None

    for attempt in range(1, args.max_attempts + 1):
        print(f"Attempt {attempt}/{args.max_attempts}...", end="", flush=True)
        report_xml = client.get_report(args.request_id)

        if report_xml:
            print(" Success!")
            break

        print(" Not ready yet.")
        if attempt < args.max_attempts:
            time.sleep(args.poll_interval)

    if not report_xml:
        print(f"Report not available after {args.max_attempts} attempts.")
        if request_info:
            db.update_request_status(args.request_id, "failed")
        return 1

    # Save the report
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report_xml)
        print(f"Report saved to {output_file}")
    except OSError as e:
        print(f"Error saving report: {e}")
        if request_info:
            db.update_request_status(args.request_id, "failed")
        return 1

    # Update the database
    if request_info:
        db.update_request_status(args.request_id, "completed", output_file)

    return 0


def handle_download_command(args: dict[str, Any], db: FlexDatabase) -> int:
    """Handle the 'download' command (all-in-one request and fetch)."""
    token = db.get_token()
    if not token:
        print("No token found. Set one with 'pyflexweb token set <token>'")
        return 1

    # Determine which queries to download
    if args.query == "all":
        # Download all queries that haven't been updated in the last 24 hours
        queries_to_download = db.get_queries_not_updated(hours=24)
        if not queries_to_download:
            print("All queries have been updated within the last 24 hours.")
            return 0
        print(f"Found {len(queries_to_download)} queries that need updating")
    else:
        # Download a specific query
        query_info = db.get_query_info(args.query)
        if not query_info:
            print(f"Query ID {args.query} not found. Add it with 'pyflexweb query add {args.query}'")
            return 1
        queries_to_download = [query_info]

    # Check for invalid combinations
    if args.query != "all" and len(queries_to_download) == 1 and args.output:
        # Single query mode with output specified - this is fine
        pass
    elif args.query == "all" and args.output:
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

    # Process each query
    for query_info in queries_to_download:
        query_id = query_info["id"]
        query_name = query_info["name"] if query_info["name"] else query_id

        print(f"\nProcessing query: {query_name} (ID: {query_id})")

        # Check if we already downloaded a report for this query today
        if not args.force:
            latest_request = db.get_latest_request(query_id)
            if latest_request and latest_request["status"] == "completed":
                completed_date = datetime.fromisoformat(latest_request["completed_at"]).date()
                today = datetime.now().date()

                if completed_date == today:
                    print(f"Already downloaded a report for query {query_id} today.")
                    print(f"Output file: {latest_request['output_path']}")
                    print("Use --force to download again.")
                    continue

        # Request the report
        print(f"Requesting report for query {query_id}...")
        request_id = client.request_report(query_id)

        if not request_id:
            print("Failed to request report.")
            overall_success = False
            continue

        # Store the request in the database
        db.add_request(request_id, query_id)
        print(f"Request ID: {request_id}")

        # Determine output filename
        if len(queries_to_download) == 1 and args.output:
            output_file = os.path.join(output_dir, args.output)
        else:
            today = datetime.now().strftime("%Y%m%d")
            query_desc = query_info["name"] if query_info["name"] else query_id
            # Remove spaces and special chars from the query description
            safe_desc = "".join(c if c.isalnum() else "_" for c in query_desc)
            output_file = os.path.join(output_dir, f"{safe_desc}_{today}.xml")

        # Poll for the report
        print(f"Polling for report (max {args.max_attempts} attempts, {args.poll_interval}s interval)...")
        report_xml = None

        for attempt in range(1, args.max_attempts + 1):
            print(f"Attempt {attempt}/{args.max_attempts}...", end="", flush=True)
            if attempt == 1:
                time.sleep(args.poll_interval / 2)  # Initial delay before first attempt
            report_xml = client.get_report(request_id)

            if report_xml:
                print(" Success!")
                break

            print(" Not ready yet.")
            if attempt < args.max_attempts:
                time.sleep(args.poll_interval)

        if not report_xml:
            print(f"Report not available after {args.max_attempts} attempts.")
            db.update_request_status(request_id, "failed")
            overall_success = False
            continue

        # Save the report
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report_xml)
            print(f"Report saved to {output_file}")
        except OSError as e:
            print(f"Error saving report: {e}")
            db.update_request_status(request_id, "failed")
            overall_success = False
            continue

        # Update the database
        db.update_request_status(request_id, "completed", output_file)

    return 0 if overall_success else 1
