Update the project's dependencies to their latest versions by running these steps:

1. Run `make update`.
2. Run `uv run --only-group=nox nox` to ensure linting, type checking, and tests pass.
3. If nox from previous step completed successfully, commit the changed files with a message: "Update dependencies to latest versions".
