#!/usr/bin/env python3
"""DeerFlow PostgreSQL database maintenance tool.

Commands:
    stats          - Show database statistics (size, threads, checkpoints)
    clean          - Interactively clean up old threads
    prune          - Prune old checkpoints from a thread while keeping recent ones
    truncate       - Truncate message history in a thread to last N messages
    view-messages  - View message history in a thread (to decide what to truncate)
    backup         - Create full backup of checkpoint data and project files

Usage:
    python scripts/db_maintenance.py stats
    python scripts/db_maintenance.py clean
    python scripts/db_maintenance.py prune
    python scripts/db_maintenance.py truncate [--thread THREAD_ID] [--keep N]
    python scripts/db_maintenance.py view-messages [--thread THREAD_ID]
    python scripts/db_maintenance.py backup [--output DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import ormsgpack
import psycopg
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.table import Table

# Import LangGraph serializer for message handling
try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer, _msgpack_default
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

console = Console()

# Default paths
DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_DEER_FLOW_HOME = Path("backend/.deer-flow")

# PostgreSQL container name (can be overridden via environment)
POSTGRES_CONTAINER = os.environ.get("DEER_FLOW_POSTGRES_CONTAINER", "fishgenomedb-db-1")


def get_postgres_connection_string() -> str:
    """Load PostgreSQL connection string from config.yaml."""
    import yaml

    # Check multiple locations for config.yaml
    config_paths = [
        os.environ.get("DEER_FLOW_CONFIG_PATH"),
        "config.yaml",  # Current directory
        "../config.yaml",  # Parent directory (when running from backend/)
    ]

    config_path = None
    for path in config_paths:
        if path and Path(path).exists():
            config_path = Path(path)
            break

    if not config_path:
        console.print("[red]Error: config.yaml not found[/red]")
        console.print("[dim]Searched: current directory, parent directory[/dim]")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    checkpointer = config.get("checkpointer", {})
    if checkpointer.get("type") != "postgres":
        console.print("[red]Error: checkpointer type is not 'postgres' in config.yaml[/red]")
        sys.exit(1)

    conn_str = checkpointer.get("connection_string")
    if not conn_str:
        console.print("[red]Error: no connection_string in checkpointer config[/red]")
        sys.exit(1)

    # Replace host.docker.internal with localhost for local execution
    return conn_str.replace("host.docker.internal", "localhost")


def get_deer_flow_home() -> Path:
    """Get DEER_FLOW_HOME directory."""
    home = os.environ.get("DEER_FLOW_HOME", "")
    if home:
        return Path(home)

    # Default: resolve relative to project root
    # Detect if we're in backend/ directory and adjust path accordingly
    cwd = Path.cwd()
    if (cwd / ".deer-flow").exists():
        # We're in project root
        return cwd / ".deer-flow"
    elif (cwd / "../backend/.deer-flow").exists():
        # We're in backend/ directory
        return (cwd / "../backend/.deer-flow").resolve()
    else:
        # Default fallback
        return Path("backend/.deer-flow")


def run_psql_query(conn_str: str, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a query and return results as list of dicts."""
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def run_psql_execute(conn_str: str, query: str, params: tuple = ()) -> int:
    """Execute a query without returning results. Returns rowcount."""
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
        conn.commit()
        return cur.rowcount


def run_psql_vacuum(conn_str: str) -> None:
    """Run VACUUM ANALYZE (must be outside transaction)."""
    with psycopg.connect(conn_str) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("VACUUM ANALYZE")


def format_size(bytes_val: int | None) -> str:
    """Format bytes to human readable string."""
    if not bytes_val:
        return "0 bytes"
    mb = bytes_val / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    elif mb >= 1:
        return f"{mb:.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f} KB"
    else:
        return f"{bytes_val} bytes"


