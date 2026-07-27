# Vibe-Trading 분석 보고서

> 세션 분석 통합본 (2026-07, Part 21–27 잔여 딥 포함).  
> 범위: 아키텍처·백테스트·런타임·UI·라이브 + 이전에 애매했던 전 패키지.  
> 깊이 범례: **딥** = 계약·흐름·모듈 단위 · **맵** = 폴더·역할 · **카탈로그** = 목록만(본문 전수 제외).

관련 캔버스(IDE): `~/.cursor/projects/.../canvases/*.canvas.tsx`  
지식 그래프: `graphify-out/GRAPH_REPORT.md`

---

## 0. 목차

| Part | 주제 | 깊이 |
|------|------|------|
| 1 | 프로젝트 정체·전체 아키텍처 | 맵→딥 |
| 2 | `agent/src` 패키지 맵 | 맵 |
| 3 | tools · skills · memory · goal | 딥(패키지) |
| 4 | Skills 카탈로그 (88) | 맵 |
| 5 | 백테스트 패키지 전체 | 맵→딥 |
| 6 | `_execute_bars` · ChinaA · Composite | 딥 |
| 7 | loaders base + tushare | 딥 |
| 8 | `_align` · Crypto funding/liq | 딥 |
| 9 | SignalEngine · AST · auto fallback | 딥 |
| 10 | BacktestConfigSchema · subprocess Runner | 딥 |
| 11 | AgentLoop · SessionService | 딥 |
| 12 | FastAPI `api/` | 맵→딥 |
| 13 | live/ · trading/ | 맵→딥 |
| 14 | swarm/ | 맵→딥 |
| 15 | frontend/src (라우트·SSE) | 맵→딥 |
| 16 | 나머지 engines | 맵→딥 |
| 17 | loaders 전체 · optimizers · metrics · validation | 맵→딥 |
| 18 | factors / Alpha Zoo | 맵 |
| 19 | CLI · MCP | 맵→딥 |
| 20 | 폴더 구조 | 맵 |
| **21** | **providers · config · security · 루트 유틸** | **딥** |
| **22** | **channels · channelsui · scheduled_research** | **딥** |
| **23** | **shadow_account · strategy_store · hypotheses** | **딥** |
| **24** | **trading connectors 12종** | **딥** |
| **25** | **백테스트 잔여 (benchmark…loaders·options)** | **딥** |
| **26** | **frontend 컴포넌트 · CLI slash · agent/skills** | **딥** |
| **27** | **wiki · CI · Docker · packaging** | **딥** |
| **28** | **카탈로그 전수 (skills/alphas/swarm/channels/tests)** | **카탈로그** |
| A | 남은 초미세 잔여 · 읽는 순서 | — |

---

## 1. 프로젝트 정체 · 전체 아키텍처

### 어떻게 분석했나
- 레포 클론 후 `pyproject.toml` / README / 패키지 루트(`agent/`) 확인.
- Graphify AST 그래프 생성 → god nodes·커뮤니티로 허브 파악.
- 진입점(CLI / FastAPI `:8899` / React `:5899` / MCP / IM) → 오케스트레이션 → 실행 레이어로 분해.

### 결론
- **정체**: 자연어 금융 리서치 에이전트. ReAct 루프 + 도구(~60) + 스킬(88) + 멀티마켓 백테스트 + (옵션) 라이브.
- **진짜 코어**: `src/agent` (특히 `loop.py`) + `src/tools` + `backtest/`. Skills는 플레이북.
- **흐름**: Surfaces → `SessionService` → `AgentLoop` → Tools → (무거운 경로) `backtest.runner` 서브프로세스 → artifacts → SSE/UI.

### 핵심 경로
- `agent/src/agent/loop.py`
- `agent/src/session/service.py`
- `agent/backtest/runner.py`
- `agent/api_server.py`

---

## 2. `agent/src` 패키지 맵

### 어떻게 분석했나
- `agent/src/*` 디렉터리 전수 목록화, 패키지별 역할 한 줄 매핑.
- 이후 Part 11–19에서 개별 딥다이브로 확장.

### 패키지 역할 요약

