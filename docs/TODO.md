# Development Roadmap

## Phase 1: MVP Demo (Week 1-2)

### Backend
- [ ] FastAPI app skeleton (`main.py`, `config.py`, routers)
- [ ] Strategy domain model (Entity, Template, Signal)
- [ ] CopyTrade domain model (Entity, Follower)
- [ ] Strategy template definitions (YAML: moving_average_cross)
- [ ] Template compiler: YAML params → Vibe-Trading backtest config
- [ ] SQLite persistence layer (StrategyRepository, CopyTradeRepository)
- [ ] Backtest adapter: call Vibe-Trading agent API
- [ ] REST endpoints: `/strategies`, `/backtests`, `/copy-trades`
- [ ] SSE endpoint for backtest progress streaming
- [ ] Tests: unit + integration

### Frontend
- [ ] Mobile-first layout shell (bottom nav, responsive)
- [ ] Home page: strategy marketplace cards
- [ ] Strategy creation page: template selector + parameter form
- [ ] Strategy detail page: backtest results + ECharts chart
- [ ] My Copy Trades page: dashboard
- [ ] API client layer (typed fetch wrapper)
- [ ] Zustand stores (strategyStore, userStore)
- [ ] Tests: component + integration

### Infrastructure
- [ ] Docker Compose dev environment
- [ ] Makefile with standard commands
- [ ] Pre-commit hooks
- [ ] CI template (GitHub Actions)

## Phase 2: Polish (Week 3-4)

- [ ] 4 strategy templates (MA Cross, Grid, RSI, Breakout)
- [ ] Strategy search/filter (by market, by performance)
- [ ] Strategy ranking (by Sharpe, by followers)
- [ ] Signal history page
- [ ] Push notifications for new signals
- [ ] Dark mode toggle
- [ ] Error boundaries + loading states
- [ ] Performance optimization (lazy loading, code splitting)

## Phase 3: Community (Future)

- [ ] User authentication (OAuth / wallet login)
- [ ] Creator profiles + follower counts
- [ ] Strategy comments / ratings
- [ ] Creator revenue model
- [ ] Real exchange API integration
- [ ] Real-time signal execution (not just simulation)
