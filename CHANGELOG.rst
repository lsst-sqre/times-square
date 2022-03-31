Change log
==========

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
