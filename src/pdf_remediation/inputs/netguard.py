"""Address classification shared by URL fetching (SSRF defence) and AI policy."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class BlockedURL(ValueError):
    pass


def resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedURL(f"Cannot resolve host '{host}'") from exc
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def is_internal(addr: ipaddress._BaseAddress) -> bool:
    return (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
            or addr.is_multicast or addr.is_unspecified)


def host_is_internal(host: str) -> bool:
    """True when every address the host resolves to is loopback or private."""
    addrs = resolve(host)
    return bool(addrs) and all(is_internal(a) for a in addrs)


def check_public_url(url: str, allow_private: bool) -> str:
    """Validate a user-supplied URL before fetching it. Returns the host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("Only http and https links are supported")
    if not parts.hostname:
        raise BlockedURL("The link has no host name")
    if parts.username or parts.password:
        raise BlockedURL("Links containing credentials are not accepted")
    if not allow_private:
        for addr in resolve(parts.hostname):
            if is_internal(addr):
                raise BlockedURL(
                    f"'{parts.hostname}' resolves to an internal address ({addr}). Internal links are blocked "
                    "unless PDFREM_ALLOW_PRIVATE_URLS=1 is set.")
    return parts.hostname
