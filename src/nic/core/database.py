import logging
import ssl as _ssl
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from prometheus_client import Gauge
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import QueuePool

from nic.config import settings

logger = logging.getLogger(__name__)


def _build_engine_args(url: str) -> tuple[str, dict[str, object]]:
    """Convert sslmode query param to asyncpg-compatible ssl connect_arg."""
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    connect_args: dict[str, object] = {}

    sslmode = params.pop("sslmode", [None])[0]
    if sslmode and sslmode != "disable":
        ctx = _ssl.create_default_context()
        # Only disable cert verification for localhost (dev)
        if sslmode in ("require", "prefer") and parts.hostname in ("localhost", "127.0.0.1"):
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
        elif sslmode == "verify-full":
            ctx.check_hostname = True
            ctx.verify_mode = _ssl.CERT_REQUIRED
        # Load custom CA certificate if configured
        if settings.db_ssl_ca:
            ctx.load_verify_locations(settings.db_ssl_ca)
        connect_args["ssl"] = ctx
    elif parts.hostname not in ("localhost", "127.0.0.1", None):
        logger.warning(
            "Non-localhost DB without sslmode set. Set ?sslmode=verify-full in NIC_DATABASE_URL for production TLS."
        )

    # Statement timeout for asyncpg (seconds)
    connect_args["command_timeout"] = 30

    clean_query = urlencode({k: v[0] for k, v in params.items()}) if params else ""
    clean_url = urlunsplit(parts._replace(query=clean_query))
    return clean_url, connect_args


_url, _connect_args = _build_engine_args(settings.database_url)

engine = create_async_engine(
    _url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# --- Connection pool monitoring ---

_pool_checked_out = Gauge("db_pool_checked_out", "Number of connections currently checked out from pool")
_pool_checked_in = Gauge("db_pool_checked_in", "Number of connections currently available in pool")
_pool_overflow = Gauge("db_pool_overflow", "Number of overflow connections currently in use")


def _get_queue_pool() -> QueuePool:
    """Get the engine's pool, asserting it is a QueuePool."""
    pool = engine.sync_engine.pool
    assert isinstance(pool, QueuePool)  # noqa: S101
    return pool


def _update_pool_gauges() -> None:
    """Refresh all pool gauges from the current pool state."""
    pool = _get_queue_pool()
    _pool_checked_out.set(pool.checkedout())
    _pool_checked_in.set(pool.checkedin())
    _pool_overflow.set(pool.overflow())


@event.listens_for(engine.sync_engine, "checkout")
def _on_checkout(dbapi_conn: object, connection_record: object, connection_proxy: object) -> None:
    _update_pool_gauges()


@event.listens_for(engine.sync_engine, "checkin")
def _on_checkin(dbapi_conn: object, connection_record: object) -> None:
    _update_pool_gauges()


def get_pool_status() -> dict[str, int]:
    """Return current pool status for health checks."""
    pool = _get_queue_pool()
    return {
        "pool_size": pool.size(),
        "checked_out": pool.checkedout(),
        "checked_in": pool.checkedin(),
        "overflow": pool.overflow(),
    }
