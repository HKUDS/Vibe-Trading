# System Architecture

## Overview

Vibe-Trading Copy is a mobile-first quantitative strategy marketplace. Users create strategies via templates, backtest them, publish them, and others can copy-trade those strategies.

## High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Mobile Browser                              │
│                         (React 19 + Tailwind CSS)                        │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Market-    │  │   Strategy   │  │   Strategy   │  │   My Copy    │ │
│  │    place     │  │   Creation   │  │    Detail    │  │   Trades     │ │
│  │  (Browse)    │  │  (Templates) │  │  (Results)   │  │  (Dashboard) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS / REST / SSE
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            Backend API (FastAPI)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Strategy   │  │   Backtest   │  │  CopyTrade   │  │    User      │ │
│  │   Module     │  │   Module     │  │   Module     │  │   Module     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                                          │
│  DDD Layers: Domain → Application → Infrastructure → Interface           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌──────────────────────┐      ┌──────────────────────┐
        │   SQLite Database    │      │ Vibe-Trading Agent   │
        │  (strategies,        │      │  (backtest engine)   │
        │   copy_trades)       │      │                      │
        └──────────────────────┘      │  ┌────────────────┐  │
                                      │  │ Multi-Market   │  │
                                      │  │ Backtest Eng.  │  │
                                      │  │ (A-share,      │  │
                                      │  │  Crypto, etc.) │  │
                                      │  └────────────────┘  │
                                      └──────────────────────┘
```

## Module Boundaries

### Strategy Module
- **Domain**: `Strategy` entity, `StrategyTemplate` value object, `Signal` value object
- **Application**: `CreateStrategy`, `RunBacktest`, `PublishStrategy`, `ListStrategies`
- **Infrastructure**: `StrategyRepository` (SQLite), `BacktestEngineAdapter` (Vibe-Trading), `TemplateCompiler`
- **Interface**: REST endpoints `/strategies/*`

### CopyTrade Module
- **Domain**: `CopyTrade` entity, `Follower` value object
- **Application**: `FollowStrategy`, `UnfollowStrategy`, `GetMyCopyTrades`
- **Infrastructure**: `CopyTradeRepository` (SQLite), `SignalDispatcher`
- **Interface**: REST endpoints `/copy-trades/*`

### Backtest Module (cross-cutting)
- **Application**: `RunBacktest` command (orchestrates Strategy + CopyTrade)
- **Infrastructure**: `BacktestEngineAdapter` wraps Vibe-Trading's backtest runners
- **Interface**: REST endpoint `/backtests/{id}` with SSE streaming for progress

## Data Flow

### Strategy Creation Flow
```
User selects template → fills params → frontend validates (Zod)
  → POST /strategies → Application:CreateStrategy
  → Domain:Strategy.create(template, params)
  → Infrastructure:StrategyRepository.save()
  → Application:RunBacktest (async)
  → Infrastructure:BacktestEngineAdapter.run(strategy_config)
  → Vibe-Trading backtest engine
  → Returns BacktestResult
  → SSE stream progress to frontend
  → Frontend renders BacktestChart (ECharts)
```

### Copy Trade Flow
```
User browses marketplace → clicks "Copy"
  → POST /copy-trades → Application:FollowStrategy
  → Domain:CopyTrade.create(strategy_id, user_id, allocation)
  → Infrastructure:CopyTradeRepository.save()
  → SignalDispatcher subscribes to strategy signals
  
When strategy generates signal:
  → SignalDispatcher.notify(followers)
  → Application:ExecuteCopyTrade(signal, allocation)
  → Infrastructure:Notify follower (push notification / SSE)
  → Frontend "My Copy Trades" updates in real-time
```

## Technology Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Mobile-first UI | React 19 + Tailwind | Existing Vibe-Trading stack, fast iteration |
| State Management | Zustand | Simpler than Redux, good for mobile UX |
| Charts | ECharts v6 | Already used by Vibe-Trading, feature-rich |
| Backend | FastAPI + Pydantic | Existing stack, auto-generated OpenAPI docs |
| Database | SQLite (dev) / PostgreSQL (prod) | Zero-config for demo, easy to migrate |
| ORM | SQLAlchemy 2.0 | Async support, type-safe |
| Migrations | Alembic | Standard for SQLAlchemy |
| Backtest Engine | Vibe-Trading native | Already multi-market, battle-tested |
| Auth | API Key (dev) / JWT (prod) | Simple for demo, scalable |
| Real-time | Server-Sent Events | Simpler than WebSockets for one-way updates |
