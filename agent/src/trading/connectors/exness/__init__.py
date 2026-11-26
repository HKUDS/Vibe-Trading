"""Exness Trader API connector — hosted REST, ``broker_sdk`` transport.

Talks to the Exness Trader API (https://www.exness-api.com/) with an API key
plus a per-request Ed25519 signature. No local terminal is involved, so unlike
the MT5 connector this runs on any OS. Credentials live in
``~/.vibe-trading/exness.json`` or ``EXNESS_*`` environment variables.

Live-only by design: the API exposes no paper environment and no demo/real
discriminator (``AccountSettings`` carries currency, leverage, trade/account
status and execution mode only). Following the Robinhood/Scalable precedent the
connector therefore ships NO paper profile — every account is treated as real
money, and order placement routes through the live mandate gate and kill
switch, even when the key happens to point at a demo account.
"""