# ---------------------------------------------------------------------------
# Stats Command
# ---------------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> None:
    """Show database statistics."""
    conn_str = get_postgres_connection_string()
    db_name = conn_str.split("/")[-1].split("?")[0]

    # Validate db_name contains only safe characters (alphanumeric, underscore, hyphen)
    if not db_name.replace("_", "").replace("-", "").isalnum():
        console.print("[red]Error: Invalid database name[/red]")
        sys.exit(1)

    # Database size
    size_result = run_psql_query(conn_str, "SELECT pg_size_pretty(pg_database_size(%s)) as size", (db_name,))
    db_size = size_result[0]["size"] if size_result else "unknown"

    # Thread count and checkpoint stats
    thread_stats = run_psql_query(conn_str, """
        SELECT
            COUNT(DISTINCT thread_id) as thread_count,
            COUNT(*) as checkpoint_count,
            MIN(checkpoint_id) as oldest_checkpoint,
            MAX(checkpoint_id) as newest_checkpoint
        FROM checkpoints
    """)[0]

    # Checkpoint blobs size - use subquery to avoid Cartesian product
    blob_stats = run_psql_query(conn_str, """
        SELECT
            COUNT(*) as blob_count,
            SUM(LENGTH(blob)) as total_blob_bytes
        FROM checkpoint_blobs
        WHERE blob IS NOT NULL
    """)[0]

    # Per-thread breakdown - use subquery to avoid Cartesian product
    thread_breakdown = run_psql_query(conn_str, """
        SELECT
            c.thread_id,
            c.checkpoint_count,
            COALESCE(b.blob_bytes, 0) as blob_bytes
        FROM (
            SELECT thread_id, COUNT(*) as checkpoint_count
            FROM checkpoints
            GROUP BY thread_id
        ) c
        LEFT JOIN (
            SELECT thread_id, SUM(LENGTH(blob)) as blob_bytes
            FROM checkpoint_blobs
            GROUP BY thread_id
        ) b ON c.thread_id = b.thread_id
        ORDER BY c.checkpoint_count DESC
        LIMIT 20
    """)

    # Display results
    console.print("\n[bold cyan]DeerFlow Database Statistics[/bold cyan]\n")

    # Summary table
    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green")
    summary.add_row("Database Size", db_size)
    summary.add_row("Total Threads", str(thread_stats["thread_count"] or 0))
    summary.add_row("Total Checkpoints", str(thread_stats["checkpoint_count"] or 0))
    summary.add_row("Total Blobs", str(blob_stats["blob_count"] or 0))
    summary.add_row("Total Blob Size", format_size(blob_stats["total_blob_bytes"]))
    console.print(summary)

    # Thread breakdown
    if thread_breakdown:
        console.print()
        threads_table = Table(title="Top 20 Threads by Checkpoint Count")
        threads_table.add_column("Thread ID", style="cyan")
        threads_table.add_column("Checkpoints", justify="right")
        threads_table.add_column("Blob Size", justify="right")
        for row in thread_breakdown:
            threads_table.add_row(
                row["thread_id"][:36] + "..." if len(row["thread_id"]) > 36 else row["thread_id"],
                str(row["checkpoint_count"]),
                format_size(row["blob_bytes"])
            )
        console.print(threads_table)

    console.print()


# ---------------------------------------------------------------------------
# Clean Command
# ---------------------------------------------------------------------------

