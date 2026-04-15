"""Shared database connection helper.

Every layer (API, services, repositories) opens its own short-lived psycopg2
connection. This module centralises the env-var configuration and provides
a context-manager-friendly factory so callers can ``with get_connection()``
and get automatic close/rollback on error.
"""

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as _PgConnection

logger = logging.getLogger(__name__)


def get_connection() -> _PgConnection:
    """Open a new psycopg2 connection using DB_* env vars.

    Caller owns the lifecycle; prefer :func:`db_session` for simple CRUD.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


@contextmanager
def db_session() -> Iterator[_PgConnection]:
    """Open a connection, commit on clean exit, rollback on exception, always close.

    Usage::

        with db_session() as conn:
            cur = conn.cursor()
            cur.execute(...)
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
