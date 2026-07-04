#!/bin/sh
# Applies pending Alembic migrations, then starts the given command.
# Fails loudly (set -e) if migrations fail — better to crash on startup
# than to run against a schema the code doesn't expect.
set -e

echo "Running migrations..."
alembic upgrade head

echo "Starting: $@"
exec "$@"