def cmd_clean(args: argparse.Namespace) -> None:
    """Interactively clean up old threads."""
    conn_str = get_postgres_connection_string()

    # Get all threads with stats - use subquery to avoid Cartesian product
    threads = run_psql_query(conn_str, """
        SELECT
            c.thread_id,
            c.checkpoint_count,
            c.last_checkpoint,
            COALESCE(b.blob_bytes, 0) as blob_bytes
        FROM (
            SELECT
                thread_id,
                COUNT(*) as checkpoint_count,
                MAX(checkpoint_id) as last_checkpoint
            FROM checkpoints
            GROUP BY thread_id
        ) c
        LEFT JOIN (
            SELECT thread_id, SUM(LENGTH(blob)) as blob_bytes
            FROM checkpoint_blobs
            GROUP BY thread_id
        ) b ON c.thread_id = b.thread_id
        ORDER BY c.last_checkpoint DESC
    """)

    if not threads:
        console.print("[yellow]No threads found in database.[/yellow]")
        return

    # Display threads
    console.print("\n[bold cyan]Available Threads[/bold cyan]\n")

    table = Table()
    table.add_column("#", justify="right", style="dim")
    table.add_column("Thread ID", style="cyan")
    table.add_column("Checkpoints", justify="right")
    table.add_column("Blob Size", justify="right")
    table.add_column("Last Checkpoint", style="dim")

    for i, row in enumerate(threads, 1):
        thread_id = row["thread_id"]
        last_cp = str(row["last_checkpoint"] or "")[:19]
        table.add_row(
            str(i),
            thread_id[:36] + "..." if len(thread_id) > 36 else thread_id,
            str(row["checkpoint_count"]),
            format_size(row["blob_bytes"]),
            last_cp
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(threads)} threads[/dim]\n")

    # Interactive selection
    console.print("[bold]Options:[/bold]")
    console.print("  - Enter thread numbers to delete (e.g., '1,3,5' or '1-5')")
    console.print("  - Enter 'all' to delete all threads")
    console.print("  - Enter 'prune' to prune old checkpoints from a thread")
    console.print("  - Press Enter to cancel\n")

    selection = Prompt.ask("Select threads to delete")

    if not selection.strip():
        console.print("[yellow]Cancelled.[/yellow]")
        return

    if selection.lower() == "prune":
        # Launch prune mode
        prune_thread_interactive(conn_str, threads)
        return

    # Parse selection
    thread_ids_to_delete = []

    if selection.lower() == "all":
        thread_ids_to_delete = [t["thread_id"] for t in threads]
    else:
        try:
            indices = parse_selection(selection, len(threads))
            thread_ids_to_delete = [threads[i]["thread_id"] for i in indices]
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    if not thread_ids_to_delete:
        console.print("[yellow]No threads selected.[/yellow]")
        return

    # Confirm deletion
    console.print(f"\n[yellow]Will delete {len(thread_ids_to_delete)} thread(s):[/yellow]")
    for tid in thread_ids_to_delete[:5]:
        console.print(f"  - {tid}")
    if len(thread_ids_to_delete) > 5:
        console.print(f"  ... and {len(thread_ids_to_delete) - 5} more")

    confirm = Prompt.ask("\nProceed?", choices=["y", "n"], default="n")
    if confirm != "y":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Delete threads in a single transaction
    deleted = 0
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            for tid in thread_ids_to_delete:
                cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (tid,))
                cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (tid,))
                cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (tid,))
                deleted += 1
        conn.commit()

    # Vacuum to reclaim space
    run_psql_vacuum(conn_str)

    console.print(f"\n[green]Successfully deleted {deleted} thread(s).[/green]")

    # Also clean up local thread directories
    deer_flow_home = get_deer_flow_home()
    threads_dir = deer_flow_home / "threads"
    if threads_dir.exists():
        for tid in thread_ids_to_delete:
            thread_dir = threads_dir / tid
            if thread_dir.exists():
                shutil.rmtree(thread_dir)
                console.print(f"[dim]Removed local directory: {thread_dir}[/dim]")


# ---------------------------------------------------------------------------
# Prune Command - Prune old checkpoints from a thread
# ---------------------------------------------------------------------------

def cmd_prune(args: argparse.Namespace) -> None:
    """Prune old checkpoints from a thread while keeping recent ones."""
    conn_str = get_postgres_connection_string()

    # Get all threads with stats
    threads = run_psql_query(conn_str, """
        SELECT
            c.thread_id,
            c.checkpoint_count,
            COALESCE(b.blob_bytes, 0) as blob_bytes
        FROM (
            SELECT thread_id, COUNT(*) as checkpoint_count
            FROM checkpoints
            GROUP BY thread_id
        ) c
        LEFT JOIN (
            SELECT thread_id, SUM(LENGTH(blob)) as blob_bytes
            FROM checkpoint_blobs
            GROUP BY thread_id
        ) b ON c.thread_id = b.thread_id
        ORDER BY c.checkpoint_count DESC
    """)

    if not threads:
        console.print("[yellow]No threads found in database.[/yellow]")
        return

    prune_thread_interactive(conn_str, threads)


