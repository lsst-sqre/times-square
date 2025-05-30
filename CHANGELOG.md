# Change log

<!--
Generate new changelog fragments with: scriv create.

Collect fragments into this file with: scriv collect --version X.Y.Z
-->

<!-- scriv-insert-here -->

<a id='changelog-0.21.1'></a>

## 0.21.1 (2025-05-30)

### Bug fixes

- The `dynamic_default` date syntax for a relative number of weeks/months/years from the current date didn't work in the 0.21.0 release. We fixed that feature and changed the syntax to use `w`, `m`, and `y` for weeks, months, and years respectively. This syntax is similar to how relative numbers of days are treated (for example, `+5d` for 5 days from now). Some examples:

  - `dynamic_default: 1w` for one week from now
  - `dynamic_default: -2m` for two months ago
  - `dynamic_default: 3y` for three years from now

  The promised syntax of `dynamic_default: +1week` from the 0.21.0 release is no longer supported. The `week_end` / `week_start` syntax still uses the full words rather than the first letter abbreviations.

<a id='changelog-0.21.0'></a>

## 0.21.0 (2025-05-29)

### New features

- The new `dayobs` parameter type adds native support for Rubin Observatory's `dayobs` date format. The `dayobs` is a string, `YYYYMMDD`, corresponding to the date in the UTC-12 timezone. This convention is useful because it is a unique identifier for each observing night on Cerro Pachón, and it is used in the Rubin Observatory's data products. To use `dayobs`, create a parameter of type `string` with a format field set to `dayobs`.

  Note that the `date` format is different from `dayobs` in that it uses the ISO 8601 date format (`YYYY-MM-DD`) and is in the UTC timezone.

- Date and `dayobs` parameters can now take a `dynamic_default` value, which causes the default value of that parameter to be a date relative to the date when the page is viewed. To use a dynamic default in a date parameter in a notebook's sidecar YAML file, replace the `default` field with `dynamic_default`. The dynamic default can be:

  - "today"
  - "yesterday"
  - "tomorrow"
  - A relative number of days earlier (e.g., "-5d" for 5 days ago) or later (e.g., "+3d" for 3 days in the future)
  - A relative number of weeks (e.g. "-2week" for 2 weeks ago), months (e.g. "+1month" for 1 month in the future), or years (e.g. "-1year" for 1 year ago)
  - The first day of the week/month/year ("week_start", "month_start", "year_start"), or a number of periods into the past or future (e.g., "-1week_start" for the start of previous week, "+1month_start" for the start of next month).
  - The last day of the week/month/year ("week_end", "month_end", "year_end"), or a number of periods into the past or future (e.g., "-1week_end" for the end of previous week, "+1month_end" for the end of next month).

### Bug fixes

- When an invalid ipynb file is added to a GitHub Check Run, Times Square now catches the error and reports it as a failure in the check run.

<a id='changelog-0.20.1'></a>

## 0.20.1 (2025-05-22)

### Bug fixes

- In the `times-square nbstripout` command, commit to the database on each page migration. Without this, the migration failed when migrating large numbers of notebooks (~2000+).

<a id='changelog-0.20.0'></a>

## 0.20.0 (2025-05-22)

### New features

