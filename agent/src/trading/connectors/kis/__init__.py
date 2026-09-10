"""Korea Investment & Securities (한국투자증권 KIS) trading connector.

Read-only and genuine broker-side paper account access via the official KIS
Developers REST API (OAuth2 client-credentials token, no third-party SDK
required). A ``broker_sdk`` transport for Korean equities (KRX: KOSPI/KOSDAQ).

Unlike Dhan/Upbit, KIS exposes a REAL structural paper/live discriminator:
paper (모의투자) and live (실전투자) accounts are reached through entirely
different hosts, so a paper-declared profile can never reach the live host.
"""