def prune_thread_interactive(conn_str: str, threads: list[dict]) -> None:
    """Interactive thread pruning with message truncation support."""
    # Display threads
    console.print("\n[bold cyan]Select Thread to Prune[/bold cyan]\n")

    table = Table()
    table.add_column("#", justify="right", style="dim")
    table.add_column("Thread ID", style="cyan")
    table.add_column("Checkpoints", justify="right")
    table.add_column("Blob Size", justify="right")

    for i, row in enumerate(threads, 1):
        thread_id = row["thread_id"]
        table.add_row(
            str(i),
            thread_id[:36] + "..." if len(thread_id) > 36 else thread_id,
            str(row["checkpoint_count"]),
            format_size(row["blob_bytes"])
        )

    console.print(table)
    console.print()

    # Select thread
    try:
        thread_idx = IntPrompt.ask("Select thread number to prune", default=1) - 1
        if thread_idx < 0 or thread_idx >= len(threads):
            console.print("[red]Invalid thread number.[/red]")
            return
    except ValueError:
        console.print("[red]Invalid input.[/red]")
        return

    thread_id = threads[thread_idx]["thread_id"]
    total_checkpoints = threads[thread_idx]["checkpoint_count"]

    console.print(f"\n[cyan]Thread: {thread_id}[/cyan]")
    console.print(f"Total checkpoints: {total_checkpoints}")

    # Ask how many to keep
    try:
        keep_count = IntPrompt.ask(
            "How many recent checkpoints to keep?",
            default=min(100, total_checkpoints)
        )
        if keep_count < 1:
            console.print("[red]Must keep at least 1 checkpoint.[/red]")
            return
        if keep_count >= total_checkpoints:
            console.print("[yellow]Nothing to prune (keep count >= total checkpoints).[/yellow]")
            return
    except ValueError:
        console.print("[red]Invalid input.[/red]")
        return

    # Preview
    delete_count = total_checkpoints - keep_count
    console.print(f"\n[yellow]Will delete {delete_count} old checkpoints, keeping {keep_count} most recent.[/yellow]")

    # Get blob info before pruning
    blob_info = run_psql_query(conn_str, """
        SELECT COUNT(*) as blob_count, SUM(LENGTH(blob)) as total_bytes
        FROM checkpoint_blobs
        WHERE thread_id = %s
    """, (thread_id,))[0]

    console.print(f"Current blobs: {blob_info['blob_count']}, size: {format_size(blob_info['total_bytes'])}")

    confirm = Prompt.ask("\nProceed?", choices=["y", "n"], default="n")
    if confirm != "y":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Perform pruning
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            # 1. Get checkpoints to keep (most recent N)
            cur.execute("""
                SELECT checkpoint_id, checkpoint
                FROM checkpoints
                WHERE thread_id = %s
                ORDER BY checkpoint_id DESC
                LIMIT %s
            """, (thread_id, keep_count))
            keep_rows = cur.fetchall()

            if not keep_rows:
                console.print("[red]No checkpoints found.[/red]")
                return

            keep_ids = [row[0] for row in keep_rows]

            # 2. Extract all blob versions referenced by kept checkpoints
            referenced_versions = set()
            for row in keep_rows:
                cp = row[1] if row[1] else {}
                channel_versions = cp.get("channel_versions", {})
                if isinstance(channel_versions, dict):
                    referenced_versions.update(channel_versions.values())

            # 3. Delete old checkpoints
            placeholders = ",".join(["%s"] * len(keep_ids))
            cur.execute(f"""
                DELETE FROM checkpoints
                WHERE thread_id = %s
                AND checkpoint_id NOT IN ({placeholders})
            """, [thread_id] + keep_ids)
            deleted_checkpoints = cur.rowcount

            # 4. Delete checkpoint_writes for deleted checkpoints
            cur.execute(f"""
                DELETE FROM checkpoint_writes
                WHERE thread_id = %s
                AND checkpoint_id NOT IN ({placeholders})
            """, [thread_id] + keep_ids)
            deleted_writes = cur.rowcount

            # 5. Delete blobs that are no longer referenced
            if referenced_versions:
                version_placeholders = ",".join(["%s"] * len(referenced_versions))
                cur.execute(f"""
                    DELETE FROM checkpoint_blobs
                    WHERE thread_id = %s
                    AND version NOT IN ({version_placeholders})
                """, [thread_id] + list(referenced_versions))
                deleted_blobs = cur.rowcount
            else:
                # No versions referenced, delete all blobs for this thread
                cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
                deleted_blobs = cur.rowcount

        conn.commit()

    # Vacuum to reclaim space
    run_psql_vacuum(conn_str)

    console.print(f"\n[green]Pruning complete![/green]")
    console.print(f"  Deleted checkpoints: {deleted_checkpoints}")
    console.print(f"  Deleted writes: {deleted_writes}")
    console.print(f"  Deleted blobs: {deleted_blobs}")
    console.print(f"  Kept checkpoints: {keep_count}")


