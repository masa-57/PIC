"""Lightweight hash utilities that do not require ML dependencies (torch, etc.)."""


def hex_to_bitstring(hex_hash: str, bit_length: int = 256) -> str:
    """Convert a hex-encoded hash to a binary bitstring for PostgreSQL BIT type."""
    return bin(int(hex_hash, 16))[2:].zfill(bit_length)
