# This Dockerfile has three stages:
#
# base-image
#   Updates the base Python image with security patches and common system
#   packages. This image becomes the base of all other images.
# install-image
#   Installs third-party dependencies (requirements/main.txt) into a virtual
#   environment. This virtual environment is ideal for copying across build
#   stages.
# runtime-image
#   - Copies the virtual environment into place.
#   - Runs as a non-root user.
#   - Sets up the entrypoint and port.

FROM python:3.13.2-slim-bookworm AS base-image

# Update system packages
COPY scripts/install-base-packages.sh .
RUN ./install-base-packages.sh && rm ./install-base-packages.sh

FROM base-image AS install-image

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /bin/uv

# Install some additional packages required for building dependencies.
COPY scripts/install-dependency-packages.sh .
RUN ./install-dependency-packages.sh

# Create a Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN uv venv /opt/venv

# Make sure we use the virtualenv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install the app's Python runtime dependencies
COPY requirements/main.txt ./requirements.txt
RUN uv pip install --compile-bytecode --verify-hashes --no-cache \
    -r requirements.txt

# Install the Python application.
COPY . /workdir
WORKDIR /workdir
RUN uv pip install --compile-bytecode --no-cache .

FROM base-image AS runtime-image

# Create a non-root user
RUN useradd --create-home appuser

# Copy the virtualenv
COPY --from=install-image /opt/venv /opt/venv

COPY scripts/start-api.sh /start-api.sh

# Copy the Alembic configuration and migrations, and set that path as the
# working directory so that Alembic can be run with a simple entry command
# and no extra configuration.
COPY --from=install-image /workdir/alembic.ini /app/alembic.ini
COPY --from=install-image /workdir/alembic /app/alembic
WORKDIR /app

# Make sure we use the virtualenv
ENV PATH="/opt/venv/bin:$PATH"

# Set environment variable for Alembic config; other variables are set
# via Kubernetes.
ENV TS_ALEMBIC_CONFIG_PATH="/app/alembic.ini"

# Switch to the non-root user.
USER appuser

# Expose the port.
EXPOSE 8080

# Run the application.
CMD ["/start-api.sh"]
