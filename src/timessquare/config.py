"""Configuration definition."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from arq.connections import RedisSettings
from pydantic import Field, HttpUrl, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings
from safir.arq import ArqMode
from safir.logging import LogLevel, Profile
from safir.pydantic import EnvAsyncPostgresDsn, EnvRedisDsn

__all__ = ["Config", "LogLevel", "Profile"]


class Config(BaseSettings):
    """Configuration for Times Square."""

    name: Annotated[
        str,
        Field(
            alias="SAFIR_NAME",
            description="The name of the application.",
        ),
    ] = "times-square"

    profile: Annotated[
        Profile,
        Field(
            alias="SAFIR_PROFILE",
            description=(
                "The application's runtime profile to configure logging."
            ),
        ),
    ] = Profile.production

    log_level: LogLevel = Field(
        LogLevel.INFO,
        alias="SAFIR_LOG_LEVEL",
        description="The application's logging level.",
    )

    logger_name: Annotated[
        str,
        Field(
            description=(
                "The name of the logger, which is also the root Python "
                "namespace of the application."
            )
        ),
    ] = "timessquare"

    environment_url: Annotated[
        HttpUrl,
        Field(
            alias="TS_ENVIRONMENT_URL",
            description=(
                "The base URL of the Rubin Science Platform environment."
                "\n\n"
                "This is used for creating URLs to other RSP services."
            ),
        ),
    ]

    environment_name: Annotated[
        str,
        Field(
            alias="TS_ENVIRONMENT_NAME",
            description=(
                "The Phalanx name of the Rubin Science Platform environment."
            ),
        ),
    ]

    gafaelfawr_token: Annotated[
        SecretStr,
        Field(
            alias="TS_GAFAELFAWR_TOKEN",
            description=(
                "This token is used to make requests to other RSP services, "
                "such as Noteburst."
            ),
        ),
    ]

    path_prefix: Annotated[
        str,
        Field(
            alias="TS_PATH_PREFIX",
            description=(
                "The URL prefix where the application's externally-accessible "
                "endpoints are hosted."
            ),
        ),
    ] = "/times-square"

    database_url: EnvAsyncPostgresDsn = Field(
        alias="TS_DATABASE_URL",
        description="The URL for the PostgreSQL database instance.",
    )

    database_password: Annotated[
        SecretStr,
        Field(
            alias="TS_DATABASE_PASSWORD",
            description="The password for the PostgreSQL database instance.",
        ),
    ]

    redis_url: EnvRedisDsn = Field(
        alias="TS_REDIS_URL",
        description=("URL for the redis instance, used by the worker queue."),
    )

    github_app_id: Annotated[
        int | None,
        Field(
            alias="TS_GITHUB_APP_ID",
            description=(
                "The GitHub App ID, as determined by GitHub when setting up a "
                "GitHub App."
            ),
        ),
    ] = None

    github_webhook_secret: Annotated[
        str,
        Field(
            alias="TS_GITHUB_WEBHOOK_SECRET",
            description=(
                "The GitHub app's webhook secret, as set when the App was "
                "created. See "
                "https://docs.github.com/en/developers/webhooks-and-events/"
                "webhooks/securing-your-webhooks"
            ),
        ),
    ]

    github_app_private_key: Annotated[
        str,
        Field(
            alias="TS_GITHUB_APP_PRIVATE_KEY",
            description=(
                "The GitHub app private key. See https://docs.github.com/en/"
                "developers/apps/building-github-apps/authenticating-with-"
                "github-apps#generating-a-private-key"
            ),
        ),
    ]

    enable_github_app: Annotated[
        bool,
        Field(
            alias="TS_ENABLE_GITHUB_APP",
            description=(
                "Toggle to enable GitHub App functionality."
                "\n\n"
                "If configurations required to function as a GitHub App are "
                "not set, this configuration is automatically toggled to "
                "False. It can also also be manually toggled to False if "
                "necessary."
            ),
        ),
    ] = True

    github_orgs: Annotated[
        str,
        Field(
            alias="TS_GITHUB_ORGS",
            description=(
                "A comma-separated list of GitHub organizations that can sync"
                "with Times Square."
            ),
        ),
    ] = "lsst-sqre"

    github_checkrun_timeout: Annotated[
        int,
        Field(
            gt=0,
            alias="TS_CHECK_RUN_TIMEOUT",
            description=(
                "The maximum time in seconds to wait for a check run to "
                "complete."
            ),
        ),
    ] = 600

    default_execution_timeout: Annotated[
        int,
        Field(
            gt=0,
            alias="TS_DEFAULT_EXECUTION_TIMEOUT",
            description=(
                "The default execution timeout for notebook execution jobs, "
                "in seconds."
            ),
        ),
    ] = 60

    redis_queue_url: EnvRedisDsn = Field(
        alias="TS_REDIS_QUEUE_URL",
        description=("URL for the redis instance, used by the worker queue."),
    )

    queue_name: Annotated[
        str,
        Field(
            alias="TS_REDIS_QUEUE_NAME",
            description=(
                "Name of the arq queue that the worker processes from."
            ),
        ),
    ] = "arq:queue"

    arq_mode: Annotated[
        ArqMode,
        Field(
            ArqMode.production,
            alias="TS_ARQ_MODE",
            description=(
                "The Arq mode to use for the worker (production or testing)."
            ),
        ),
    ]

    slack_webhook_url: Annotated[
        HttpUrl | None,
        Field(
            alias="TS_SLACK_WEBHOOK_URL",
            description=(
                "Webhook URL for sending error messages to a Slack channel."
            ),
        ),
    ] = None

    sentry_dsn: Annotated[
        str | None,
        Field(
            alias="TS_SENTRY_DSN",
            description="DSN for sending events to Sentry.",
        ),
    ] = None

    sentry_traces_sample_rate: Annotated[
        float,
        Field(
            alias="TS_SENTRY_TRACES_SAMPLE_RATE",
            description=(
                "The percentage of transactions to send to Sentry, expressed "
                "as a float between 0 and 1. 0 means send no traces, 1 means "
                "send every trace."
            ),
            ge=0,
            le=1,
        ),
    ] = 0

    @field_validator("path_prefix")
    @classmethod
    def validate_path_prefix(cls, v: str) -> str:
        # Handle empty path prefix (i.e. app is hosted on its own domain)
        if v == "":
            raise ValueError(
                "Times square does not yet support being hosted from "
                "the root path. Set a value for $TS_PATH_PREFIX."
            )

        # Remove any trailing / since individual paths operations add those.
        v = v.rstrip("/")

        # Add a / prefix if not present
        if not v.startswith("/"):
            v = "/" + v
        return v

    @field_validator(
        "github_webhook_secret",
        "github_app_private_key",
    )
    @classmethod
    def validate_none_secret(cls, v: SecretStr | None) -> SecretStr | None:
        """Validate a SecretStr setting which may be "None" that is intended
        to be `None`.

        This is useful for secrets generated from 1Password or environment
        variables where the value cannot be null.
        """
        if v is None:
            return v
        elif isinstance(v, str):
            if v.strip().lower() == "none":
                return None
            else:
                return v
        else:
            raise ValueError(f"Value must be None or a string: {v!r}")

    @field_validator("enable_github_app")
    @classmethod
    def validate_github_app(cls, v: bool, info: ValidationInfo) -> bool:
        """Validate ``enable_github_app`` by ensuring that other GitHub
        configurations are also set.
        """
        if v is False:
            # Allow the GitHub app to be disabled regardless of other
            # configurations.
            return False

        return not (
            info.data.get("github_app_private_key") == ""
            or info.data.get("github_webhook_secret") == ""
            or info.data.get("github_app_id") is None
        )

    @property
    def arq_redis_settings(self) -> RedisSettings:
        """Create a Redis settings instance for arq."""
        url_parts = urlparse(str(self.redis_queue_url))
        return RedisSettings(
            host=url_parts.hostname or "localhost",
            port=url_parts.port or 6379,
            database=int(url_parts.path.lstrip("/")) if url_parts.path else 0,
        )

    @property
    def accepted_github_orgs(self) -> list[str]:
        """Get the list of allowed GitHub organizations.

        This is based on the `github_orgs` configuration, which is a
        comma-separated list of GitHub organizations.
        """
        return [v.strip() for v in self.github_orgs.split(",")]


config = Config()
"""Configuration for Times Square."""
