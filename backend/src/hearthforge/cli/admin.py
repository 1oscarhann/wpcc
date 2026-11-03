"""Admin CLI: `uv run hf --help`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from hearthforge.config.loader import ConfigError, load_config
from hearthforge.settings import get_settings

app = typer.Typer(no_args_is_help=True, help="Hearthforge admin tools")
config_app = typer.Typer(help="Config tools")
app.add_typer(config_app, name="config")


@config_app.command("check")
def config_check(
    path: Path = typer.Option(None, help="Config dir (default: HF_CONFIG_DIR or repo /config)"),
    strict: bool = typer.Option(True, help="Treat warnings as errors"),
) -> None:
    """Validate /config/*.yaml exactly like server startup does."""
    try:
        cfg = load_config(path or get_settings().config_dir, strict=strict)
    except ConfigError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    typer.secho(f"config OK  hash={cfg.hash}  {cfg.summary()}", fg=typer.colors.GREEN)


def run(coro) -> None:  # noqa: ANN001
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        sys.exit(130)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
