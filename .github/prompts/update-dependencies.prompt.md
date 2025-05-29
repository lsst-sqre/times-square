Update the project's dependencies to their latest versions by running these steps:

1. Run `make update`.
2. Run [uv-version-sync-prompt](uv-version-sync.prompt.md) to update the `uv` version.
3. Run `tox` to ensure linting, type checking, and tests pass.
4. If tox from previous step completed successfully, commit the changed files with a message: "Update dependencies to latest versions".
