#!/bin/bash
set -e

echo "Running database migrations..."

# Generate migration if no versions exist
if [ -z "$(ls -A app/migrations/versions/ 2>/dev/null)" ]; then
    echo "No migrations found — generating initial schema..."
    alembic revision --autogenerate -m "initial_schema"
fi

# Run all pending migrations
alembic upgrade head

echo "Migrations complete!"
