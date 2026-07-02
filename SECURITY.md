# Security Policy

## Supported Versions

| Version | Supported |
|---------|:---------:|
| latest  | ✅        |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue.**
2. Use the [GitHub Security Advisory](https://github.com/HKUDS/Vibe-Trading/security/advisories/new) to report privately.
3. Include steps to reproduce, potential impact, and any suggested fixes.

We will acknowledge your report within **5 business days** and work with you to resolve the issue.

## Scope

This policy applies to the [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) repository.

## Generated backtest code

Backtest runs may execute generated Python strategy code locally. Treat generated strategies as local code you review before running. The runner validates run directories and uses a narrow subprocess environment: it preserves OS/Python basics, proxy/certificate settings, allowed run-root configuration, and read-only market-data credentials needed by loaders, but it does not forward LLM provider keys, API server bearer tokens, shell-tool opt-ins, broker trading secrets, or live/advisory toggles by default.

The backtest subprocess is still network-capable so loaders can fetch public or user-authorized market data. Do not run untrusted generated strategies in an environment that exposes sensitive files, secret-bearing proxy variables, or network services you would not trust local code to access.

## Official channels & impersonation

Vibe-Trading is an open-source finance **research** tool. We will **never** ask you to
"verify", connect, or sign with a crypto wallet to join our community, claim an airdrop, or
unlock features — any such prompt is a scam.

- Our only official Discord is **https://discord.gg/6TdQnT5xcF** (the HKUDS community server,
  also linked from the README). Treat any other "Vibe-Trading" Discord as an impostor.
- If a Discord or website asks you to connect/sign a wallet for "verification", do not do it.
  If you already did, move your funds to a fresh wallet and revoke approvals (e.g. via
  [revoke.cash](https://revoke.cash)).

See the pinned security announcement in [Discussions](https://github.com/HKUDS/Vibe-Trading/discussions)
for the 2026-06-18 impostor-Discord incident.

## Disclosure

- Please do not publicly disclose the vulnerability until we have released a fix.
- We will credit reporters in the release notes (unless you prefer anonymity).