| 패키지 | 역할 |
|--------|------|
| `agent/` | ReAct 루프 |
| `session/` | 세션·JSONL·FTS·SSE |
| `api/` | HTTP 라우트 |
| `tools/` | 실행 도구 |
| `skills/` | SKILL.md 플레이북 88 |
| `memory/` · `goal/` · `hypotheses/` | 연구 상태 |
| `swarm/` | 멀티에이전트 |
| `factors/` | Alpha Zoo |
| `live/` · `trading/` | 실거래 |
| `channels/` | IM |
| `providers/` · `config/` · `core/` | LLM·설정·Runner |
| `shadow_account/` · `strategy_store/` | 섀도우·전략 저장 |

---

## 3. tools · skills · memory · goal (+ `agent/SKILL.md`)

### 어떻게 분석했나
- `src/tools/` 파일 목록·도구명 inventory.
- `src/memory/`(3), `src/goal/`(5) 파일 단위 읽기.
- `agent/SKILL.md` = MCP/ClawHub 매니페스트 vs `src/skills/*/SKILL.md` 구분.

### 결론
- **Tools**: `build_registry()`가 BaseTool 자동 발견; backtest/swarm/live/data/file 등.
- **Memory**: `PersistentMemory` → `~/.vibe-trading/memory/` (opt-in lifecycle).
- **Goal**: SQLite `GoalStore`; live-execution 목표 거부; 루프 continuation과 연동.
- **SKILL.md(루트)**: 외부 MCP 클라이언트가 보는 54-tool 카탈로그. 내부 스킬 디렉터리와 다름.

---

## 4. Skills 카탈로그 (88)

### 어떻게 분석했나
- `src/skills/*` 디렉터리 분류(analysis / strategy / data-source / tool / asset-class / flow / crypto / research / risk).
- `tushare` 스킬 references 규모(~232) 인지. 개별 SKILL 전문 88개 전부는 읽지 않음(**맵**).

### 결론
- 스킬 = 에이전트에게 주는 플레이북(`load_skill`).
- 코어 로직을 대체하지 않음.

---

## 5. 백테스트 패키지 (`agent/backtest/`)

### 어떻게 분석했나
- `runner` → loader → `SignalEngine.generate` → `_align` → engine → metrics/run_card 파이프라인 추적.
- engines / loaders / optimizers / validation / run_card 맵.

### 파이프라인
```
safe_run_dir → config schema → AST sandbox(signal_engine.py)
  → fetch_data_map (+ fallback) → generate → _align(shift-1)
  → _execute_bars → metrics / artifacts / run_card
```

---

## 6. `_execute_bars` · ChinaA · Composite

### 어떻게 분석했나
- `engines/base.py` 바 루프 순서·주석 의도 라인 단위.
- `china_a.py` / `composite.py` 오버라이드·위임 비교.

### `_execute_bars` 한 바 순서
1. open equity로 사이즈 기준
2. 청산/플립 먼저 (순서 독립)
3. 신규 open 계획 → 자금 부족 시 **공통 scale** 이분탐색 → 일괄 체결
4. `on_bar` (펀딩/스왑/청산)
5. close equity 스냅샷
6. EOB 강제청산 + 터미널 equity 보정

### ChinaA vs Composite
| | ChinaA | Composite |
|--|--------|-----------|
| 상태 | 자기 capital/positions | **공유** 장부 |
| 규칙 | T+1·한도·100주·인지세 | 서브엔진 = 룰북만 |
| T+1 | 자체 `can_execute` | Composite가 가로챔 |
| 펀딩/스왑 | 없음 | Composite `on_bar` |

---

## 7. loaders `base` + `tushare`

### 어떻게 분석했나
- `DataLoaderProtocol`, `validate_ohlc`, retry/budget, opt-in parquet cache.
- `tushare.py` 라우팅: ETF/`fund_daily`, 지수/`index_daily`, HK/`hk_daily`, 주식/`daily`, 분봉/`stk_mins`.

### 결론
- 모든 fetch는 최종적으로 `validate_ohlc`로 수렴 (`fetch_data_map`).
- US/crypto는 tushare 스킵 → 다른 로더/fallback.

---

## 8. `_align` · CryptoEngine `on_bar`

### 어떻게 분석했나
- `_align` 133–229행: 통합 캘린더 → close 격자 → 심볼 캘린더에서 shift(1) → ffill → optimizer → `Σ|w|≤1`.
- `crypto.py` + `_market_hooks.calc_crypto_funding_fee` / `check_crypto_liquidation`.

