# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Times Square is a Rubin Science Platform (RSP) service for displaying parameterized Jupyter Notebooks as websites. It's used for engineering dashboards, quick-look data previewing, and reports that incorporate live data sources.

The service executes notebooks via [Noteburst](https://noteburst.lsst.io) in JupyterLab instances and renders them as web pages with parameterization support.

## Development Setup

Initialize the development environment:
```bash
make init  # Installs dependencies and sets up pre-commit hooks
```

Run local development server:
```bash
make run  # Starts docker-compose services and runs the app
```

The development server runs with auto-reload on port 8080 and requires PostgreSQL and Redis (started automatically via docker-compose).

Initialize the database:
```bash
times-square init  # Must have TS_ALEMBIC_CONFIG_PATH set or pass --alembic-config-path
```

## Testing and Quality

Run tests (requires Docker):
```bash
tox run -e docker  # Runs full test suite with PostgreSQL and Redis containers
tox run -e docker -- tests/domain/pageparameters_test.py  # Run specific test file
tox run -e docker -- tests/domain/pageparameters_test.py::test_specific_test  # Run specific test
```

Linting and formatting:
```bash
tox run -e lint  # Checks linting and fixes formatting issues
```

Type checking:
```bash
tox run -e typing  # Runs mypy on source and tests
```

Build documentation:
```bash
tox run -e docs
```

## Code Style

- **Docstrings**: Use Numpydoc style
  - Don't include types in Parameters sections (they're in type annotations)
  - Include the type as the term in the Returns section
  - Don't document private methods/functions by default
- **Type annotations**: Use `from __future__ import annotations` style
- **Testing**: Use functional style (`def test_something()` not `class TestSomething`)
- **Test mocks**: Put common mocks in `tests/support/`

## Architecture

Times Square follows a layered architecture:

### Domain Layer (`src/timessquare/domain/`)
Contains business logic and domain models as dataclasses. Key models:
- `PageModel`: A parameterized notebook page
- `PageExecutionInfo`: Information about a page execution
- `PageParameters`: Parameter schema and validation
- `RunSchedule`/`ScheduleRule`: Scheduling configuration

### Storage Layer (`src/timessquare/storage/`)
Database and external service adapters:
- `PageStore`: SQLAlchemy database operations for pages
- `NbHtmlCacheStore`: Redis cache for rendered HTML
- `NoteburstApi`: Client for the Noteburst notebook execution service
- `storage/github/`: GitHub API integration for notebook source management

### Service Layer (`src/timessquare/services/`)
Business logic orchestration:
- `PageService`: Primary service for page operations (CRUD, execution, caching)
- `BackgroundPageService`: Manages background page updates
- `GitHubRepoService`: GitHub repository operations
- `RunSchedulerService`: Scheduled execution management

### Handler Layer (`src/timessquare/handlers/`)
FastAPI route handlers:
- `handlers/v1/`: Main REST API endpoints (v1)
- `handlers/external/`: Public endpoints (e.g., GitHub webhooks)
- `handlers/internal/`: Internal endpoints (health checks, etc.)

### Worker Layer (`src/timessquare/worker/`)
ARQ-based background job processing:
- `worker/main.py`: ARQ worker entry point
- `worker/functions/`: Background job implementations
- Uses Redis-backed job queue for async operations

### Database Schema (`src/timessquare/dbschema/`)
SQLAlchemy ORM models:
- `SqlPage`: Database representation of pages
- Migration files in `alembic/versions/`

## Key Dependencies

- **FastAPI**: Web framework
- **SQLAlchemy**: ORM for PostgreSQL
- **Safir**: Rubin Observatory's FastAPI/SQLAlchemy utilities
- **ARQ**: Async job queue (Redis-backed)
- **Noteburst**: External service for notebook execution
- **nbformat/nbconvert**: Jupyter notebook handling
- **gidgethub**: GitHub API client

## Database Migrations

Create a new migration:
```bash
tox run -e alembic -- revision --autogenerate -m "Description"
```

Apply migrations:
```bash
tox run -e alembic -- upgrade head
```

Validate schema is current:
```bash
times-square validate-db-schema --alembic-config-path=alembic.ini
```

## CLI Commands

The `times-square` CLI provides administrative operations:
- `times-square develop`: Run with auto-reload (development)
- `times-square init`: Initialize database schema
- `times-square update-db-schema`: Apply Alembic migrations
- `times-square validate-db-schema`: Check schema currency
- `times-square reset-html`: Clear Redis HTML cache
- `times-square migrate-html-cache`: Migrate cache format
- `times-square nbstripout`: Strip notebook outputs (migration)

## Configuration

Configuration is via environment variables (prefix `TS_`) or `.env` file:
- `TS_DATABASE_URL`: PostgreSQL connection string
- `TS_DATABASE_PASSWORD`: Database password
- `TS_REDIS_URL`: Redis connection for cache
- `TS_REDIS_QUEUE_URL`: Redis connection for ARQ job queue
- `TS_GAFAELFAWR_TOKEN`: Authentication token
- `TS_ENVIRONMENT_URL`: Base URL for the deployment
- `TS_ARQ_MODE`: ARQ mode (`production`, `test`)
- `TS_ENABLE_GITHUB_APP`: Enable GitHub App integration
- See `src/timessquare/config.py` for complete list

## Project Structure Notes

- Main FastAPI app is in `src/timessquare/main.py`
- Database initialization in `src/timessquare/database.py`
- Dependency injection via `src/timessquare/dependencies/`
- Configuration in `src/timessquare/config.py` (uses Pydantic settings)
- The app uses SQLAlchemy async sessions throughout
- Background jobs are queued via Safir's ARQ integration
