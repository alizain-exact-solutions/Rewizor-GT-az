"""Shared database connection helper.

Supports two configuration modes:

* ``DATABASE_URL`` — single connection string (preferred on Fly.io / Heroku
  style deployments).
* ``DB_HOST``/``DB_NAME``/``DB_USER``/``DB_PASSWORD``/``DB_PORT`` — discrete
  vars for local docker-compose.
"""

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as _PgConnection

logger = logging.getLogger(__name__)


def get_connection() -> _PgConnection:
    """Open a new psycopg2 connection.

    Prefers ``DATABASE_URL`` when set (Fly.io injects this for attached
    Postgres); falls back to the discrete ``DB_*`` env vars.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


@contextmanager
def db_session() -> Iterator[_PgConnection]:
    """Open a connection, commit on clean exit, rollback on exception, always close."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
