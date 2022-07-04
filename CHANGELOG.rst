Change log
==========

0.5.0 (2022-07-04)
------------------

Times Square now implements two GitHub check runs for pull requests on notebook repositories:

- The "YAML config" check validates the structure of YAML configuration files, specifically the ``times-square.yaml`` repository settings as well as the YAML sidecar files that describe each notebook.
- The "Notebook execution" check actually runs notebooks (given their default parameters) with Noteburst, and ensures that they return without error.

Together, these features will help contributors to Times Square notebook repositories ensure that their contributions work before they merge pull requests.

0.4.0 (2022-05-14)
------------------

Times Square now supports sourcing Jupyter Notebooks from GitHub repositories, in addition to its original mode of API-sourced notebooks.
To do this, Times Square acts as a GitHub App integration, and receives webhook events from GitHub.
When the Times Square app is installed in a GitHub repository, or a push to the default branch is accomplished, Times Square syncs Jupyter Notebooks from that repository into its page store.

Times Square-enabled GitHub repositories feature a ``times-square.yaml`` file that provides settings for the repository as a whole (such as switching the repository on or off) and setting the root path for notebooks.
Each notebook (``ipynb`` file) also has a corresponding YAML sidecar file that provides metadata for individual notebooks, including the title, description, tags, authors, and the parameter schemas.

To efficiently process webhook events, Times Square now operates an arq (Redis-backed) distributed queue.

New API endpoints:

- ``GET /github/webhook`` receives webhook events from GitHub (this should not require Gafaelfawr auth since webhooks are internally authenticated)
- ``GET /v1/github`` provides a hierarchical tree of GitHub-backed pages within their GitHub organization, repository, and directory contexts. This endpoint powers Squareone's navigational view.
- ``GET /v1/github/:path`` provides the same data as ``/v1/pages/:page``, but uses the GitHub *display path* as the path argument. An example of a display is ``lsst-sqre/times-square-demo/matplotlib/gaussian2d``.

The ``GET /v1/github`` and ``GET /v1/pages/:page`` endpoints both include a new ``github`` field with metadata specific to GitHub-backed pages.

0.3.0 (2022-03-31)
------------------

This release adds a new ``/v1/pages/:page/htmlstatus`` endpoint that provides information about the availability of HTML for a specific page instance (set of page parameters).
The Times Square UI monitors this endpoint to determine if an HTML rendering is available and when to refresh the iframe element displaying the HTML rendering.

In addition, the ``htmlstatus`` endpoint includes a SHA256 hash of the HTML, which is now stored alongside the HTML in the Redis cache.
This hash can be used to invalidate expired HTML renderings for pages with a finite time-to-live setting.

As well, this release adds a new ``times-square reset-html`` command to the command line interface for clearing the Redis cache of HTML renderings (primarily useful during development).

0.2.0 (2022-03-15)
------------------

Set up the ``/v1/`` HTTP API, along with core services, domain models and storage for managing pages and interfacing with Noteburst for notebook execution.

0.2.0 (2022-03-15)
------------------

Set up the ``/v1/`` HTTP API, along with core services, domain models and storage for managing pages and interfacing with Noteburst for notebook execution.

0.1.0 (2021-11-17)
------------------

Initial application set up.
