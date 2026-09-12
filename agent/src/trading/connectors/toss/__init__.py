"""Toss Securities (토스증권) trading connector.

Read-only account/holdings/quote/history access via the official Toss Invest
Open API (OAuth2 client-credentials token, no third-party SDK required). A
``broker_sdk`` transport for Korean (KRX) and US equities.

Toss Securities' Open API launched in 2026 and, like Trading 212, exposes no
sandbox and no verifiable paper/live discriminator — every credentialed call
reaches the operator's real brokerage account. Order placement is therefore
disabled for every profile, following the Trading 212 precedent.
"""
