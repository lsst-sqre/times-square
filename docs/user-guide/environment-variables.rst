#####################
Environment variables
#####################

Noteburst uses environment variables for configuration.
In practice, these variables are typically set as Helm values and 1Password/Vault secrets that are injected into the container as environment variables.
See the `Phalanx documentation for Times Square <https://phalanx.lsst.io/applications/times-square/index.html>`__ for more information on the Phalanx-specific configurations.

.. envvar:: SAFIR_NAME

   (string, default: "Times Square") The name of the application.
   This is used in the metadata endpoint.

.. envvar:: SAFIR_PROFILE

   (string enum: "production" [default], "development") The application run profile.
   Use production to enable JSON structured logging.

.. envvar:: SAFIR_LOG_LEVEL

   (string enum: "debug", "info" [default], "warning", "error", "critical") The application log level.

.. envvar:: TS_PATH_PREFIX

   (string, default: "/times-square") The path prefix for the Times Square application.
   This is used to configure the application's URL.

.. envvar:: TS_ENVIRONMENT_URL

   (string) The base URL of the Rubin Science Platform environment.
   This is used for creating URLs to services, such as JupyterHub.

.. envvar:: TS_GAFAELFAWR_TOKEN

   (secret string) This token is used to make an admin API call to Gafaelfawr to get a token for the user.

.. envvar:: TS_DATABASE_URL

   (string) The URL of the database to use for Times Square.

.. envvar:: TS_DATABASE_PASSWORD

   (string) The name of the database to use for Times Square.

.. envvar:: TS_REDIS_URL

   (string) The URL of the Redis server, used by the worker queue.

.. envvar:: TS_ARQ_MODE

   (string enum: "production" [default], "test") The Arq worker mode.
   The production mode uses the Redis server, while the test mode mocks queue interactions for testing the application.

.. envvar:: TS_REDIS_QUEUE_NAME

   (string) The name of arq queue the workers process.

.. envvar:: TS_GITHUB_APP_ID

   (string) The GitHub App ID for Times Square.

.. envvar:: TS_GITHUB_WEBHOOK_SECRET

   (secret string) The GitHub webhook secret for Times Square.

.. envvar:: TS_GITHUB_APP_PRIVATE_KEY

   (secret string) The GitHub App private key for Times Square.

.. envvar:: TS_ENABLE_GITHUB_APP

   (boolean, default: true) Enable the GitHub App integration.
