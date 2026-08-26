"""The cached db accessors hand their engine/connection to whichever thread asks next."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from appworld.apps.lib.models.db import (
    get_cached_db_engine,
    get_direct_cached_sqlite3_connection,
)


@pytest.fixture
def clear_db_caches():
    # Both accessors are process-global `lru_cache`s, so a leaked entry would let a later test reuse
    # this test's engine -- the same reason test_appworld.py clears them around each task.
    get_cached_db_engine.cache_clear()
    get_direct_cached_sqlite3_connection.cache_clear()
    yield
    get_cached_db_engine.cache_clear()
    get_direct_cached_sqlite3_connection.cache_clear()


def test_cached_engine_is_usable_from_another_thread(tmp_path, clear_db_caches):
    # Passes with or without the explicit `connect_args` -- SQLAlchemy's pysqlite dialect already
    # defaults `check_same_thread` to False for a file url. It guards the pin, so that a dialect
    # default change (or a switch to a pool that shares one connection) fails here rather than in a
    # concurrent run.
    db_path = str(tmp_path / "engine.db")
    engine = get_cached_db_engine(db_path)  # created on this thread
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    def query_on_worker() -> int:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one()

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(query_on_worker).result() == 1


def test_cached_direct_connection_is_usable_from_another_thread(tmp_path, clear_db_caches):
    # This one is the real regression test: it raises `sqlite3.ProgrammingError` without the fix,
    # because `sqlite3.connect` defaults `check_same_thread` to True.
    db_path = str(tmp_path / "direct.db")
    connection = get_direct_cached_sqlite3_connection(db_path)  # created on this thread
    connection.execute("SELECT 1")

    # Read-only on purpose: every thread shares this connection's single implicit transaction, so
    # writing through it is unsafe even with `check_same_thread=False`. See `get_direct_sqlite3_connection`.
    def query_on_worker() -> int:
        return connection.execute("SELECT 1").fetchone()[0]

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(query_on_worker).result() == 1
