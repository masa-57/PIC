"""Build the synchronous database URL Alembic uses."""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

LOCAL_HOSTS = ("localhost", "127.0.0.1", None)
STRICT_SSLMODES = {"verify-full", "verify-ca"}


def migration_url(url: str, ssl_ca: str = "") -> str:
    """Convert an asyncpg URL to psycopg2 with production-safe TLS defaults.

    Remote hosts get ``sslmode=verify-full`` unless the URL already asks for
    ``verify-full``/``verify-ca`` or explicitly opts out with ``sslmode=disable``
    (used by the docker compose ``db`` host).
    """
    # Explicit driver: SQLAlchemy 2.1 maps a bare postgresql:// to psycopg 3, which is not installed.
    sync_url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    parts = urlsplit(sync_url)
    params = parse_qs(parts.query)

    if parts.hostname not in LOCAL_HOSTS:
        sslmode = params.get("sslmode", [None])[0]
        if sslmode != "disable" and sslmode not in STRICT_SSLMODES:
            params["sslmode"] = ["verify-full"]
        if ssl_ca and sslmode != "disable":
            params["sslrootcert"] = [ssl_ca]

    query = urlencode({k: v[0] for k, v in params.items()}) if params else ""
    return urlunsplit(parts._replace(query=query))