- Times Square now pre-processes notebooks with [nbstripout](https://github.com/kynan/nbstripout). This has two benefits:

  1. Nbstripout removes the `kernelspec` metadata from notebooks, which can cause issues when a notebook is made with a different kernel than the one that Times Square uses for notebook execution in the Rubin Science Platform. All notebooks now run under the `lsst` kernel.

  2. Nbstripout removes outputs from the notebooks, in cases where outputs are committed to their Git repository. This improves the performance for storing and transferring notebooks in the system.

  Although Times Square now uses nbstripout internally, it is still a good idea for authors to run nbstripout as a pre-commit hook in their own repositories to improve their own development processes.

- The `times-square nbstripout` CLI command provides a way to migrate existing notebooks to the the new stripped format by running `nbstripout` on all notebooks in the database.

### Bug fixes

- Fixed the capitalization of the `lsst` kernel name. Previously it was `LSST`, which is the _display name_, but not the _kernel name_. This is relevant now that [Noteburst uses the specified kernel name to run notebooks](https://github.com/lsst-sqre/noteburst/pull/121).

<a id='changelog-0.19.0'></a>

## 0.19.0 (2025-05-15)

### Backwards-incompatible changes

- This release requires a Alembic database migration (new Alembic revision is `c617718eaf6b`).

### New features

- Improved reporting of notebook execution errors in GitHub check runs.

  - Uncaught exceptions in the notebook now result in a failure of the GitHub check run. The exception message is included in the check run output.

  - For timeouts, we now distinguish between notebook execution timeouts and GitHub check run timeouts.

  - For internal noteburst errors, we now show the full exception class to help with debugging.

- The notebook execution time is now reported in the GitHub check run output. This will help you understand what notebooks may be approaching their timeout limit.

- Notebook execution timeouts are now configurable per notebook. In a notebook's sidecar file, set the timeout under the 'timeout' field. This value can be an integer or float (seconds), or a string with a time interval (e.g., '5m', '1h'). It not set or left to null, the default timeout is used (which is the previous behavior). Use this setting to decrease the timeout for notebooks that are known to run fast, or to attempt to increase the timeout for notebooks that are known to run slow. Notebooks still cannot exceed the timeout in the Noteburst service configuration.

### Other changes

- Adopt uv's dependency-groups and uv.lock for dependency management. This replaces the previous use of pip-tools compile to generate requirement/main.txt and dev.txt files of pinned dependencies.

<a id='changelog-0.18.1'></a>

## 0.18.1 (2025-03-06)

### Bug fixes

- Fix date and datetime parameter support by adding the "format" key to the Pydantic model of the sidecar settings file for pages in GitHub.

<a id='changelog-0.18.0'></a>

## 0.18.0 (2025-02-28)

### Backwards-incompatible changes

- Redis cache keys for page instance HTML models and noteburst job records use a new format based on the URL query string of page instances and display settings. Existing cached data will be ignored, but the new `times-square migrate-html-cache` command is available to migrate cached HTML pages in the old key format to the new one based on URL query strings.

- The Jinja context for rendering templated Markdown cells now uses the native Python types rather than the string representation. This provides more flexibility for template authors to use these values in their templates. For example, a date parameter is a `datetime.date` object rather than a string. A boolean parameter is a `bool` rather than a string.

### New features

- Parameters can now have `date` and `date-time` JSON schema formats. In a notebook, these parameters are rendered as `datetime.date` and `datetime.datetime` objects, respectively.

- Improved reliability of constructing URL query strings in the API by using the new `PageParameterSchema` classes in conjunction with the `PageInstanceId` class and `NbHtmlKey` classes.

- A new `times-square migrate-html-cache` command is available to migrate cached HTML pages in the old key format to the new one based on URL query strings.

### Bug fixes

- Fix getting `date_deleted` from the pages database table.

### Other changes

- Update to Python 3.13
- Adopt uv in the Docker image
- New internal API for page parameters. Each parameter type is now backed by a subclass of `PageParameterSchema`. These types implement methods for casting to Python types, creating JSON-compatible values, query-string compatible values, and listing any Python imports needed to instantiate the native Python type.
- Refactored interface models to the "storage" layer where possible, including the models for settings files in GitHub repositories and models for the GitHub API. This helps clarify the internal domain from external interfaces.

<a id='changelog-0.17.0'></a>

## 0.17.0 (2025-02-05)

### New features

- `GET /v1/github/rendered/{display_path}` that returns a rendered GitHub-backed notebook template. This route provides the same functionality as `GET /v1/pages/{page}/rendered`, but finds the page based on its GitHub URL path. This is an additional path, all existing functionality, including the existing template rendering path, remains unchanged.

  We need to deploy Times Square to environments where some users should not have permissions to execute notebooks, but they should have permissions to render notebook templates for certain GitHub-based notebooks. This will let us configure that access via methods that apply permissions based on URL paths.

<a id='changelog-0.16.0'></a>

## 0.16.0 (2025-01-22)

### New features

- Instrument with Sentry. Don't trace the SSE endpoint because Sentry holds spans in memory as long as the connection is open.

<a id='changelog-0.15.0'></a>

## 0.15.0 (2025-01-15)

### Backwards-incompatible changes

- Migrate the database to use `TEXT` column types where previously we used `VARCHAR` columns with a (now unnecessary) length limit. **This change requires a database migration on deployment**. In Postgres there is no functional or performance difference between `VARCHAR` and `TEXT` columns. This change simplifies the database schema and reduce the risk of future issues with column length limits.

### Bug fixes

- In the `cli` tox environment, fix the name of the executable to be `times-square` rather than `timessquare`.

### Other changes

- Improved the developer documentation for database migration to concretely provide copy-and-paste-able commands for preparing and running database migrations.

<a id='changelog-0.14.0'></a>

## 0.14.0 (2025-01-13)

### Other changes

- Times Square now uses Alembic to manage database schema versioning and migrations.

- Begin SQLAlchemy 2 adoption with the new `DeclarativeBase`, `mapped_column`, and the `Mapped` type.

- Update the `make update` command in the Makefile to use the `--universal` flag with `uv pip compile`.

- Fix type checking issues for Pydantic fields to use empty lists as the default, rather than using a default factory.

- Explicitly set `asyncio_default_fixture_loop_scope` to `function`. An explicit setting is now required by pytest-asyncio.

<a id='changelog-0.13.0'></a>

## 0.13.0 (2024-09-12)

### New features

- Times Square now specifies a timeout for notebook executions with Noteburst. This provides better feedback for notebook executions that have hung, either when rendering new pages for users, for when doing a GitHub Check Run. Currently this timeout is set app-wide with the `TS_DEFAULT_EXECUTION_TIMEOUT` environment variable. The default timeout is 60 seconds. In the future we intend to add per-notebook timeout configuration.

- Times Square enforces a timeout when polling for Noteburst results during a GitHub Check run. This prevents the Check Run from hanging indefinitely if the Noteburst service is unable to time out a notebook execution or fails for any reason. This timeout is configurable via the `TS_CHECK_RUN_TIMEOUT` environment variable. The default timeout is 600 seconds.

<a id='changelog-0.12.0'></a>

## 0.12.0 (2024-09-04)

### New features

- Improved feedback in GitHub Check Runs:

  - If a YAML file has bad syntax causing a parsing error, we now post the YAML error as a check run annotation — including the location of the error in the file.

  - If the notebook has incorrect Jinja templating in its Markdown cells, we now post a check run annotation with the error message and cell number.

### Other changes

- Adopt uv and tox-uv for pinning and installing dependencies
- Pin the tox dependencies with a `requirements/tox.[in|txt]` file
- Adapt configuration for tox-docker version 5's randomized connection ports
- Adopt [ruff-shared.toml](https://github.com/lsst/templates/blob/main/project_templates/fastapi_safir_app/example/ruff-shared.toml) for common SQuaRE ruff configuration.

- The GitHub Check Run service methods are now part of a new `GitHubCheckRunService` class, separate from the `GitHubRepoService`. This internal change helps clarify what functionality is needed for the GitHub Checks functionality, as opposed to syncing data with GitHub repositories.

<a id='changelog-0.11.0'></a>

## 0.11.0 (2024-03-27)

### New features

- New support for background recomputation of a page instance (cached HTML) with the new `DELETE /v1/pages/:page/html?{params}` endpoint. This endpoint triggers a Noteburst computation of the page instance and deletes the currently-cached HTML once that computation is complete. This API provides a way for users to request a recomputation of a page instance without affecting other users that may be viewing that page instance.
- A new server-sent events endpoint for getting updates on the status of a page instance's computation and HTML rendering: `GET /v1/pages/:page/html/events?{params}`. This endpoint should replace the current practice of clients polling the `GET /v1/pages/:page/htmlstatus` endpoint to determine when a page instance's HTML is ready to be displayed. The events endpoint also provides additional metadata, such as the time when the current computation job was queued so that clients can provide more detailed status information to users. This endpoint works well with the new `DELETE /v1/pages/:page/html?{params}` endpoint, as it can provide updates on the status of the recomputation job while still linking to the existing cached HTML.

<a id='changelog-0.10.0'></a>

## 0.10.0 (2024-03-13)

### New features

- We've adopted Safir's `safir.fastapi.ClientRequestError` so that errors like 404 and 422 (input validation) now use the same error format as FastAPI uses for its built-in model validation errors. For parameter errors from endpoints like `GET /v1/pages:page/html` the parameter name is now part of the `loc` field in the error message.
- Times Square and its worker now send uncaught exceptions to a Slack webhook for better error reporting. The webhook URL is set in the `TS_SLACK_WEBHOOK_URL` environment variable.

### Other changes

- Updated to Python 3.12
- Updated to Pydantic 2
- Adopted Ruff for linting and formatting, replacing black, flake8, and isort.
- Switch to using Annotated for Pydantic models and FastAPI path functions.

<a id='changelog-0.9.2'></a>

## 0.9.2 (2023-09-21)

### Bug fixes

- Fix how strings are rendered in the parameters cell of notebooks. Previously string parameters were missing Python quotes. Now parameters are passed to Jinja in their `repr` string forms to be proper Python code.

<a id='changelog-0.9.1'></a>

## 0.9.1 (2023-07-31)

### Bug fixes

- When a page is updated (e.g., from a GitHub pull request merge), the HTML renders for that page are cleared.
- Fixed a bug where updating a page and executing it with defaults would result in two requests to Noteburst.
- Deleting a page now deletes the page's HTML renders.

<a id='changelog-0.9.0'></a>

## 0.9.0 (2023-07-27)

### Backwards-incompatible changes

- New treatment for templating in notebooks. Times Square no longer treats all cells as Jinja templates. Instead, the first cell is considered to be under the control of Times Square for setting variables. When a parameters are rendered into a notebook, the first code cell is replaced with new source that sets the parameter variables to their values. This means that notebook authors can now use that first cell to set and experiment with parameter values for interactive debugging, knowing that Times Square will replace that cell with new values when the notebook is rendered.

### Bug fixes

- Parameter names are now validated against Python keyword names using `keyword.iskeyword()`. This prevents parameter names from shadowing Python keywords.

<a id='changelog-0.8.0'></a>

## 0.8.0 (2023-07-27)

### New features

- Add a new `TS_GITHUB_ORGS` environment variable. This can be set to a comma-separated list of GitHub organizations that can install the Times Square GitHub App and sync notebooks into the Times Square service. This is a an important security feature if the Times Square GitHub App is set to public so that multiple GitHub organizations can sync repositories with Times Square. GitHub webhook handlers filter out events from non-accepted organizations. The `GitHubRepoService` also checks the ownership on initialization.

### Other changes

- Adopt scriv for managing the changelog.
- Adopt ruff for linting, and update the codebase accordingly.
- Adopt the new neophile workflow for managing dependencies.
- Adopt the new `lsst-sqre/build-and-push-to-ghcr` GitHub Action for building and pushing Docker images.
- Adopt the new FastAPI lifespan function for handling start-up and shutdown.
- Create a Sphinx documentation site at `times-square.lsst.io`.

- Add documentation for configuring the Times Square GitHub App, including a sample URL with the app settings built-in.

## 0.7.0 (2023-04-19)

### New features

- Adopt `safir.redis.pydantic` for Redis-backed storage.
- Adopt `safir.github` creating the GitHub App client and modelling of GitHub resources with Pydantic.

### Bug fixes

- Fix handling of disabled pages so that they aren't executed in a GitHub check, and are dropped if they previously existed in the database.

### Other changes

- Update to Python 3.11

### 0.6.0 (2022-08-18)

### New features

- Times Square now exposes information about pages created during GitHub PR check runs:

  - `GET /times-square/api/v1/github-pr/:org/:repo/:sha` provides metadata for a repository's check run in general, such as the contents in the check run and the GitHub pull request or check run.
  - `GET /times-square/api/v1/github-pr/:org/:repo/:sha/:path` provides metadata about a specific notebook.

  Times Square check runs also link to the pull request preview pages published through Times Square's interface in Squareone.

## 0.5.0 (2022-07-04)

### New features

- Times Square now implements two GitHub check runs for pull requests on notebook repositories:

  - The "YAML config" check validates the structure of YAML configuration files, specifically the `times-square.yaml` repository settings as well as the YAML sidecar files that describe each notebook.
  - The "Notebook execution" check actually runs notebooks (given their default parameters) with Noteburst, and ensures that they return without error.

  Together, these features will help contributors to Times Square notebook repositories ensure that their contributions work before they merge pull requests.

## 0.4.0 (2022-05-14)

### New features

- Times Square now supports sourcing Jupyter Notebooks from GitHub repositories, in addition to its original mode of API-sourced notebooks. To do this, Times Square acts as a GitHub App integration, and receives webhook events from GitHub. When the Times Square app is installed in a GitHub repository, or a push to the default branch is accomplished, Times Square syncs Jupyter Notebooks from that repository into its page store.

  Times Square-enabled GitHub repositories feature a `times-square.yaml` file that provides settings for the repository as a whole (such as switching the repository on or off) and setting the root path for notebooks. Each notebook (`ipynb` file) also has a corresponding YAML sidecar file that provides metadata for individual notebooks, including the title, description, tags, authors, and the parameter schemas.

- To efficiently process webhook events, Times Square now operates an arq (Redis-backed) distributed queue.

- New API endpoints:

  - `GET /github/webhook` receives webhook events from GitHub (this should not require Gafaelfawr auth since webhooks are internally authenticated)
  - `GET /v1/github` provides a hierarchical tree of GitHub-backed pages within their GitHub organization, repository, and directory contexts. This endpoint powers Squareone's navigational view.
  - `GET /v1/github/:path` provides the same data as `/v1/pages/:page`, but uses the GitHub _display path_ as the path argument. An example of a display is `lsst-sqre/times-square-demo/matplotlib/gaussian2d`.

  The `GET /v1/github` and `GET /v1/pages/:page` endpoints both include a new `github` field with metadata specific to GitHub-backed pages.

## 0.3.0 (2022-03-31)

### New features

- This release adds a new `/v1/pages/:page/htmlstatus` endpoint that provides information about the availability of HTML for a specific page instance (set of page parameters). The Times Square UI monitors this endpoint to determine if an HTML rendering is available and when to refresh the iframe element displaying the HTML rendering.

- The `htmlstatus` endpoint includes a SHA256 hash of the HTML, which is now stored alongside the HTML in the Redis cache. This hash can be used to invalidate expired HTML renderings for pages with a finite time-to-live setting.

- This release adds a new `times-square reset-html` command to the command line interface for clearing the Redis cache of HTML renderings (primarily useful during development).

## 0.2.0 (2022-03-15)

### New features

- Set up the `/v1/` HTTP API, along with core services, domain models and storage for managing pages and interfacing with Noteburst for notebook execution.

## 0.2.0 (2022-03-15)

### New features

- Set up the `/v1/` HTTP API, along with core services, domain models and storage for managing pages and interfacing with Noteburst for notebook execution.

## 0.1.0 (2021-11-17)

### New features

- Initial application set up.
