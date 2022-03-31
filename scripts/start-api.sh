#!/bin/bash

# Start up script for the API service (referenced by Dockerfile).

set -eu

times-square init
uvicorn timessquare.main:app --host 0.0.0.0 --port 8080
