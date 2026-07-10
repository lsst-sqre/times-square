FROM mcr.microsoft.com/devcontainers/python:1-3.14-bookworm

# graphviz for Sphinx diagram rendering in the docs build
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz \
    && rm -rf /var/lib/apt/lists/*

# uv manages all Python dependencies (see uv.lock / noxfile.py)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