# ---------------------------------------------------------------------------
# Truncate Command - Truncate message history in a thread
# ---------------------------------------------------------------------------

def cmd_truncate(args: argparse.Namespace) -> None:
    """Truncate message history in a thread to last N messages."""
    if not LANGGRAPH_AVAILABLE:
        console.print("[red]Error: LangGraph not available. Cannot truncate messages.[/red]")
        console.print("[dim]Install with: uv pip install langgraph-checkpoint[/dim]")
        sys.exit(1)

    conn_str = get_postgres_connection_string()

    # Get threads with message blobs
    threads = run_psql_query(conn_str, """
        SELECT
            cb.thread_id,
            COUNT(*) as message_blob_count,
            SUM(LENGTH(cb.blob)) as total_blob_bytes
        FROM checkpoint_blobs cb
        WHERE cb.channel = 'messages'
        GROUP BY cb.thread_id
        ORDER BY SUM(LENGTH(cb.blob)) DESC
    """)

    if not threads:
        console.print("[yellow]No threads with message blobs found in database.[/yellow]")
        return

    # If thread_id provided via args, use it; otherwise show interactive selection
    thread_id = args.thread
    if thread_id:
        # Validate thread exists
        matching = [t for t in threads if t["thread_id"] == thread_id]
        if not matching:
            console.print(f"[red]Thread {thread_id} not found or has no messages.[/red]")
            return
        thread_info = matching[0]
    else:
        # Display threads
        console.print("\n[bold cyan]Select Thread to Truncate Messages[/bold cyan]\n")

        table = Table()
        table.add_column("#", justify="right", style="dim")
        table.add_column("Thread ID", style="cyan")
        table.add_column("Blob Count", justify="right")
        table.add_column("Total Size", justify="right")

        for i, row in enumerate(threads, 1):
            thread_id_disp = row["thread_id"]
            table.add_row(
                str(i),
                thread_id_disp[:36] + "..." if len(thread_id_disp) > 36 else thread_id_disp,
                str(row["message_blob_count"]),
                format_size(row["total_blob_bytes"])
            )

        console.print(table)
        console.print()

        # Select thread
        try:
            thread_idx = IntPrompt.ask("Select thread number to truncate", default=1) - 1
            if thread_idx < 0 or thread_idx >= len(threads):
                console.print("[red]Invalid thread number.[/red]")
                return
        except ValueError:
            console.print("[red]Invalid input.[/red]")
            return

        thread_id = threads[thread_idx]["thread_id"]
        thread_info = threads[thread_idx]

    console.print(f"\n[cyan]Thread: {thread_id}[/cyan]")
    console.print(f"Message blobs: {thread_info['message_blob_count']}")
    console.print(f"Total size: {format_size(thread_info['total_blob_bytes'])}")

    # Get all message blobs for this thread
    message_blobs = run_psql_query(conn_str, """
        SELECT version, blob, LENGTH(blob) as blob_size
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages'
        ORDER BY version
    """, (thread_id,))

    if not message_blobs:
        console.print("[yellow]No message blobs found for this thread.[/yellow]")
        return

    # Deserialize first blob to get message count
    serde = JsonPlusSerializer()
    first_blob = message_blobs[0]["blob"]
    try:
        messages = ormsgpack.unpackb(first_blob, ext_hook=serde._unpack_ext_hook, option=ormsgpack.OPT_NON_STR_KEYS)
        total_messages = len(messages)
    except Exception as e:
        console.print(f"[red]Error deserializing messages: {e}[/red]")
        return

    console.print(f"Current messages per blob: {total_messages}")

    # Ask how many messages to keep
    keep_count = args.keep
    if not keep_count:
        try:
            keep_count = IntPrompt.ask(
                "How many most recent messages to keep?",
                default=min(3, total_messages)
            )
            if keep_count < 1:
                console.print("[red]Must keep at least 1 message.[/red]")
                return
            if keep_count >= total_messages:
                console.print("[yellow]Nothing to truncate (keep count >= total messages).[/yellow]")
                return
        except ValueError:
            console.print("[red]Invalid input.[/red]")
            return

    # Preview
    delete_count = total_messages - keep_count
    console.print(f"\n[yellow]Will truncate to last {keep_count} messages (removing {delete_count} oldest).[/yellow]")

    # Show preview of kept messages
    console.print("\n[dim]Kept messages preview:[/dim]")
    for i, msg in enumerate(messages[-keep_count:], 1):
        content_preview = str(getattr(msg, 'content', str(msg)))[:60]
        msg_type = msg.__class__.__name__
        console.print(f"  {i}. {msg_type}: {content_preview}...")

    confirm = Prompt.ask("\nProceed?", choices=["y", "n"], default="n")
    if confirm != "y":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Perform truncation
    updated_count = 0
    bytes_saved = 0

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            for row in message_blobs:
                version = row["version"]
                old_blob = row["blob"]
                old_size = row["blob_size"]

                try:
                    # Deserialize
                    msgs = ormsgpack.unpackb(old_blob, ext_hook=serde._unpack_ext_hook, option=ormsgpack.OPT_NON_STR_KEYS)

                    # Truncate
                    truncated = msgs[-keep_count:] if len(msgs) > keep_count else msgs

                    # Reserialize
                    new_blob = ormsgpack.packb(truncated, default=_msgpack_default)
                    new_size = len(new_blob)

                    # Update database
                    cur.execute("""
                        UPDATE checkpoint_blobs
                        SET blob = %s
                        WHERE thread_id = %s AND channel = 'messages' AND version = %s
                    """, (new_blob, thread_id, version))

                    updated_count += 1
                    bytes_saved += (old_size - new_size)

                except Exception as e:
                    console.print(f"[yellow]Warning: Failed to truncate version {version}: {e}[/yellow]")
                    continue

        conn.commit()

    # Vacuum to reclaim space
    if bytes_saved > 0:
        run_psql_vacuum(conn_str)

    console.print(f"\n[green]Truncation complete![/green]")
    console.print(f"  Updated blobs: {updated_count}")
    console.print(f"  Bytes saved: {format_size(bytes_saved)}")
    console.print(f"  Messages per blob: {keep_count}")


