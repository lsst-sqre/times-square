"""Administrative command-line interface."""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import TYPE_CHECKING

import click
import uvicorn

from .config import config
from .database import initialize_database

if TYPE_CHECKING:
    from typing import Any, Awaitable, Callable, Optional, TypeVar

    T = TypeVar("T")


def coroutine(f: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    @wraps(f)
    def async_wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(f(*args, **kwargs))

    return async_wrapper


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(message="%(version)s")
def main() -> None:
    """times-square.

    Administrative command-line interface for Times Square.
    """
    pass


@main.command()
@click.argument("topic", default=None, required=False, nargs=1)
@click.pass_context
def help(ctx: click.Context, topic: Optional[str]) -> None:
    """Show help for any command."""
    # The help command implementation is taken from
    # https://www.burgundywall.com/post/having-click-help-subcommand
    if topic:
        if topic in main.commands:
            click.echo(main.commands[topic].get_help(ctx))
        else:
            raise click.UsageError(f"Unknown help topic {topic}", ctx)
    else:
        assert ctx.parent
        click.echo(ctx.parent.get_help())


@main.command()
@click.option(
    "--port", default=8080, type=int, help="Port to run the application on."
)
def develop(port: int) -> None:
    """Run the application with live reloading (for development only)."""
    uvicorn.run(
        "timessquare.main:app", port=port, reload=True, reload_dirs=["src"]
    )


@main.command()
@coroutine
async def init() -> None:
    """Initialize the database storage."""
    await initialize_database(config)
