"""Administrative command-line interface."""

from __future__ import annotations

from typing import Optional

import click
import structlog
import uvicorn
from aioredis import Redis
from safir.asyncio import run_with_asyncio
from safir.database import create_database_engine, initialize_database

from .config import config
from .dbschema import Base
from .storage.nbhtmlcache import NbHtmlCacheStore


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
@click.option(
    "--reset", is_flag=True, help="Delete all existing database data."
)
@run_with_asyncio
async def init(reset: bool) -> None:
    """Initialize the database storage."""
    logger = structlog.get_logger(config.logger_name)
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(
        engine, logger, schema=Base.metadata, reset=reset
    )
    await engine.dispose()


@main.command("reset-html")
@run_with_asyncio
async def reset_html() -> None:
    """Reset the Redis-based HTML result cache."""
    redis = Redis.from_url(config.redis_url, password=None)
    try:
        html_store = NbHtmlCacheStore(redis)
        record_count = await html_store.delete_all()
        if record_count > 0:
            click.echo(f"Deleted {record_count} HTML records")
        else:
            click.echo("No HTML records to delete")
    except Exception as e:
        click.echo(str(e))
    finally:
        await redis.close()
        await redis.connection_pool.disconnect()
