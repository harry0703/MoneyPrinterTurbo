from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from typer._click.exceptions import UsageError
from typer.core import TyperGroup

from .batch import BatchInputError, build_retention_report, register_batch, verify_raw_batch
from .canonical import load_unique_json
from .curation import CurationError, curate_batch, verify_curated_batch
from .privacy import PrivacyConfigurationError, PrivacyHasher
from .storage import DataLayout, PathSafetyError, assert_safe_regular_file


class SafeTyperGroup(TyperGroup):
    """Render every parser failure without reflecting untrusted argv."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        try:
            result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except UsageError:
            typer.echo("invalid command line", err=True)
            if standalone_mode:
                raise SystemExit(3) from None
            return 3
        if standalone_mode and isinstance(result, int):
            raise SystemExit(result)
        return result


app = typer.Typer(cls=SafeTyperGroup, no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Health trend intelligence command line interface."""


@app.command()
def version() -> None:
    typer.echo("health-trend-intelligence 0.1.0")


T = TypeVar("T")
_SAFE_BATCH_ID = re.compile(r"HTI-\d{8}-\d{2}\Z")


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


def _curation_guard(command: str, batch_id: str, action: Callable[[], T]) -> T:
    safe_batch_id = (
        batch_id
        if isinstance(batch_id, str) and _SAFE_BATCH_ID.fullmatch(batch_id)
        else "<invalid-batch>"
    )
    if safe_batch_id == "<invalid-batch>":
        typer.echo(f"{command} {safe_batch_id} invalid_input", err=True)
        raise typer.Exit(code=3) from None
    try:
        return action()
    except CurationError as error:
        reason_code = error.reason_code
    except (
        BatchInputError,
        FileExistsError,
        OSError,
        PathSafetyError,
        PrivacyConfigurationError,
        TypeError,
        ValueError,
    ):
        reason_code = "invalid_input"
    typer.echo(f"{command} {safe_batch_id} {reason_code}", err=True)
    raise typer.Exit(code=3) from None


@app.command("curate")
def curate(root: Annotated[Path, typer.Option()], batch_id: Annotated[str, typer.Option()]) -> None:
    _curation_guard(
        "curate",
        batch_id,
        lambda: curate_batch(
            DataLayout.from_root(root), batch_id, PrivacyHasher.from_environment()
        ),
    )
    typer.echo(f"curated {batch_id}")


@app.command("verify-curated")
def verify_curated(
    root: Annotated[Path, typer.Option()], batch_id: Annotated[str, typer.Option()]
) -> None:
    _curation_guard(
        "verify-curated",
        batch_id,
        lambda: verify_curated_batch(
            DataLayout.from_root(root), batch_id, PrivacyHasher.from_environment()
        ),
    )
    typer.echo(f"verified-curated {batch_id}")
