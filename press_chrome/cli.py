"""chtabs — Press Chrome CLI."""

from __future__ import annotations

import sys
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .agent_ux import (
    EXIT_API,
    EXIT_AUTH,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    agent_output_options,
    compact_rows,
    die,
    emit_csv,
    emit_json,
    note_showing,
    resolve_format,
    select_fields,
)
from . import client
from .config import DEFAULT_PORT, init_config, read_config, read_token, ws_url
from .daemon import main_serve

console = Console(stderr=True)


def _emit_rows(
    rows: list[dict],
    *,
    fmt: str,
    compact: bool,
    select: str | None,
    quiet: bool,
    as_csv: bool,
    compact_fields: list[str],
    noun: str,
) -> None:
    data: Any = rows
    if compact:
        data = compact_rows(rows, compact_fields)
    data = select_fields(data, select)
    if as_csv:
        fields = compact_fields if compact and not select else (None if not rows else list((data[0] if isinstance(data, list) and data else rows[0]).keys()))
        emit_csv(data if isinstance(data, list) else [data], fields)
        return
    fmt = resolve_format(fmt)
    if fmt == "json":
        emit_json(data)
    else:
        if not rows:
            click.echo("(none)")
            return
        table = Table(show_header=True, header_style="bold")
        keys = compact_fields if compact else list(rows[0].keys())
        if select:
            keys = [k.strip() for k in select.split(",") if k.strip()]
        for k in keys:
            table.add_column(k)
        for row in (data if isinstance(data, list) else [data]):
            table.add_row(*[str(row.get(k, ""))[:80] for k in keys])
        Console().print(table)
    note_showing(len(rows), quiet=quiet, noun=noun)


def _handle_client_error(exc: client.ClientError) -> None:
    die(str(exc), code=exc.code)


@click.group()
@click.version_option(__version__, prog_name="chtabs")
def main() -> None:
    """Press Chrome — read-only Chrome tabs for agents (chtabs)."""


@main.command()
@click.option("--force", is_flag=True, help="Rotate token even if one exists.")
def init(force: bool) -> None:
    """Create ~/.press-chrome/{token,config.json} (mode 0600)."""
    token, cfg = init_config(force=force)
    click.echo("Initialized Press Chrome config.")
    click.echo(f"  config: ~/.press-chrome/config.json")
    click.echo(f"  token:  ~/.press-chrome/token")
    click.echo(f"  host:   {cfg.get('host')}:{cfg.get('port')}")
    click.echo(f"  trust:  {cfg.get('trust')}")
    click.echo("")
    click.echo("Paste this token into the extension Options page:")
    click.echo(token)
    click.echo("")
    click.echo(f"Extension WebSocket URL: {ws_url(cfg)}")
    sys.exit(EXIT_OK)


@main.command()
@click.option("--host", default=None, help="Bind host (default 127.0.0.1).")
@click.option("--port", default=None, type=int, help=f"Bind port (default {DEFAULT_PORT}).")
def serve(host: str | None, port: int | None) -> None:
    """Run localhost bridge daemon (HTTP + extension WebSocket)."""
    if not read_token():
        die("No token. Run: chtabs init", code=EXIT_AUTH)
    main_serve(host=host, port=port)


@main.command()
@agent_output_options()
def status(fmt: str, compact: bool, select: str | None, quiet: bool, as_csv: bool) -> None:
    """Daemon up? Extension connected? Trust mode?"""
    try:
        data = client.status()
    except client.ClientError as exc:
        _handle_client_error(exc)
    fmt = resolve_format(fmt)
    data = select_fields(data, select)
    if as_csv:
        emit_csv([data] if isinstance(data, dict) else data)
    elif fmt == "json" or not sys.stdout.isatty():
        emit_json(data)
    else:
        for k, v in (data if isinstance(data, dict) else {}).items():
            click.echo(f"{k}: {v}")
    sys.exit(EXIT_OK if (isinstance(data, dict) and data.get("ok")) else EXIT_API)


@main.command("list")
@agent_output_options()
def list_tabs(fmt: str, compact: bool, select: str | None, quiet: bool, as_csv: bool) -> None:
    """List shared tabs (+ active under shared_plus_active)."""
    try:
        resp = client.rpc({"type": "list"})
    except client.ClientError as exc:
        _handle_client_error(exc)
    if not resp.get("ok", True) and resp.get("error"):
        die(resp["error"], code=int(resp.get("code") or EXIT_API))
    rows = resp.get("tabs") or []
    _emit_rows(
        rows,
        fmt=fmt,
        compact=compact,
        select=select,
        quiet=quiet,
        as_csv=as_csv,
        compact_fields=["id", "title", "url", "shared", "active"],
        noun="tabs",
    )
    sys.exit(EXIT_OK)


@main.command()
@click.argument("tab_id", type=int)
@agent_output_options()
def show(tab_id: int, fmt: str, compact: bool, select: str | None, quiet: bool, as_csv: bool) -> None:
    """Show metadata for one tab."""
    try:
        resp = client.rpc({"type": "show", "tabId": tab_id})
    except client.ClientError as exc:
        _handle_client_error(exc)
    if not resp.get("ok"):
        code = int(resp.get("code") or EXIT_NOT_FOUND)
        die(resp.get("error") or "not_found", code=code)
    tab = resp.get("tab") or resp
    data = select_fields(tab, select)
    fmt = resolve_format(fmt)
    if as_csv:
        emit_csv([data] if isinstance(data, dict) else data)
    elif fmt == "json" or not sys.stdout.isatty():
        emit_json(data)
    else:
        for k, v in (data if isinstance(data, dict) else {}).items():
            click.echo(f"{k}: {v}")
    sys.exit(EXIT_OK)