### 수식 요약
- **Funding**: `fee = size × mark × rate × direction` ; UTC `{0,8,16}` 또는 일 1회 fallback ; `capital -= fee`
- **Liq**: `(margin + unrealized) ≤ maint_margin` (OKX식 tier); lev≤1이면 스킵

### 인과성
- t바 시그널 → `_align` shift → **t+1 open** 체결.

---

## 9. SignalEngine · AST · auto fallback

### 어떻게 분석했나
- 계약: `strategy-generate/SKILL.md`, `scaffold_signal_engine` 템플릿, runner `_validate_*`.
- AST 2단: import-time 구조 검사 + runtime-reachable scrub (VT-001).
- `FALLBACK_CHAINS` / `_fetch_auto` / `fetch_data_map`.

### SignalEngine 계약
```python
class SignalEngine:  # 무인자 생성
    def generate(self, data_map) -> dict[str, pd.Series]:  # [-1,1], 동일 index
```

### AST
- 차단: network/subprocess/eval/os.system/쓰기 open/`getattr(os,…)`
- 한계: 진짜 OS 샌드박스 아님; 스킬 예제의 미도달 `requests`는 허용 가능.

### Fallback
- `auto`: 시장 그룹 → `resolve_loader` → missing만 체인.
- `local`/`qveris`: 네트워크로 조용히 안 넘어감.

---

## 10. BacktestConfigSchema · subprocess Runner

### 어떻게 분석했나
- `BacktestConfigSchema` pydantic 필드·validator.
- `backtest_tool` → `src/core/runner.py` `Runner(timeout=300)`.

### 스키마
- **검사**: codes, dates, source, interval, engine, initial_cash(>0), fundamental_fields, event_feeds.
- **`extra="allow"`**: leverage/slippage/optimizer/validation/commission* 등은 엔진이 `config.get`.

### 서브프로세스
- cmd: `python backtest/runner.py <run_dir>`, cwd=`agent/`
- env allowlist (시세 키·proxy 유지, LLM/브로커 시크릿 차단)
- ephemeral HOME (cache/data-bridge/qveris만 symlink)
- Docker에서만 UID drop + RLIMIT; 항상 AST는 on
- 타임아웃 300s; artifacts 수집

---

## 11. AgentLoop · SessionService

### 어떻게 분석했나
- `loop.py` `run()` iteration·도구 배치·압축 5단·goal continuation·이벤트 emit.
- `SessionService.send_message` → Attempt → ThreadPool `AgentLoop` → EventBus.
- Store: `session.json` + `messages.jsonl`; 검색: SQLite FTS5.

### ReAct 요약
```
build messages (ContextBuilder + skills + memory recall)
→ stream_chat (+ tools)
→ tool_calls? → parallel readonly / serial write → continue
→ text-only → (goal continuation?) → success/fail/cancel
```

### SSE 이벤트 예
`text_delta`, `tool_call`, `tool_result`, `attempt.*`, `goal.updated`, `swarm.event`, …

---

## 12. FastAPI `api/`

### 어떻게 분석했나
- `api_server.py` 조립 순서·미들웨어.
- 각 `*_routes.py` method/path/auth 표로 정리.

### 조립
`register_runs` → sessions → system → settings → uploads → channels → qveris → swarm → live → alpha → auth → scheduled

### 축
| 영역 | SessionService? |
|------|-----------------|
| `/sessions*` · goal · SSE | 예 |
| `/runs*` | 디스크만 |
| `/swarm*` | SwarmRuntime 단독 |
| `/live*` · mandate | 예(이벤트 relay) + LiveRunner |
| `/alpha*` | 인메모리 job |

인증: `require_auth` / SSE는 `POST /auth/sse-ticket` + ticket.

---

## 13. live/ · trading/

### 어떻게 분석했나
- mandate 모델·commit(에이전트 쓰기 불가)·OrderGuard/SDK gate 순서.
- LiveRunner tick: halt → mandate → reconcile → agent.
- connectors 12종 + transport(paper/live, mcp/sdk/tws).

### 실주문 게이트 (요약)
mandate 유효 → HALT 없음 → intent → `check_mandate` → (옵션 advisory) → broker → audit/count

