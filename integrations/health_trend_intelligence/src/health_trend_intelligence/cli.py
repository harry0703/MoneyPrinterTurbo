import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Health trend intelligence command line interface."""


@app.command()
def version() -> None:
    typer.echo("health-trend-intelligence 0.1.0")
