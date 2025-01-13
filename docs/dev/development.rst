#################
Development guide
#################

This page provides procedures and guidelines for developing and contributing to Times Square.

Scope of contributions
======================

Times Square is an open source package, meaning that you can contribute to Times Square itself, or fork Times Square for your own purposes.

Since Times Square is intended for internal use by Rubin Observatory, community contributions can only be accepted if they align with Rubin Observatory's aims.
For that reason, it's a good idea to propose changes with a new `GitHub issue`_ before investing time in making a pull request.

Times Square is developed by the Rubin Observatory SQuaRE team.

.. _GitHub issue: https://github.com/lsst-sqre/times-square/issues/new

.. _dev-environment:

Setting up a local development environment
==========================================

Times Square is a Python project that should be developed within a virtual environment.

If you already have a Python virtual environment set up in your shell, you can use the :command:`make init` command to install Times Square and its development dependencies into it.

.. code-block:: sh

    git clone https://github.com/lsst-sqre/times-square.git
    cd times-square
    pip install tox
    make init

.. _pre-commit-hooks:

Pre-commit
==========

The pre-commit hooks, which are automatically installed by running the :command:`make init` command on :ref:`set up <dev-environment>`, ensure that files are valid and properly formatted.
Some pre-commit hooks automatically reformat code:

``ruff``
    Sorts Python imports and automatically fixes some common Python issues.

``black``
    Automatically formats Python code.

When these hooks fail, your Git commit will be aborted.
To proceed, stage the new modifications and proceed with your Git commit.

.. _dev-run-tests:

Running tests
=============

To test all components of Times Square, run tox_, which tests the library the same way that the GitHub Actions CI workflow does:

.. code-block:: sh

   tox run

To see a listing of specific tox sessions, run:

.. code-block:: sh

   tox list

Times Square requires Docker to run its tests.

Database migrations
===================

Times Square uses Alembic_ for database migrations.
If your work involves changing the database schema (in :file:`/src/timessquare/dbschema`) you will need to prepare an Alembic migration in the same PR.
This process is outlined in the `Safir documentation <https://safir.lsst.io/user-guide/database/schema.html#testing-database-migrations>`__.
Note that in Times Square the :file:`docker-compose.yaml` is hosted in the root of the repository rather than in the :file:`alembic` directory.

Building documentation
======================

Documentation is built with Sphinx_:

.. _Sphinx: https://www.sphinx-doc.org/en/master/

.. code-block:: sh

   tox run -e docs

The build documentation is located in the :file:`docs/_build/html` directory.

To check the documentation for broken links, run:

.. code-block:: sh

   tox run -e docs-linkcheck

.. _dev-change-log:

Updating the change log
=======================

Times Square uses scriv_ to maintain its change log.

When preparing a pull request, run

.. code-block:: sh

   scrive create

This will create a change log fragment in :file:`changelog.d`.
Edit that fragment, removing the sections that do not apply and adding entries for your pull request.

Change log entries use the following sections:

- **Backward-incompatible changes**
- **New features**
- **Bug fixes**
- **Other changes** (for minor, patch-level changes that are not bug fixes, such as logging formatting changes or updates to the documentation)

Do not include a change log entry solely for updating pinned dependencies, without any visible change to Times Square's behavior.
Every release is implicitly assumed to update all pinned dependencies.

These entries will eventually be cut and pasted into the release description for the next release, so the Markdown for the change descriptions must be compatible with GitHub's Markdown conventions for the release description.
Specifically:

- Each bullet point should be entirely on one line, even if it contains multiple sentences.
  This is an exception to the normal documentation convention of a newline after each sentence.
  Unfortunately, GitHub interprets those newlines as hard line breaks, so they would result in an ugly release description.
- Avoid using too much complex markup, such as nested bullet lists, since the formatting in the GitHub release description may not be what you expect and manually editing it is tedious.

.. _style-guide:

Style guide
===========

Code
----

- The code style follows :pep:`8`, though in practice lean on Black and ruff to format the code for you. Use :sqr:`072` for for architectural guidance.

- Use :pep:`484` type annotations.
  The ``tox run -e typing`` test session, which runs mypy_, ensures that the project's types are consistent.

- Write tests for Pytest_.

Documentation
-------------

- Follow the `LSST DM User Documentation Style Guide`_, which is primarily based on the `Google Developer Style Guide`_.

- Document the Python API with numpydoc-formatted docstrings.
  See the `LSST DM Docstring Style Guide`_.

- Follow the `LSST DM ReStructuredTextStyle Guide`_.
  In particular, ensure that prose is written **one-sentence-per-line** for better Git diffs.

.. _`LSST DM User Documentation Style Guide`: https://developer.lsst.io/user-docs/index.html
.. _`Google Developer Style Guide`: https://developers.google.com/style/
.. _`LSST DM Docstring Style Guide`: https://developer.lsst.io/python/style.html
.. _`LSST DM ReStructuredTextStyle Guide`: https://developer.lsst.io/restructuredtext/style.html
