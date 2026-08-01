from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    pass


def validate_remote_url(url: str, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port:
        raise UnsafeURL("only HTTPS URLs without credentials or explicit ports are accepted")
    host = parsed.hostname.lower().rstrip(".")
    if allowed_hosts and host not in {item.lower().rstrip(".") for item in allowed_hosts}:
        raise UnsafeURL(f"host is not in the provider allowlist: {host}")
    # The desktop runtime may expose provider DNS through the controlled
    # 198.18.0.0/15 egress range. A strict provider host allowlist plus TLS
    # still prevents an arbitrary-host SSRF in that environment.
    _reject_private_host(host, allow_controlled_egress=bool(allowed_hosts))
    return parsed.geturl()


def _reject_private_host(host: str, *, allow_controlled_egress: bool = False) -> None:
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise UnsafeURL("private or reserved address is not allowed")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeURL(f"could not resolve download host: {host}") from exc
    for info in infos:
        resolved = info[4][0]
        try:
            address = ipaddress.ip_address(resolved)
        except ValueError:
            continue
        controlled = address.version == 4 and address in ipaddress.ip_network("198.18.0.0/15")
        if address.version == 6 and int(address) >> 32 == 0xFFFF0000:
            controlled = ipaddress.ip_address(int(address) & 0xFFFFFFFF) in ipaddress.ip_network("198.18.0.0/15")
        if allow_controlled_egress and controlled:
            continue
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise UnsafeURL("download host resolves to a private or reserved address")
