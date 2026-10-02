#!/bin/sh
set -eu

python - <<'PY'
import os
import time

import psycopg

settings = {
    "host": os.environ["SWB_DB_HOST"],
    "port": os.environ.get("SWB_DB_PORT", "5432"),
    "dbname": os.environ["SWB_DB_NAME"],
    "user": os.environ["SWB_DB_USER"],
    "password": os.environ["SWB_DB_PASSWORD"],
    "connect_timeout": 2,
}
for attempt in range(30):
    try:
        with psycopg.connect(**settings) as connection:
            connection.execute("SELECT 1")
        break
    except psycopg.OperationalError:
        if attempt == 29:
            raise SystemExit("Database did not become ready within 60 seconds")
        time.sleep(2)
PY

python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
