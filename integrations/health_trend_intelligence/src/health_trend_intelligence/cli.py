from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from typer._click.exceptions import NoArgsIsHelpError, UsageError

from .batch import BatchInputError, build_retention_report, register_batch, verify_raw_batch
from .canonical import load_unique_json
from .storage import DataLayout, PathSafetyError, assert_safe_regular_file

# Operational commands have one failure contract. Typer delegates argument
# errors to Click before command callbacks run, so align that early path too.
UsageError.exit_code = 3
NoArgsIsHelpError.exit_code = 3

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Health trend intelligence command line interface."""


@app.command()
def version() -> None:
    typer.echo("health-trend-intelligence 0.1.0")


T = TypeVar("T")


def _guarded(action: Callable[[], T]) -> T:
    try:
        return action()
    except (BatchInputError, FileExistsError, OSError, PathSafetyError, ValueError):
        typer.echo("invalid input or state", err=True)
        raise typer.Exit(code=3) from None


def _load_json(path: Path) -> Any:
    assert_safe_regular_file(path)
    return load_unique_json(path.read_bytes())


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


@app.command("init")
def initialize(root: Annotated[Path, typer.Option()]) -> None:
    def action() -> None:
        DataLayout.from_root(root).initialize()

    _guarded(action)
    typer.echo("initialized")


@app.command()
def register(
    root: Annotated[Path, typer.Option()],
    batch_id: Annotated[str, typer.Option()],
    queries: Annotated[Path, typer.Option()],
    source: Annotated[Path, typer.Option()],
    snapshot_at: Annotated[str, typer.Option()],
) -> None:
    def action() -> Any:
        return register_batch(
            DataLayout.from_root(root),
            batch_id,
            _load_json(queries),
            _load_json(source),
            _parse_datetime(snapshot_at),
        )

    manifest = _guarded(action)
    typer.echo(f"registered {manifest.batch_id} sources={len(manifest.sources)}")


@app.command("verify-raw")
def verify_raw(
    root: Annotated[Path, typer.Option()], batch_id: Annotated[str, typer.Option()]
) -> None:
    manifest = _guarded(lambda: verify_raw_batch(DataLayout.from_root(root), batch_id))
    typer.echo(f"verified {manifest.batch_id} sources={len(manifest.sources)}")


@app.command("retention-report")
def retention_report(
    root: Annotated[Path, typer.Option()], as_of: Annotated[str, typer.Option()]
) -> None:
    entries = _guarded(
        lambda: build_retention_report(DataLayout.from_root(root), _parse_datetime(as_of))
    )
    for entry in entries:
        typer.echo(
            f"{entry.batch_id} age_days={entry.age_days} "
            f"eligible_for_manual_deletion={str(entry.eligible_for_manual_deletion).lower()}"
        )
