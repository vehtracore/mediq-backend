import ipaddress
import os

from slowapi import Limiter
from slowapi.util import get_remote_address


def _truthy_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _normalise_ip(candidate: str | None) -> str | None:
    if not candidate:
        return None

    value = candidate.strip()
    if not value:
        return None

    # Header values may include a port. Handle IPv4 host:port and bracketed IPv6.
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        value = value.rsplit(":", 1)[0]

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def get_client_address(request) -> str:
    """
    Rate-limit key function.

    Render terminates TLS/proxy traffic before the app, so request.client can
    be the proxy unless forwarded headers are honoured. TRUST_PROXY_HEADERS is
    enabled by default for this deployment; set it false if the app is exposed
    directly without a trusted proxy.
    """
    if _truthy_env("TRUST_PROXY_HEADERS", default=True):
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            for candidate in forwarded_for.split(","):
                normalised = _normalise_ip(candidate)
                if normalised:
                    return normalised

        for header_name in ("cf-connecting-ip", "x-real-ip"):
            normalised = _normalise_ip(request.headers.get(header_name))
            if normalised:
                return normalised

    return get_remote_address(request)


limiter = Limiter(key_func=get_client_address)