# ---------------------------------------------------------------------------
# View Messages Command - View message history in a thread
# ---------------------------------------------------------------------------

def cmd_view_messages(args: argparse.Namespace) -> None:
    """View message history in a thread with index numbers."""
    if not LANGGRAPH_AVAILABLE:
        console.print("[red]Error: LangGraph not available. Cannot view messages.[/red]")
        console.print("[dim]Install with: uv pip install langgraph-checkpoint[/dim]")
        sys.exit(1)

    conn_str = get_postgres_connection_string()

    # Get threads with message blobs
    threads = run_psql_query(conn_str, """
        SELECT
            cb.thread_id,
            COUNT(*) as message_blob_count,
            SUM(LENGTH(cb.blob)) as total_blob_bytes
        FROM checkpoint_blobs cb
        WHERE cb.channel = 'messages'
        GROUP BY cb.thread_id
        ORDER BY SUM(LENGTH(cb.blob)) DESC
    """)

    if not threads:
        console.print("[yellow]No threads with message blobs found in database.[/yellow]")
        return

    # If thread_id provided via args, use it; otherwise show interactive selection
    thread_id = args.thread
    if thread_id:
        matching = [t for t in threads if t["thread_id"] == thread_id]
        if not matching:
            console.print(f"[red]Thread {thread_id} not found or has no messages.[/red]")
            return
    else:
        # Display threads
        console.print("\n[bold cyan]Select Thread to View Messages[/bold cyan]\n")

        table = Table()
        table.add_column("#", justify="right", style="dim")
        table.add_column("Thread ID", style="cyan")
        table.add_column("Blob Count", justify="right")
        table.add_column("Total Size", justify="right")

        for i, row in enumerate(threads, 1):
            thread_id_disp = row["thread_id"]
            table.add_row(
                str(i),
                thread_id_disp[:36] + "..." if len(thread_id_disp) > 36 else thread_id_disp,
                str(row["message_blob_count"]),
                format_size(row["total_blob_bytes"])
            )

        console.print(table)
        console.print()

        # Select thread
        try:
            thread_idx = IntPrompt.ask("Select thread number to view", default=1) - 1
            if thread_idx < 0 or thread_idx >= len(threads):
                console.print("[red]Invalid thread number.[/red]")
                return
        except ValueError:
            console.print("[red]Invalid input.[/red]")
            return

        thread_id = threads[thread_idx]["thread_id"]

    # Get first message blob for this thread
    message_blob = run_psql_query(conn_str, """
        SELECT version, blob
        FROM checkpoint_blobs
        WHERE thread_id = %s AND channel = 'messages'
        ORDER BY version
        LIMIT 1
    """, (thread_id,))

    if not message_blob:
        console.print("[yellow]No message blobs found for this thread.[/yellow]")
        return

    # Deserialize messages
    serde = JsonPlusSerializer()
    blob = message_blob[0]["blob"]
    try:
        messages = ormsgpack.unpackb(blob, ext_hook=serde._unpack_ext_hook, option=ormsgpack.OPT_NON_STR_KEYS)
    except Exception as e:
        console.print(f"[red]Error deserializing messages: {e}[/red]")
        return

    total = len(messages)
    console.print(f"\n[cyan]Thread: {thread_id}[/cyan]")
    console.print(f"[dim]Total messages: {total}\n[/dim]")

    # Display messages with index
    for i, msg in enumerate(messages, 1):
        msg_type = msg.__class__.__name__
        content = getattr(msg, 'content', str(msg))

        # Format based on message type
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            content_preview = f"[Tool Calls: {len(msg.tool_calls)} calls]"
        elif hasattr(msg, 'tool_call_id') and msg.tool_call_id:
            content_preview = f"[Tool Call ID: {msg.tool_call_id}] " + str(content)[:80]
        elif hasattr(msg, 'name') and msg.name:
            content_preview = f"[Name: {msg.name}] " + str(content)[:80]
        else:
            content_preview = str(content)[:200]

        # Show index (newest messages have higher numbers)
        console.print(f"[{i:3d}/{total}] [bold]{msg_type}[/bold]")
        console.print(f"      {content_preview}")
        console.print()

    console.print(f"\n[dim]Tip: To truncate to last N messages, run:[/dim]")
    console.print(f"  make db-truncate --thread {thread_id} --keep <N>")
    console.print(f"[dim]  (keeps messages {total}-{total} down to {total}-<N>+1)[/dim]")


