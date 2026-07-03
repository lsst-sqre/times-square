# Copilot instructions

## Code style

- Docstrings are in Numpydoc style.
  - Don't include types in Parameters sections because they're already in type annotations.
  - Include the type as the term in the Returns section.
  - Don't document private methods and functions, by default
- Use type annotations in the `from __future__ import annotations` style

## Testing

- Use `pytest` for tests
- Use the functional style for tests, i.e., use `def test_something()` instead of `class TestSomething`.
- Put common mocks inside the `tests/support` directory.

## Running tests, formatting, linting, and type checking

- Run `uv run --only-group=nox nox -s lint` to check for linting errors and fix formatting issues
- Run `uv run --only-group=nox nox -s typing` to run mypy
- Run `uv run --only-group=nox nox -s test` to run pytests. To specify pytest arguments, use `--` followed by the arguments. For example, to run tests for a specific module, use `uv run --only-group=nox nox -s test -- tests/domain/pageparameters_test.py`.
