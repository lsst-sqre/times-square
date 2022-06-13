"""Configuration definition."""


from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from arq.connections import RedisSettings
from pydantic import (
    BaseSettings,
    Field,
    HttpUrl,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    validator,
)
from safir.arq import ArqMode

__all__ = ["Config", "Profile", "LogLevel"]


class Profile(str, Enum):

    production = "production"

    development = "development"


class LogLevel(str, Enum):

    DEBUG = "DEBUG"

    INFO = "INFO"

    WARNING = "WARNING"

    ERROR = "ERROR"

    CRITICAL = "CRITICAL"


class Config(BaseSettings):

    name: str = Field("times-square", env="SAFIR_NAME")

    profile: Profile = Field(Profile.production, env="SAFIR_PROFILE")

    log_level: LogLevel = Field(LogLevel.INFO, env="SAFIR_LOG_LEVEL")

    logger_name: str = "timessquare"
    """The name of the logger, which is also the root Python namespace
    of the application.
    """

    environment_url: HttpUrl = Field(env="TS_ENVIRONMENT_URL")
    """The base URL of the Rubin Science Platform environment.

    This is used for creating URLs to other RSP services.
    """

    gafaelfawr_token: SecretStr = Field(env="TS_GAFAELFAWR_TOKEN")
    """This token is used to make requests to other RSP services, such as
    Noteburst.
    """

    path_prefix: str = Field("/times-square", env="TS_PATH_PREFIX")
    """The URL prefix where the application's externally-accessible endpoints
    are hosted.
    """

    database_url: PostgresDsn = Field(..., env="TS_DATABASE_URL")

    database_password: SecretStr = Field(..., env="TS_DATABASE_PASSWORD")

    redis_url: RedisDsn = Field("redis://localhost:6379/0", env="TS_REDIS_URL")
    """URL for the redis instance, used by the worker queue."""

    github_app_id: Optional[str] = Field(None, env="TS_GITHUB_APP_ID")
    """The GitHub App ID, as determined by GitHub when setting up a GitHub
    App.
    """

    github_webhook_secret: Optional[SecretStr] = Field(
        None, env="TS_GITHUB_WEBHOOK_SECRET"
    )
    """The GitHub app's webhook secret, as set when the App was created. See
    https://docs.github.com/en/developers/webhooks-and-events/webhooks/securing-your-webhooks
    """

    github_app_private_key: Optional[SecretStr] = Field(
        None, env="TS_GITHUB_APP_PRIVATE_KEY"
    )
    """The GitHub app private key. See
    https://docs.github.com/en/developers/apps/building-github-apps/authenticating-with-github-apps#generating-a-private-key
    """

    enable_github_app: bool = Field(True, env="TS_ENABLE_GITHUB_APP")
    """Toggle to enable GitHub App functionality.

    If configurations required to function as a GitHub App are not set,
    this configuration is automatically toggled to False. It also also be
    manually toggled to False if necessary.
    """

    redis_queue_url: RedisDsn = Field(
        "redis://localhost:6379/1", env="TS_REDIS_QUEUE_URL"
    )

    queue_name: str = Field("arq:queue", env="TS_REDIS_QUEUE_NAME")
    """Name of the arq queue that the worker processes from."""

    arq_mode: ArqMode = Field(ArqMode.production, env="TS_ARQ_MODE")

    @validator("path_prefix")
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

    @validator("github_webhook_secret", "github_app_private_key", pre=True)
    def validate_none_secret(
        cls, v: Optional[SecretStr]
    ) -> Optional[SecretStr]:
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

    @validator("enable_github_app")
    def validate_github_app(cls, v: bool, values: Mapping[str, Any]) -> bool:
        """Validate ``enable_github_app`` by ensuring that other GitHub
        configurations are also set.
        """
        if v is False:
            # Allow the GitHub app to be disabled regardless of other
            # configurations.
            return False

        if (
            (values.get("github_app_private_key") is None)
            or (values.get("github_webhook_secret") is None)
            or (values.get("github_app_id") is None)
        ):
            return False

        return True

    @property
    def arq_redis_settings(self) -> RedisSettings:
        """Create a Redis settings instance for arq."""
        url_parts = urlparse(self.redis_queue_url)
        redis_settings = RedisSettings(
            host=url_parts.hostname or "localhost",
            port=url_parts.port or 6379,
            database=int(url_parts.path.lstrip("/")) if url_parts.path else 0,
        )
        return redis_settings


config = Config()
"""Configuration for Times Square."""
