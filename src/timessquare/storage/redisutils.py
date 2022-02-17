"""Common functionality for Redis-based data stores."""

from __future__ import annotations

import json
from base64 import b64encode
from typing import Any, Mapping

__all__ = ["calculate_key", "encode_parameters_key"]


def calculate_key(
    *, prefix: str, page_name: str, parameters: Mapping[str, Any]
) -> str:
    """Create the redis key for given the page's name and
    parameter values with a datastore's redis key prefix.

    Parameters
    ----------
    prefix : str
        The storage classes's redis key prefix. This separates keys from,
        e.g. the NbHtmlCacheStore from the NoteburstJobStore.
    page_name : str
        The name of the page (corresponds to
        `timessquare.domain.page.PageModel.name`).
    parameters : dict
        The parameter values, keyed by the parameter names, with values as
        cast Python types
        (`timessquare.domain.page.PageParameterSchema.cast_value`).

    Returns
    -------
    key : str
        The unique redis key for this combination of page name and
        parameter values for a given datastore.
    """
    return f"{prefix}/{page_name}/{encode_parameters_key(parameters)}"


def encode_parameters_key(parameters: Mapping[str, Any]) -> str:
    """Encode the notebook template parameters into a string that is used
    in a redis key.

    Parameters
    ----------
    parameters : dict
        The parameter values, keyed by the parameter names, with values as
        cast Python types
        (`timessquare.domain.page.PageParameterSchema.cast_value`).

    Returns
    -------
    parameters_key : str
        A canonical string reprentation of the parameter values.

    See also
    --------
    NbHtmlCacheStore.calculate_key
    """
    return b64encode(
        json.dumps(
            {k: p for k, p in parameters.items()}, sort_keys=True
        ).encode("utf-8")
    ).decode("utf-8")
