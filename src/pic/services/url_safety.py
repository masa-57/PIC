"""Utilities for validating externally supplied image URLs."""

import asyncio
import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_ALLOWED_URL_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def _normalize_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _parse_ip_literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def is_forbidden_ip_address(ip: IPAddress) -> bool:
    """Return True when an IP address should never be fetched by URL ingest."""
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def validate_url_target(url: str) -> SplitResult:
    """Validate URL syntax and reject obviously unsafe local/private targets."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise ValueError("Only http:// and https:// image URLs are allowed")
    if parsed.hostname is None:
        raise ValueError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")

    hostname = _normalize_host(parsed.hostname)
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith((".localhost", ".local")):
        raise ValueError(f"URL host '{parsed.hostname}' is not allowed")

    ip_address = _parse_ip_literal(hostname)
    if ip_address is not None and is_forbidden_ip_address(ip_address):
        raise ValueError(f"URL host '{parsed.hostname}' is not allowed")

    return parsed


async def resolve_public_ips(url: str) -> tuple[IPAddress, ...]:
    """Resolve a URL hostname and reject any hop that targets non-public IPs."""
    parsed = validate_url_target(url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("URL must include a hostname")

    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc

    try:
        addr_info = await asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"Could not resolve URL host '{hostname}'") from exc

    resolved_ips: list[IPAddress] = []
    for family, _, _, _, sockaddr in addr_info:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        resolved_ips.append(ipaddress.ip_address(sockaddr[0].split("%", 1)[0]))

    if not resolved_ips:
        raise ValueError(f"Could not resolve URL host '{hostname}'")

    forbidden_ips = sorted({str(ip) for ip in resolved_ips if is_forbidden_ip_address(ip)})
    if forbidden_ips:
        raise ValueError(f"URL host '{hostname}' resolves to a non-public address: {', '.join(forbidden_ips)}")

    return tuple(resolved_ips)