@main.command()
@click.argument("tab_id", type=int)
@agent_output_options(formats=("table", "json", "text"))
def read(tab_id: int, fmt: str, compact: bool, select: str | None, quiet: bool, as_csv: bool) -> None:
    """Read main text content of a shared/active tab."""
    try:
        resp = client.rpc({"type": "read", "tabId": tab_id})
    except client.ClientError as exc:
        _handle_client_error(exc)
    if not resp.get("ok"):
        die(resp.get("error") or "read_failed", code=int(resp.get("code") or EXIT_API))
    fmt = resolve_format(fmt, default="text")
    if fmt == "json" or as_csv:
        data = select_fields(
            {
                "id": resp.get("tabId", tab_id),
                "title": resp.get("title"),
                "url": resp.get("url"),
                "method": resp.get("method"),
                "text": resp.get("text"),
            },
            select,
        )
        if as_csv:
            emit_csv([data] if isinstance(data, dict) else data)
        else:
            emit_json(data)
    else:
        click.echo(resp.get("text") or "")
    sys.exit(EXIT_OK)


@main.command()
@agent_output_options(formats=("table", "json", "text"))
def active(fmt: str, compact: bool, select: str | None, quiet: bool, as_csv: bool) -> None:
    """Read the active tab (allowed under shared_plus_active)."""
    try:
        resp = client.rpc({"type": "active"})
    except client.ClientError as exc:
        _handle_client_error(exc)
    if not resp.get("ok"):
        die(resp.get("error") or "active_failed", code=int(resp.get("code") or EXIT_API))
    fmt = resolve_format(fmt, default="text")
    if fmt == "json" or as_csv:
        data = select_fields(
            {
                "id": resp.get("tabId"),
                "title": resp.get("title"),
                "url": resp.get("url"),
                "method": resp.get("method"),
                "text": resp.get("text"),
                "shared": resp.get("shared"),
            },
            select,
        )
        if as_csv:
            emit_csv([data] if isinstance(data, dict) else data)
        else:
            emit_json(data)
    else:
        meta = f"# {resp.get('title') or ''} ({resp.get('url') or ''})\n\n"
        if not quiet:
            click.echo(meta, err=True)
        click.echo(resp.get("text") or "")
    sys.exit(EXIT_OK)


@main.command()
@click.option("--limit", default=20, show_default=True, type=int, help="Max history items.")
@click.option("--query", "-Q", default="", help="Optional chrome.history text query.")
@agent_output_options()
def history(
    limit: int,
    query: str,
    fmt: str,
    compact: bool,
    select: str | None,
    quiet: bool,
    as_csv: bool,
) -> None:
    """Chrome history via extension (chrome.history permission)."""
    try:
        resp = client.rpc({"type": "history", "limit": limit, "query": query or ""})
    except client.ClientError as exc:
        _handle_client_error(exc)
    if not resp.get("ok"):
        die(resp.get("error") or "history_failed", code=int(resp.get("code") or EXIT_API))
    rows = resp.get("items") or []
    _emit_rows(
        rows,
        fmt=fmt,
        compact=compact,
        select=select,
        quiet=quiet,
        as_csv=as_csv,
        compact_fields=["id", "title", "url", "lastVisitTime", "visitCount"],
        noun="history items",
    )
    sys.exit(EXIT_OK)


@main.group()
def vision() -> None:
    """Read-only image questions and bounding boxes using TypeSafe."""


def _vision_command(kind):
    @click.argument("source_or_question")
    @click.argument("question", required=False)
    @click.option("--image", "image_path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--threshold", default=0.5, type=click.FloatRange(0, 1), show_default=True)
    @click.option("--save-screenshot", type=click.Path(dir_okay=False))
    @agent_output_options(default_format="text", formats=("text", "json", "table"))
    def command(source_or_question, question, image_path, threshold, save_screenshot,
                fmt, compact, select, quiet, as_csv):
        from .vision import analyze, VisionError
        import math
        if not math.isfinite(threshold):
            raise click.UsageError("Threshold must be finite and between 0 and 1")
        tab_id = None
        if image_path:
            if question is not None:
                raise click.UsageError("Use --image PATH QUESTION without a tab ID")
            question = source_or_question
        else:
            try:
                tab_id = int(source_or_question)
            except ValueError:
                raise click.UsageError("Provide a numeric tab ID or use --image PATH") from None
            if not question:
                raise click.UsageError("A question/target is required")
        if not question.strip():
            raise click.UsageError("A nonempty question/target is required")
        try:
            data = analyze(kind, question, tab_id=tab_id, image_path=image_path,
                           threshold=threshold, save_screenshot=save_screenshot)
        except client.ClientError as exc:
            _handle_client_error(exc)
        except (VisionError, OSError) as exc:
            die(str(exc))
        data = select_fields(data, select)
        if as_csv:
            emit_csv([data])
        elif resolve_format(fmt) == "json":
            emit_json(data)
        else:
            import json
            for key, value in data.items():
                click.echo(f"{key}: {json.dumps(value) if isinstance(value, (dict, list)) or value is None else value}")
    command.__doc__ = "Ask one yes/no image question." if kind == "ask" else "Find one target in an image."
    return command


vision.command("ask")(_vision_command("ask"))
vision.command("box")(_vision_command("box"))


@main.command("agent-help")
@agent_output_options(default_format="text", formats=("text", "json", "table"))
def agent_help(fmt, compact, select, quiet, as_csv):
    """Command reference for agents."""
    from .agent_ux import agent_help_entries
    _emit_rows(agent_help_entries(), fmt=fmt, compact=compact, select=select,
               quiet=quiet, as_csv=as_csv, compact_fields=["command", "description"], noun="commands")


if __name__ == "__main__":
    main()
