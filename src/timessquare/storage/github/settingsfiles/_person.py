from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from timessquare.domain.page import PersonModel

__all__ = ["SidecarPersonModel"]


class SidecarPersonModel(BaseModel):
    """A Pydantic model for a person's identity encoded in YAML."""

    name: Annotated[str | None, Field(title="Display name")] = None

    username: Annotated[str | None, Field(title="RSP username")] = None

    affiliation_name: Annotated[
        str | None,
        Field(
            title="Affiliation name",
            description="Display name of a person's main affiliation",
        ),
    ] = None

    email: Annotated[EmailStr | None, Field(title="Email")] = None

    slack_name: Annotated[str | None, Field(title="Slack username")] = None

    @model_validator(mode="after")
    def check_names(self) -> Self:
        """Either of name or username must be set."""
        if not (self.name or self.username):
            raise ValueError(
                "Either name or username must be set for a person"
            )
        return self

    def to_person_model(self) -> PersonModel:
        """Convert to the domain version of this object."""
        if self.name is not None:
            display_name = self.name
        elif self.username is not None:
            display_name = self.username
        else:
            # Shouldn't be possible thanks to the model validator
            raise RuntimeError("Cannot resolve a display name for person")

        return PersonModel(
            name=display_name,
            username=self.username,
            affiliation_name=self.affiliation_name,
            email=self.email,
            slack_name=self.slack_name,
        )
