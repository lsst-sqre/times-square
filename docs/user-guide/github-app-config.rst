##########################
Configuring the GitHub App
##########################

Times Square operates as a GitHub App to access notebooks in GitHub repositories, to get webhooks when those notebooks change, and to offer status checks for pull requests that change notebooks.
Each installation of Times Square in different Phalanx environments has its own GitHub App in order to receive webhook events.
Times Square installations in different RSP/Phalanx environments can share the same source repository, however.

To learn more about installing GitHub Apps in general, see the `GitHub Apps documentation <https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/creating-a-github-app>`__.

Create an app with a template URL
=================================

You can create the GitHub App by customizing and visiting the following URL (replace ``lsst-sqre`` with the GitHub organization or user that owns the source repository):

.. literalinclude:: _github-app-url-org.txt

Alternatively, the app can be installed in a personal account (not recommended for production use):

.. literalinclude:: _github-app-url-personal.txt

Once you follow the link, you will be able to make further customizations to the GitHub App before creating it.
These settings are described in the following sections.

GitHub App settings
===================

Name
----

The name of the GitHub App should be "Times Square (env)".
For example, ``Times Square (data.lsst.cloud)``.

This naming convention distinguishes the Times Square installations for each Phalanx environment.

Description
-----------

Use the description provided with the GitHub App template URL, and modify it as needed.

Homepage URL
------------

Set this to the Times Square app in the RSP, e.g. https://data-dev.lsst.cloud/times-square/.

Identifying and authorizing users
---------------------------------

Not applicable.

Post installation
-----------------

Not applicable.

Webhook
-------

The webhook should be enabled.
Set the webhook URL to the ``/times-square/api/github/webhook`` endpoint in the RSP/Phalanx environment.
For example, ``https://data.lsst.cloud/times-square/api/github/webhook``.

Create a webhook secret and store it in the :envvar:`TS_GITHUB_WEBHOOK_SECRET` environment variable (through Vault/1Password).

Permissions
-----------

The GitHub App needs the following repository permissions:

- **Checks**: Read & write
- **Contents**: Read-only
- **Metadata**: Read-only
- **Pull requests**: Read-only

Events
------

The GitHub App needs to subscribe to the following events:

- Check Run
- Check Suite
- Push
- Pull request
- Repository

.. _github-app-secrets:

Create the app and secrets
==========================

Once the GitHub App is configured, you can click the :guilabel:`Create GitHub App` button to create it in your GitHub organization or user account.

When you do this, you can create the secret keys that Times Square needs to authenticate with GitHub and verify webhook events.
These are provided to Times Square as environment variables:

- :envvar:`TS_GITHUB_APP_ID`: The GitHub App ID. This is shown on the GitHub App's :guilabel:`General` page under the :guilabel:`About` heading.
- :envvar:`TS_GITHUB_APP_PRIVATE_KEY`: The GitHub App's private key. This is shown on the GitHub App's :guilabel:`General`.
- :envvar:`TS_GITHUB_WEBHOOK_SECRET`: The webhook secret you created in the GitHub App's :guilabel:`General` page under :guilabel:`Webhooks`.
- :envvar:`TS_GITHUB_ORGS`: A comma-separated list of the GitHub organizations that Times Square should operate on. For a private GitHub App, this should be the organization that owns the app. See also: :ref:`multiple-github-orgs`.

See :doc:`environment-variables` for more information on Phalanx's environment variable settings.

Install the app in the source repository
========================================

Once the app is created and the Times Square app is configured, you need to *install* the app in the source repository (or repositories, if there are several).
From the app's GitHub settings page, click :guilabel:`Install App` and select the repositories to install it in.
Avoid installing the app in repositories that do not use Times Square.

.. _multiple-github-orgs:

Sourcing notebooks from multiple GitHub organizations
=====================================================

By default, the Times Square GitHub App is configured as "private," meaning that it can only be installed in repositories owned by the organization that owns the GitHub App.
If you want to source notebooks from multiple GitHub organizations, you need to configure the GitHub App as "public" instead.
There are three steps involved in doing this:

1. Update the :envvar:`TS_GITHUB_ORGS` environment variable in the Times Square configuration to include the additional organizations. For example, set it to ``lsst,lsst-dm,lsst-sqre``.

2. Update the GitHub App to be "public" instead of "private." This is done on the GitHub App's :guilabel:`Advanced` settings page under the :guilabel:`Make this GitHub App public` heading.

3. Install the GitHub App in additional repositories in the other GitHub organizations.
