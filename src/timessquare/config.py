"""Configuration definition."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseSettings, Field, HttpUrl, validator

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

    name: str = Field("timessquare", env="SAFIR_NAME")

    profile: Profile = Field(Profile.production, env="SAFIR_PROFILE")

    log_level: LogLevel = Field(LogLevel.INFO, env="SAFIR_LOG_LEVEL")

    logger_name: str = Field("timessquare", env="SAFIR_LOGGER")

    environment_url: HttpUrl = Field(env="TS_ENVIRONMENT_URL")
    """The base URL of the Rubin Science Platform environment.

    This is used for creating URLs to other RSP services.
    """

    path_prefix: str = Field("/times-square", env="TS_PATH_PREFIX")
    """The URL prefix where the application's externally-accessible endpoints
    are hosted.
    """

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


config = Config()
"""Configuration for Times Square."""
