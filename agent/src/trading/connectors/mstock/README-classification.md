# mStock classification boundary

mStock is a plain REST broker, not a remote MCP broker. `scalable/classification.py`
exists to pin the safety class of remote MCP tool names before discovery can
expose them; mStock has no remote tool names and this first cut deliberately has
no SDK module or callable operations, so there is nothing for a Tier-2
classification map to key on.

Adding a `classification.py` now would invent operation names for an HTTP layer
that is intentionally out of scope. If the follow-up introduces local SDK-style
functions, follow the KIS and Upbit REST precedent: pin each verified read as
`READ`, pin every order-path operation as `WRITE`, and register the map in the
live registry so unknown operations fail closed.
