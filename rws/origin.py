"""Validate explicit browser origins; forwarded headers never configure trust."""

import re
from urllib.parse import urlsplit


def normalize_web_origin(value, allow_loopback=True):
    message = "Studio URL must be an HTTP loopback or HTTPS Tailscale origin without credentials, query or path."
    if not isinstance(value, str) or not value or re.search(r"[\s\x00-\x1f\x7f?#]", value):
        raise ValueError(message)
    try:
        address = urlsplit(value)
        hostname, port = address.hostname, address.port
    except ValueError:
        raise ValueError(message) from None
    if address.username is not None or address.password is not None or address.path not in ("", "/"):
        raise ValueError(message)
    if not hostname or not re.fullmatch(r"[a-z0-9.-]+", hostname):
        raise ValueError(message)
    if ":" in address.netloc and not re.fullmatch(r"[^:]+:[1-9][0-9]{0,4}", address.netloc):
        raise ValueError(message)
    local = allow_loopback and address.scheme == "http" and hostname in ("127.0.0.1", "localhost")
    tailscale = address.scheme == "https" and re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+ts\.net", hostname)
    if not (local or tailscale) or (port is not None and not 1 <= port <= 65535):
        raise ValueError(message)
    default_port = 443 if address.scheme == "https" else 80
    authority = hostname + (":" + str(port) if port is not None and port != default_port else "")
    return address.scheme + "://" + authority
