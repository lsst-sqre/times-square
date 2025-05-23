# Copilot instructions

## Code style

- Docstrings are in Numpydoc style.
  - Don't include types in Parameters sections because they're already in type annotations.
  - Include the type as the term in the Returns section.
  - Don't document private methods and functions, by default
- Use type annotations in the `from __future__ import annotations` style

## Running tests, formatting, linting, and type checking

- Run `tox run -e lint` to check for linting errors and fix formatting issues
- Run `tox run -e typing` to run mypy
- Run `tox run -e docker` to run pytests. To specify pytest arguments, use `--` followed by the arguments. For example, to run tests for a specific module, use `tox run -e docker -- tests/domain/pageparameters_test.py`.