def parse_selection(selection: str, max_count: int) -> list[int]:
    """Parse selection string like '1,3,5' or '1-5' into list of 0-based indices."""
    indices = set()
    parts = selection.replace(" ", "").split(",")

    for part in parts:
        if "-" in part:
            start, end = part.split("-")
            start, end = int(start), int(end)
            if start < 1 or end > max_count or start > end:
                raise ValueError(f"Invalid range: {part}")
            indices.update(range(start - 1, end))
        else:
            idx = int(part)
            if idx < 1 or idx > max_count:
                raise ValueError(f"Invalid index: {idx}")
            indices.add(idx - 1)

    return sorted(indices)


# ---------------------------------------------------------------------------
# Backup Command
# ---------------------------------------------------------------------------

def cmd_backup(args: argparse.Namespace) -> None:
    """Create full backup of checkpoint data and project files."""
    conn_str = get_postgres_connection_string()
    deer_flow_home = get_deer_flow_home()
    db_name = conn_str.split("/")[-1].split("?")[0]

    # Find project root (where config.yaml is located)
    project_root = Path.cwd()
    if not (project_root / "config.yaml").exists():
        # We might be in backend/, go up one level
        if (project_root / "../config.yaml").exists():
            project_root = project_root.parent

    # Create backup directory (always in project root)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        backup_dir = Path(args.output)
    else:
        backup_dir = project_root / "backups" / f"deerflow_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold cyan]Creating backup in {backup_dir}[/bold cyan]\n")

    # 1. Dump PostgreSQL database
    console.print("[dim]Dumping PostgreSQL database...[/dim]")
    pg_dump_file = backup_dir / "checkpoints.sql"

    # Extract connection details from connection string
    match = re.match(r"postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", conn_str)
    if not match:
        console.print("[red]Error: Could not parse connection string[/red]")
        sys.exit(1)

    user, password, host, port, dbname = match.groups()

    # Use pg_dump via docker exec
    # Pass PGPASSWORD through environment to avoid exposing in process list
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    result = subprocess.run([
        "docker", "exec", "-e", "PGPASSWORD",
        POSTGRES_CONTAINER,
        "pg_dump", "-U", user, "-d", dbname, "--clean", "--if-exists"
    ], capture_output=True, text=True, env=env)

    if result.returncode != 0:
        console.print(f"[red]pg_dump failed: {result.stderr}[/red]")
        sys.exit(1)

    with open(pg_dump_file, "w") as f:
        f.write(result.stdout)

    console.print(f"[green]  Database dump: {pg_dump_file} ({pg_dump_file.stat().st_size} bytes)[/green]")

    # 2. Backup memory.json
    memory_file = deer_flow_home / "memory.json"
    if memory_file.exists():
        backup_memory = backup_dir / "memory.json"
        shutil.copy2(memory_file, backup_memory)
        console.print(f"[green]  Memory backup: {backup_memory}[/green]")
    else:
        console.print("[dim]  No memory.json found, skipping[/dim]")

    # 3. Backup threads directory
    threads_dir = deer_flow_home / "threads"
    if threads_dir.exists():
        backup_threads = backup_dir / "threads"
        try:
            # Use a custom copy function to handle broken symlinks
            def ignore_broken_links(directory, files):
                ignored = []
                for f in files:
                    path = Path(directory) / f
                    if path.is_symlink() and not path.exists():
                        ignored.append(f)
                return ignored
            shutil.copytree(threads_dir, backup_threads, ignore=ignore_broken_links)
            console.print(f"[green]  Threads backup: {backup_threads}[/green]")
        except Exception as e:
            console.print(f"[yellow]  Warning: Could not fully backup threads: {e}[/yellow]")
            console.print("[dim]  Some files may have been skipped due to broken symlinks or permissions[/dim]")
    else:
        console.print("[dim]  No threads directory found, skipping[/dim]")

    # 4. Create manifest
    manifest = {
        "timestamp": timestamp,
        "database": dbname,
        "postgres_container": POSTGRES_CONTAINER,
        "files": {
            "checkpoints.sql": "PostgreSQL dump",
            "memory.json": "Memory data (if exists)",
            "threads/": "Thread user data (if exists)"
        },
        "restore_instructions": [
            f"1. Restore database: docker exec -i {POSTGRES_CONTAINER} psql -U deerflow -d deerflow < checkpoints.sql",
            "2. Restore memory: cp memory.json <DEER_FLOW_HOME>/",
            "3. Restore threads: cp -r threads/ <DEER_FLOW_HOME>/"
        ]
    }

    manifest_file = backup_dir / "manifest.json"
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    console.print(f"[green]  Manifest: {manifest_file}[/green]")

    # Summary
    total_size = sum(f.stat().st_size for f in backup_dir.rglob("*") if f.is_file())
    console.print(f"\n[bold green]Backup complete![/bold green]")
    console.print(f"  Location: {backup_dir}")
    console.print(f"  Total size: {total_size / 1024 / 1024:.2f} MB")


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeerFlow PostgreSQL database maintenance tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Stats command
    subparsers.add_parser("stats", help="Show database statistics")

    # Clean command
    subparsers.add_parser("clean", help="Interactively clean up old threads")

    # Prune command
    subparsers.add_parser("prune", help="Prune old checkpoints from a thread")

    # Truncate command
    truncate_parser = subparsers.add_parser("truncate", help="Truncate message history in a thread")
    truncate_parser.add_argument("--thread", "-t", help="Thread ID to truncate (interactive if not provided)")
    truncate_parser.add_argument("--keep", "-k", type=int, help="Number of recent messages to keep (interactive if not provided)")

    # View messages command
    view_parser = subparsers.add_parser("view-messages", help="View message history in a thread")
    view_parser.add_argument("--thread", "-t", help="Thread ID to view (interactive if not provided)")

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create full backup")
    backup_parser.add_argument("--output", "-o", help="Output directory (default: backups/deerflow_TIMESTAMP)")

    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "clean":
        cmd_clean(args)
    elif args.command == "prune":
        cmd_prune(args)
    elif args.command == "truncate":
        cmd_truncate(args)
    elif args.command == "view-messages":
        cmd_view_messages(args)
    elif args.command == "backup":
        cmd_backup(args)


if __name__ == "__main__":
    main()