백테스트 경로와 **완전 분리** (시뮬은 mandate 안 탐).

---

## 14. swarm/

### 어떻게 분석했나
- YAML preset → `SwarmRun` → `SwarmRuntime` DAG 레이어 → `run_worker`.
- grounding: run 시작 1회 OHLCV prefetch → 전 워커 프롬프트.
- 메인 `AgentLoop`과 **별도 루프**; 연결은 `run_swarm` 도구(+ REST).

### 규모
- 번들 preset **30**.

---

## 15. frontend/src

### 어떻게 분석했나
- router 페이지·Zustand `agent`·`useSSE`·`api.ts`/`apiAuth.ts` 흐름.
- Agent 페이지: `?session=` + EventSource `replay=active` + RunCompleteCard.
- Runs/Reports/AlphaZoo(별도 EventSource) 맵.

### 결론
- 채팅 실시간 = 세션 SSE; Runtime live status = 폴링; Alpha = 독립 스트림.

---

## 16. 나머지 engines

### 어떻게 분석했나
- forex / global_equity / china·global futures / futures_base / india / options_portfolio를 Base 대비 표로 비교 (이미 분석한 ChinaA·Composite·Crypto 제외).

### 요지
| 엔진 | 특징 |
|------|------|
| Forex | lev 100, commission 0, pip 스프레드, on_bar swap |
| GlobalEquity | US/HK lot·fee 분기, can_execute 항상 True |
| ChinaFutures | 승수·품목 증거금·涨跌停 |
| GlobalFutures | 고정 ~10x, USD/계약, 지수 한도 |
| India | T+1·서킷·세금 스택 |
| Options | BaseEngine 밖 BS 일별 루프 |

---

## 17. loaders 전체 · optimizers · metrics · validation

### 어떻게 분석했나
- 등록 로더 23종 name/markets/auth/한 줄 specialty.
- optimizer 5: equal_vol / risk_parity / mean_variance / max_div / turnover_aware.
- `calc_metrics` 키 · `calc_bars_per_year`.
- validation: monte_carlo / bootstrap / walk_forward / `run_validation`.

---

## 18. factors / Alpha Zoo

### 어떻게 분석했나
- AST `Registry` 스캔 → `__alpha_meta__` → lazy `compute(panel)`.
- zoo: alpha101(101) + gtja191(191) + qlib158(154) + academic(12) + fundamental(4) ≈ **462**.
- 진입: CLI / API `/alpha/*` / tools / `ZooSignalEngine`; backtest는 `fund:*` 패널 주입.

---

## 19. CLI · MCP

### 어떻게 분석했나
- `cli.main` 대화형(SessionStore 직접) vs `_legacy` 서브커맨드 vs `serve`→api_server.
- `mcp_server.py` 54 `@mcp.tool` → 대부분 `build_registry().execute`; swarm만 `load_swarm_agent_config`.
- `agent/SKILL.md` = 외부용 MCP 카탈로그.

### 엔트리
- `vibe-trading` → CLI  
- `vibe-trading-mcp` → MCP  
- `serve` → FastAPI  

---

## 20. 폴더 구조

### 어떻게 분석했나
- 레포·`agent/`·`agent/src/`·`frontend/` 트리 depth 1–2 스캔 + 역할 주석.

```
Vibe-Trading/
├── agent/          # Python 본체
│   ├── api_server.py · mcp_server.py · SKILL.md
│   ├── backtest/ · cli/ · src/ · tests/
├── frontend/       # React UI
├── wiki/ · scripts/ · tools/ · assets/
└── pyproject.toml
```

런타임 홈(레포 밖): `~/.vibe-trading/` (sessions, memory, cache, mandate…).

---

## 21. providers · config · security · 루트 유틸

### 어떻게 분석했나
- `providers/` ChatLLM·build_llm·content_filter·Codex OAuth 전 파일.
- `config/` load_agent vs load_runtime vs load_swarm, AgentConfig vs EnvConfig.
- `security/` scanner(경고만)·network SSRF·workspace path.
- `preflight.py` · `market_data.py` · `ui_services.py` · `utils/media_decode.py`.

