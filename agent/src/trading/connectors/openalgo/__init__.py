"""OpenAlgo connector package.

Read-only access to a self-hosted OpenAlgo server (https://github.com/marketcalls/openalgo)
through its ``/api/v1`` REST API. One connector reaches whichever Indian broker the
OpenAlgo instance is logged in to. Order placement and cancellation are refused for
every profile; see ``README-classification.md``.
"""
