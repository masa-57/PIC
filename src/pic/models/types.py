"""Custom SQLAlchemy types for asyncpg compatibility."""

from asyncpg.types import BitString
from sqlalchemy import TypeDecorator
from sqlalchemy.dialects.postgresql import BIT


class AsyncpgBIT(TypeDecorator[str]):
    """BIT type that auto-converts between Python str and asyncpg BitString.

    asyncpg requires BitString objects for BIT columns, but our code (and
    hex_to_bitstring()) works with plain '01' strings. This decorator handles
    the conversion transparently so call sites don't need asyncpg imports.
    """

    impl = BIT
    cache_ok = True

    def __init__(self, length: int | None = None) -> None:
        super().__init__(length=length)

    def process_bind_param(self, value: str | BitString | None, dialect: object) -> BitString | None:
        if value is None:
            return None
        if isinstance(value, BitString):
            return value
        return BitString(value)

    def process_result_value(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, BitString):
            result: str = value.as_string().replace(" ", "")
            return result
        return str(value)
