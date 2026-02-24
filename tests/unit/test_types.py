"""Unit tests for custom SQLAlchemy types."""

import pytest
from asyncpg.types import BitString

from pic.models.types import AsyncpgBIT


@pytest.mark.unit
class TestAsyncpgBIT:
    def setup_method(self) -> None:
        self.bit_type = AsyncpgBIT(256)

    def test_bind_converts_str_to_bitstring(self) -> None:
        bits = "10101010" * 32  # 256-bit string
        result = self.bit_type.process_bind_param(bits, dialect=None)
        assert isinstance(result, BitString)

    def test_bind_passes_none_through(self) -> None:
        result = self.bit_type.process_bind_param(None, dialect=None)
        assert result is None

    def test_bind_passes_bitstring_through(self) -> None:
        bs = BitString("10101010")
        result = self.bit_type.process_bind_param(bs, dialect=None)  # type: ignore[arg-type]
        assert result is bs

    def test_result_converts_bitstring_to_str(self) -> None:
        bs = BitString("10101010")
        result = self.bit_type.process_result_value(bs, dialect=None)
        assert result == "10101010"
        assert isinstance(result, str)

    def test_result_passes_none_through(self) -> None:
        result = self.bit_type.process_result_value(None, dialect=None)
        assert result is None

    def test_result_strips_spaces_from_bitstring(self) -> None:
        """asyncpg BitString.as_string() returns space-separated groups."""
        bs = BitString("1010101011110000")
        raw = bs.as_string()
        assert " " in raw  # Confirm spaces exist
        result = self.bit_type.process_result_value(bs, dialect=None)
        assert " " not in result  # type: ignore[operator]

    def test_cache_ok_is_true(self) -> None:
        assert AsyncpgBIT.cache_ok is True
