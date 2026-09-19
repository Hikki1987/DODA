"""NFR-PERF-003 follow-up — `doda.db`'s connection pool size/overflow are
now real, operator-tunable `Settings` fields (`db_pool_size`/
`db_max_overflow`) rather than SQLAlchemy's hard-coded defaults, after
`backend/scripts/load_test_ai_chat.py` measured real, significant
latency degradation under concurrent chat load with the defaults
(5 + 10 = 15 connections per process).

No real Postgres connection is opened here — `create_async_engine` only
builds the pool object; it connects lazily on first checkout. This test
proves the WIRING (Settings -> engine construction), not connectivity.
"""

from doda.config import Settings
from doda.db import _build_engine


def test_the_engine_pool_size_and_overflow_come_from_settings_not_a_hardcoded_default() -> None:
    settings = Settings(db_pool_size=23, db_max_overflow=7)
    engine = _build_engine(settings)
    try:
        assert engine.pool.size() == 23
        assert engine.pool._max_overflow == 7  # noqa: SLF001 — no public getter exists on QueuePool
    finally:
        engine.sync_engine.dispose()


def test_default_settings_reproduce_sqlalchemys_own_defaults_so_behavior_is_unchanged() -> None:
    """Prevents someone from "improving" the default later and silently
    changing production behavior for every deployment that never sets
    DODA_DB_POOL_SIZE/DODA_DB_MAX_OVERFLOW."""
    settings = Settings()
    engine = _build_engine(settings)
    try:
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10  # noqa: SLF001
    finally:
        engine.sync_engine.dispose()
