"""Domain specialist sub-agents for the built-in agent loop.

Each specialist is a small hard-enforced tool whitelist plus a routing
description and a behavior prompt; the main agent delegates via the
``delegate_to_specialist`` tool and only decides "handle directly or hand to
a named specialist". The feature is gated by
``VIBE_TRADING_SPECIALISTS_ENABLED`` (default off).
"""

from src.specialists.loader import load_specialists, reset_specialists_cache
from src.specialists.models import FORBIDDEN_SPECIALIST_TOOLS, SpecialistSpec
from src.specialists.routing import specialist_routing_block

__all__ = [
    "FORBIDDEN_SPECIALIST_TOOLS",
    "SpecialistSpec",
    "load_specialists",
    "reset_specialists_cache",
    "specialist_routing_block",
]