### 결론
- LLM: dotenv → EnvConfig → provider env를 `OPENAI_*`에 미러 → LangChain invoke/stream.
- Content filter: finish_reason 감지 → 최대 10회 skip → circuit breaker.
- **세션 MCP 주입 기본 금지** (`ALLOW_SESSION_MCP_SERVERS` opt-in).
- Swarm 설정 파일은 `VIBE_TRADING_SWARM_AGENT_CONFIG` / `swarm-agent.json` 별도 해석.
- Scanner는 삭제 없이 경고+토큰 defang만.

---

## 22. channels · channelsui · scheduled_research

### 어떻게 분석했나
- BaseChannel → MessageBus → ChannelRuntime → SessionService; Manager는 outbound.
- 어댑터 16종(+websocket) 프로토콜 한 줄씩.
- channelsui = WebSocket/WebUI 게이트웨이만.
- scheduled_research: JSON store + executor tick → 새 세션 enqueue.

### 결론
```
IM event → _handle_message → inbound queue
  → ChannelRuntime (pairing / /new)
  → SessionService.send_message → poll assistant
  → outbound → ChannelManager → adapter.send
```
- **AgentLoop→bus 실시간 스트림은 IM에 미연결** (최종 답변 폴링).
- 채널 auto-start / 스케줄러 **기본 OFF** (env 플래그).
- WebSocket은 동일 bus + channelsui hydrate.

---

## 23. shadow_account · strategy_store · hypotheses

### 어떻게 분석했나
- Shadow: extract→codegen→backtest_tool→report→scan 전체.
- SDM: SqliteStrategyStore · DecayEvaluator · sdm_* 도구; **record_bench를 호출하는 도구 없음** 갭 확인.
- Hypotheses JSON + autopilot 4도구 + link_backtest.

### 결론
| 축 | 저장 | 도구 |
|----|------|------|
| Shadow | shadow_accounts/runs/reports | extract/run/render/scan |
| SDM | strategy_store.db | register/status/decay_scan |
| Hypotheses | hypotheses.json | create/update/search/link + autopilot |

세 축은 `hypothesis_id`·run_dir로 **느슨 연결**.

---

## 24. trading connectors 12종

### 어떻게 분석했나
- `service.py` transport 분기 + 브로커별 profiles/sdk/classification.
- tap_forward는 **Alpaca만**.

### 요약 표

| 브로커 | Transport | place via service |
|--------|-----------|-------------------|
| IBKR | local_tws / mcp RO | **불가** |
| Robinhood | remote_mcp | **불가**(별도 MCP gate) |
| Alpaca/Binance/OKX/Tiger/Futu/MT5 | broker_sdk | paper 직행 / live mandate |
| Longbridge | broker_sdk | **paper만** |
| Dhan/Shoonya | broker_sdk | **paper 로컬 시뮬만** |
| Trading212 | broker_sdk | **항상 거부** |

선택 프로필: `~/.vibe-trading/trading-connections.json`.

---

## 25. 백테스트 잔여 딥

### 어떻게 분석했나
- benchmark / correlation / regime / risk_xray / rebalance_notes / run_card.
- options_portfolio 일 루프·Greeks·시그널 계약.
- optimizer 5 목적함수·제약.
- tushare_fundamentals + rsshub_events PIT/이벤트 계약.
- 전 등록 로더 interval·auth 표.

### 하이라이트
- **benchmark**: market 추론 티커 → loader → (비 local) yfinance 폴백.
- **regime**: \|ρ\| 엣지 밀도 + Schmitt 히스테리시스 (거래 시그널 아님).
- **risk_xray**: 순수 수치(가격+가중치), I/O 없음.
- **run_card**: schema 0.1, hashes, artifacts sha256, validation 복사.
- **options**: `generate`→ list of open/close legs; BS+smile; greeks.csv.
- **local/qveris**: 네트워크 폴백 금지.

---

## 26. frontend 컴포넌트 · CLI slash · agent/skills

### 어떻게 분석했나
- chat/charts/layout/common/settings 파일 단위 + Agent 조립도.
- Runtime/Settings/Correlation/AlphaZoo SSE/Compare 데이터 흐름.
- slash_router 전 명령; onboard/completer/stream.
- `agent/skills/` = mootdx 레퍼런스 1파일 (번들은 `src/skills`).

