# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Times Square is a Rubin Science Platform (RSP) FastAPI service that publishes parameterized Jupyter Notebooks as web pages. It does not execute notebooks itself: execution is delegated to the [Noteburst](https://noteburst.lsst.io) service (`src/timessquare/storage/noteburst.py` is the API client), and the resulting rendered HTML is cached in Redis. The design is described in [SQR-062](https://sqr-062.lsst.io). The user-facing UI lives in the separate Squareone repo; this repo is the REST API only.

## Commands

Dependencies are managed with uv; tasks run through nox (invoked via uv so nothing needs global installation). **Test, run, and migration sessions use testcontainers to start PostgreSQL and Redis, so Docker (or Colima — the noxfile auto-detects it) must be running.**

```sh
make init                                  # set up dev environment (uv sync + prek hooks)
uv run --only-group=nox nox -s lint        # ruff / pre-commit hooks via prek
uv run --only-group=nox nox -s typing      # mypy
uv run --only-group=nox nox -s test        # pytest (starts Postgres + Redis containers)
uv run --only-group=nox nox -s docs        # Sphinx docs build
make run                                   # local dev server with containerized backing services
```

Run a single test file or test by passing pytest args after `--`:

```sh
uv run --only-group=nox nox -s test -- tests/domain/pageparameters_test.py
uv run --only-group=nox nox -s test -- tests/handlers/v1/pages_test.py::test_pages
```

Other sessions:

```sh
uv run --only-group=nox nox -s cli -- <args>                       # run the times-square CLI against containers
uv run --only-group=nox nox -s create-migration -- "Message."      # autogenerate an Alembic migration
uv run --only-group=nox nox -s scriv-create                        # create a changelog fragment in changelog.d/
make update                                # upgrade pinned dependencies (uv lock --upgrade, prek autoupdate)
```

Every user-visible change needs a scriv changelog fragment in `changelog.d/`.

## Architecture

Two deployable processes share one codebase, configuration (`config.py`, env vars prefixed `TS_`), and service layer:

1. **FastAPI app** (`src/timessquare/main.py`) — routers in `handlers/`: `internal.py` (health, off the ingress), `external/` (GitHub webhook receiver and unversioned endpoints), `v1/` (the REST API). Authentication is handled upstream by Gafaelfawr; handlers read identity from the `X-Auth-Request-User` header.
2. **arq worker** (`src/timessquare/worker/main.py`) — background task functions in `worker/functions/` (one file per task), plus cron jobs (`schedule_runs` every 5 minutes, `cleanup_scheduled_runs` daily). Handlers enqueue tasks by name onto the arq Redis queue; e.g. GitHub webhook handlers do no real work themselves, they enqueue `repo_push`, `pull_request_sync`, `compute_check_run`, etc.

Both processes refuse to start if the Alembic schema is not current (`safir.database.is_database_current`).

### Layering

`handlers` → `services` → `storage` → `domain`, with `domain` models (plain pydantic/dataclass business objects) used at every layer:

- **`services/`** — business logic. `PageService` is the core; `GitHubRepoService` manages GitHub-backed pages; `githubcheckrun.py` runs notebook checks on PRs.
- **`storage/`** — one class per backend: `PageStore` (Postgres via SQLAlchemy), `NbHtmlCacheStore` (rendered-HTML Redis cache), `NoteburstJobStore` (pending execution jobs in Redis), `scheduledrunstore.py`, `noteburst.py` (Noteburst HTTP client), `github/` (GitHub API models and the `times-square.yaml` / notebook sidecar settings-file parsers).
- **`dbschema/`** — SQLAlchemy declarative models only; migrations live in `alembic/versions/`.

### Service construction

There is no DI container. In the API, the `context_dependency` (`dependencies/requestcontext.py`) yields a `RequestContext` that bundles the request, db session, Redis, arq queue, http client, and logger, and constructs services via properties (`context.page_service`). The worker builds the same services through `worker/servicefactory.py`. If you add a service or change a constructor, update both.

### Page domain

A "page" is a parameterized notebook. Parameter types live in `domain/pageparameters/` (one module per type: string, integer, date, dayobs, ...), validated against JSON Schema. Pages come from two sources: direct API upload, or GitHub repositories synced via the GitHub App integration (webhooks → worker tasks → `GitHubRepoService`). Scheduled re-execution is modeled in `domain/schedule*.py` (dateutil rrule-based) and driven by the worker cron jobs.

## Code style

- Numpydoc-style docstrings. Don't repeat types in Parameters sections (they're in annotations); do give the type as the term in Returns. Don't document private functions by default.
- `from __future__ import annotations` style type annotations.
- Tests are functional (`def test_something()`, not classes); shared mocks go in `tests/support/` (see `tests/support/github.py`). The test suite layout mirrors `src/timessquare/`.
- Ruff config extends the shared `ruff-shared.toml`; the philosophy is to disable lints with legitimate exceptions rather than scatter `noqa`.
