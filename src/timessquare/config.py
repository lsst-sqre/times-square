"""Configuration definition."""

from __future__ import annotations

from enum import Enum

from pydantic import (
    AnyUrl,
    BaseSettings,
    Field,
    HttpUrl,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    validator,
)

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

    logger_name: str = Field("timessquare", env="SAFIR_LOGGER")

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

    @property
    def asyncpg_database_url(self) -> str:
        """The ``postgresql+asyncpg`` database URL that includes the password,
        based on the `database_url` and `database_password` attributes.
        """
        return str(
            AnyUrl.build(
                scheme="postgresql+asyncpg",
                user=self.database_url.user,
                host=self.database_url.host,
                port=self.database_url.port,
                path=self.database_url.path,
                password=self.database_password.get_secret_value(),
            )
        )


config = Config()
"""Configuration for Times Square."""