### 결론
- Agent: Zustand + useSSE → ThinkingTimeline / MessageBubble / Swarm / Mandate / RunnerStatus.
- AlphaZoo bench/compare: raw EventSource (Agent와 패턴 다름).
- Compare 페이지 = 백테스트 run A/B (AlphaZoo compare와 별개).
- CLI slash: help/model/memory/history/search/goal/swarm/skill/show/…; `/quit`→exit 2.
- `StreamRenderer`는 구현됐으나 **main에 아직 미연결**.

---

## 27. wiki · CI · Docker · packaging

### 어떻게 분석했나
- wiki 구조·wrangler·D1 analytics; GitHub Actions 3종; tools/ CI gates; scripts/dev; Dockerfile/compose; package-data.

### 결론
| 표면 | 역할 |
|------|------|
| wiki | Cloudflare Pages `vibetrading.wiki`, 정적+Functions |
| test.yml | grep gates + pytest + frontend build |
| wiki.yml / deploy | wiki 검증 / wrangler pages deploy |
| tools/ci_* | yaml.load·WorldQuant·utcnow·env-gate |
| scripts/dev | :8899+:5899 로컬 오케스트레이션 |
| Docker | 3-stage, vibe-sandbox, /live health |
| package-data | skills/** + swarm/presets/*.yaml + factors zoo |

---

## 28. 카탈로그 전수 기록 (한 장씩)

### 어떻게 분석했나
- `docs/catalog/_build_inventories.py`: 88개 `SKILL.md` frontmatter, 462개 `__alpha_meta__` AST, 30개 swarm YAML.
- `docs/catalog/_build_channels_tests.py`: 16 채널 어댑터 AST·프로토콜 노트, 315 `test_*.py` 도메인 맵.

### 산출물
| 파일 | 건수 |
|------|------|
| `docs/catalog/SKILLS.md` (+ json) | 88 |
| `docs/catalog/ALPHAS.md` (+ json) | 462 |
| `docs/catalog/SWARM_PRESETS.md` (+ json) | 30 |
| `docs/catalog/CHANNELS.md` | 16 |
| `docs/catalog/TESTS.md` | 315 |
| `docs/catalog/INDEX.md` | 인덱스 |

### 스킬 카테고리 분포 (요약)
analysis 22 · strategy 19 · data-source 10 · tool 10 · asset-class 9 · flow 8 · crypto 7 · research 2 · risk-analysis 1 (frontmatter 기준; uncategorized 가능).

### 알파 zoo 분포
alpha101 101 · gtja191 191 · qlib158 154 · academic 12 · fundamental 4 → **462**.

---

## A. 남은 초미세 잔여

카탈로그 **목록/메타/구조**는 전수 기록됨. 더 깊게 가려면 개별 선택만:

| 잔여 | 의미 |
|------|------|
| 스킬 본문 전체 튜토리얼 문단 | 설명은 frontmatter에 있음; references 대량(tushare 등)은 온디맨드 |
| 알파 `compute()` 구현 라인 | formula_latex + meta로 대체; 특정 id 감사 시 해당 py 열기 |
| 채널 서드파티 SDK 내부 | 우리 쪽 어댑터 계약은 CHANNELS.md |
| 테스트 assertion 전수 | TESTS.md는 파일 맵 |

→ **“안 읽은 장” 목록 작업은 완료.** 이후는 관심 id 하나 지정 딥.

---

## B. 권장 읽는 순서 (갱신)

1. Part 20 → 1 → 11–12 → 15/26  
2. Part 5–10 → 16 → 25  
3. Part 13 → 24  
4. Part 21–23 · 22 · 14 · 18–19 · 27  
5. **Part 28 + `docs/catalog/*`** (전수 표)

---

## C. 산출물 인덱스

| 종류 | 위치 |
|------|------|
| **이 문서** | `docs/analysis/REPORT.md` |
| **AI 핸드오프** | `docs/analysis/README.md` |
| **카탈로그** | `docs/analysis/catalog/` |
| Graphify | `graphify-out/GRAPH_REPORT.md` |
| 캔버스 | IDE canvases (architecture … analysis-report-index) |

---

*작성: 대화 세션 분석 통합 + Part 21–28. 애플리케이션 코드 변경 없음 — 문서화·카탈로그만.*
