<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <b>한국어</b> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading 로고"/>
</p>

<h1 align="center">Vibe-Trading: 당신의 개인 트레이딩 에이전트</h1>

<p align="center">
  <b>한 번의 명령으로 에이전트에 종합적인 트레이딩 역량을 더하세요</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://vibetrading.wiki/">웹사이트</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">문서</a> &nbsp;&middot;&nbsp;
  <a href="#-뉴스">뉴스</a> &nbsp;&middot;&nbsp;
  <a href="#-주요-기능">기능</a> &nbsp;&middot;&nbsp;
  <a href="#-섀도우-계정">섀도우 계정</a> &nbsp;&middot;&nbsp;
  <a href="#-데모">데모</a> &nbsp;&middot;&nbsp;
  <a href="#-빠른-시작">빠른 시작</a> &nbsp;&middot;&nbsp;
  <a href="#-예제">예제</a> &nbsp;&middot;&nbsp;
  <a href="#-api-서버">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-로드맵">로드맵</a> &nbsp;&middot;&nbsp;
  <a href="#기여하기">기여하기</a>
</p>

<p align="center">
  <a href="#-빠른-시작"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 뉴스

- **2026-05-29** 🔐 **Robinhood Agentic Trading 지원(옵트인, 제한된 자율성)**: Robinhood Agentic Trading을 지원합니다(원격 MCP, OAuth). 기본적으로 비활성·읽기 전용이며, 에이전트는 사용자가 커밋한 mandate(종목/주문 규모/익스포저/레버리지/일일 한도) 범위 안에서만 자율 거래합니다. 파일 수준의 즉시 kill switch, 선제적 포지션 청산, mandate 자동 만료, 완전한 감사 원장, 영속 자율 runner를 갖췄습니다. 수탁 없음·거래소 없음 — 자금 보유와 체결은 브로커가 하고, 우리는 의도만 중계합니다. 실험적 / 사용에 따른 책임은 본인에게 있습니다.
- **2026-05-28** 🧪 **Swarm 안전성 + 엄격 alpha 게이트 + worker MCP**: Swarm DAG가 상위 태스크 실패 시 하위 태스크를 차단합니다 ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). 새 `run_bench_strict()`는 IC 게이트 위에 동일 universe 랜덤 컨트롤 + 학습/테스트 OOS 분할을 추가해 시장 beta만 따라가는 가짜 factor를 잡아냅니다 ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), @Soli22de 감사). Swarm worker는 이제 operator가 설정한 외부 MCP server를 호출할 수 있으며 신뢰 경계는 전용 테스트로 고정되어 있습니다 ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), @shadowinlife 감사).
- **2026-05-27** 📊 **mootdx A주 데이터 소스 + 출력 정리**: 새 `mootdx` loader는 네이티브 通达信 TCP 프로토콜로 A주 OHLCV를 가져옵니다(인증 불필요, IP 속도 제한 없음, 일봉 + 분봉의 25 페이지 walk-back 페이지네이션). fallback chain에서 tushare와 akshare 사이에 위치합니다 ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). CCXT loader는 이제 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`를 읽어 제한된 네트워크에서 Binance/OKX 공개 데이터를 가져올 수 있습니다 ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), @ruok808 감사). 최종 답변 렌더링에서도 CLI와 Web의 보기 흉한 전체 너비 `---` 구분자를 제거했습니다: system prompt는 markdown 테이블과 `##` 헤딩 사용을 유도하고, CLI 렌더러는 독립 HR을 defense-in-depth로 제거하며, 채팅 버블은 빠져나온 `<hr>`을 숨깁니다 ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), @sdwxm188 감사).
<details>
<summary>이전 뉴스</summary>

- **2026-05-26** ✅ **Research Goal lifecycle 폐쇄 루프**: Goal mode가 실제 task runner처럼 동작합니다. Web UI에서 goal을 만들면 session을 생성하거나 바인딩하고 즉시 kickoff turn을 보냅니다. active goal은 Web/API/CLI/MCP에서 continue/edit/cancel/complete할 수 있으며, agent loop는 최초 prompt만이 아니라 현재 goal snapshot(criteria, evidence, claims, open items)을 기준으로 진행합니다. criteria가 covered였지만 goal이 active로 남아 있으면 조용히 멈추지 않고 audit/status update로 들어가며, backend, CLI, MCP, frontend events 회귀로 고정했습니다.

- **2026-05-25** 🧼 **더 깔끔한 Chat UI + composer 워크플로**: Web UI는 이제 다음 입력에 집중하도록 정리되었습니다. upload, swarm, research-goal 모드는 composer의 `+` 메뉴 뒤로 모이고, floating panel로 채팅을 방해하지 않습니다. 현재 context는 입력창 위 compact chip으로 표시되며, goal 세부 정보는 chip을 클릭할 때만 inline으로 펼쳐집니다. 기존 custom i18n layer도 제거하고 직접 English copy로 통일했습니다. Full Report card는 report-worthy run에만 표시되며, 로컬 dev startup/status reporting도 브라우저 smoke test에 맞게 안정화했습니다.
- **2026-05-24** 🎯 **Research Goal runtime**: backend, CLI, API/MCP, SSE, Web UI 전반에 session-scoped Research Goal layer를 추가했습니다. Goal은 claim, acceptance criteria, evidence row, budget, completion policy를 영속화합니다. agent tool은 goal 생성과 evidence 추가를 지원하고, `/goal`은 CLI 진입점이 되었으며, REST/MCP는 goal snapshot과 evidence write를 노출하고, SSE는 chat client 상태를 최신으로 유지합니다. 후속 audit fixes에서는 verified evidence 경계를 잠그고, agent tool의 live-trading risk tier 입력을 차단하며, CLI-created goal을 이후 turn에 연결하고, session 삭제 시 goal ledger를 정리하고, replay-all을 연결하고, frontend cross-session snapshot race를 수정했습니다.
- **2026-05-23** 🖥️ **대화형 CLI 새 단장**: 터미널 진입점은 더 큰 Vibe-Trading 배너, 더 깔끔한 prompt 구분선, 이전 턴 요약, 실행 후 소요 시간, Claude Code 스타일 activity rail로 live agent 작업을 보여줍니다. 도구 호출, 웹/데이터 fetch, shell 스타일 동작, Markdown 답변, pipe table은 더 읽기 쉬운 transcript로 렌더링되며, pipe 또는 non-TTY 실행은 자동화에 적합한 plain-text 출력을 유지합니다. 생성된 CLI 스크린샷은 커밋되는 docs 파일이 아니라 local artifact로 처리되어 저장소를 가볍게 유지합니다.
- **2026-05-22** 🧭 **Swarm 복구 + MCP keepalive**: Swarm 상태는 이제 읽을 때마다 live task 파일에서 reconcile되므로 API/MCP/SSE/list 뷰가 크래시되었거나 오래된 run을 복구하고 영구 `running` 스냅샷을 보여주지 않습니다. `run_swarm`는 polling 중 MCP progress heartbeat를 보내며, transport drop 이후 재연결한 클라이언트가 handle을 회수할 수 있도록 첫 프레임을 `swarm_started run_id=<id>`로 고정했습니다. worker도 LLM streaming, grounding fetch, tool execution 전 과정에서 heartbeat를 냅니다. stale-run reaper는 run별 임계값을 사용하고 task 상태에서 최종 상태를 도출합니다. `SwarmTool`은 wait budget이 끝났다는 이유만으로 진행 중인 team을 취소하지 않으며, MCP 클라이언트는 `reap_stale_runs()`로 명시적 cleanup을 실행할 수 있습니다. 오늘의 DX pass에서는 provider 기본 모델도 갱신하고 CI syntax check를 새 `agent/cli/` 패키지에 맞췄습니다. 22개의 새 회귀 테스트가 hydrate, 최종 상태 복구, stale reap, keepalive cadence, env parsing, heartbeat wiring을 다루며, 전체 swarm/MCP 스위트는 169 passed, 4 skipped입니다.
- **2026-05-21** 🧱 **CLI 패키지 리팩토링**: `agent/cli.py`(3216 LOC)를 `agent/cli/` 패키지로 분할 — 대화형 진입점, 슬래시 라우터, Rich 컴포넌트, 그리고 모든 서브커맨드를 보존하고 `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` 등 공개 심볼을 재내보내는 `_legacy.py` shim. 새 FastAPI 미들웨어는 브라우저가 `/runs/{id}` 또는 `/correlation`에 직접 접근할 때 SPA 셸을 반환하며, 동일한 좁힘을 Vite dev 프록시에도 반영했습니다. 버전 문자열은 `cli/_version.py` 단일 소스로 통합(`--version`과 배너 드리프트 해결), `python -m cli`는 `__main__.py`로 복원, chat 게이트를 좁혀 `chat --help` / `chat extra`가 REPL에 삼켜지지 않고 레거시 argparse에 도달합니다.
- **2026-05-20** 🔬 **Hypothesis Registry CLI**: 2026-05-16에 백엔드만 출시된 Hypothesis Registry의 CLI 측을 완성했습니다. `vibe-trading hypothesis list`는 Rich 테이블 또는 JSON을 출력합니다(`--status` 필터, `--limit` 지원). `show <id>`는 링크된 run card를 포함한 상세 패널을 렌더링합니다. `invalidate <id> --note "..."`는 상태를 `rejected`로 전환하며, `--note`를 생략하면 기존 invalidation notes를 유지합니다. 기존 `VIBE_TRADING_HYPOTHESES_PATH` 환경변수 오버라이드와 호출별 `--path`를 모두 지원합니다. 22개의 새 테스트가 와이어링, JSON 출력, 상태 필터, limit, ID 누락 오류, 노트 영속성을 다룹니다.
- **2026-05-19** ✨ **도구 라이브 피드백 + 우아한 취소**: 오래 걸리는 도구(백테스트, 큰 PDF, swarm worker)가 멈춘 것처럼 보이지 않게 되었습니다. 모든 도구 호출은 이제 3초 간격의 하트비트와 구조화된 단계별 진행 상황을 발행합니다 — `run_backtest`는 단계 마커(`validate` / `simulate` / `finalize`), `read_document`는 PDF에서는 페이지 단위, Excel에서는 시트 단위, `read_url`은 `fetch` / `parse`를 표시합니다. CLI의 Rich Live 대시보드는 유니코드 스피너, ASCII 진행 표시줄, ETA를 렌더링하고 도구 이름으로 키된 최대 3개의 병렬 도구를 스택 표시합니다. 프런트엔드 채팅에는 새로운 `ToolProgressIndicator`를 추가했으며, rAF 코얼레싱, ARIA `role="status"` + 스크린 리더용 숨겨진 네이티브 `<progress>`, 총량을 알 때 결정적 `ProgressRing` SVG로 전환합니다. CLI 실행 중 첫 번째 `Ctrl+C`는 이제 `agent.cancel()`을 호출해 우아하게 종료(현재 단계가 끝나고 trace가 깨끗하게 닫힘)하고, 2초 이내 두 번째는 강제 종료합니다. 재사용 가능한 기본 요소도 추출했습니다: `ProgressBar.tsx`와 `lib/tools.ts`(공유 도구 이름 i18n).
- **2026-05-18** 🧹 **정리 + 3개의 잠재 버그 수정**: `CompositeEngine`이 거래소 접미사가 없는 중국 선물 코드(`RB2410` 등)를 `GlobalFuturesEngine`으로 잘못 라우팅하던 문제를 수정했습니다. `_is_china_futures`를 공유 `_market_hooks` 모듈로 옮기고, 상품 코드 테이블에 대소문자 정규화 + 비중국 거래소 가드를 추가했으며, 회귀 케이스 9개를 새로 작성했습니다. session FTS5 인덱스가 타임스탬프를 영구 저장하게 되어 크로스 세션 검색에서 날짜 정렬이 가능해졌으며, 동일 변경으로 re-upsert 경로가 `started_at`을 wall-clock으로 덮어쓰던 부수 버그도 해결했습니다. Vite 개발 프록시에 누락되었던 `/alpha`를 추가하여 AlphaZoo 페이지가 `npm run dev`에서 정상 해석됩니다. `tests/test_e2e_harness_v2.py`(실 LLM e2e 스위트)는 `VIBE_TRADING_RUN_LIVE_E2E=1`로 게이트하여 CI가 환경변수 유무에 따라 형태를 바꾸지 않도록 했습니다. ruff에 factor zoo용 `per-file-ignores`를 추가(F401 잡음 3783 → 0)하고, 프런트엔드 tsconfig에 `noUnusedLocals` / `noUnusedParameters`를 활성화해 회귀 가드로 두었으며, `gtja191` alpha 파일들의 사용되지 않는 `vw = vwap(...)` 보일러플레이트 76개도 삭제했습니다. 순 **-918줄**.
- **2026-05-17** 🧬 **Alpha Zoo v1 (0.1.8)**: 4개 zoo에 걸친 452개의 사전 빌드된 quant alpha를 번들로 제공 — `qlib158`(Microsoft Qlib의 Alpha158 특성, Apache-2.0 출처 표기), `alpha101`(Kakushadze의 "101 Formulaic Alphas"를 arXiv:1601.00991 논문 부록에서 재구현), `gtja191`(국태군안 2014 단기 거래형 alpha 리서치 보고서), `academic`(Fama-French 5 + Carhart 모멘텀의 가격 기반 proxy 구현). 한 줄 CLI로 임의 universe에서 벤치: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`. AST 순수 함수 게이트, look-ahead 가드 테스트, `pytest-socket` 네트워크 차단, zoo별 LICENSE.md, 커뮤니티 PR용 DCO 서명 워크플로우 포함. Alpha Library 자동 렌더링: [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/), Research Lab 글: [Which of the 191 GTJA alphas still work in 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).
- **2026-05-16** 🧪 **리서치 기반 업데이트**: backend Hypothesis Registry를 추가해 `create_hypothesis`, `update_hypothesis`, `link_backtest`, `search_hypotheses`를 제공합니다. 외부 콘텐츠 reader는 warning-only `security_warnings`를 붙이고, Shadow Account scanner는 기존 calendar-phase stub 대신 deterministic OHLCV feature evaluation을 사용합니다.
- **2026-05-15** 🪪 Run 상세 페이지에서 metrics와 artifacts 옆에 Trust Layer run card를 렌더링해, 2026-05-12에 들어간 `run_card.json` 작업의 UI 측을 마무리합니다. `PersistentMemory.add()`도 #108/#109/#110 triage에 따라 길이, 빈 문자열 또는 공백만으로 이루어진 name, C0/C1 제어 바이트 경로에서 강화되었습니다([#112](https://github.com/HKUDS/Vibe-Trading/pull/112), @Teerapat-Vatpitak 감사합니다).
- **2026-05-14** 🌐 공개 Wiki가 [vibetrading.wiki](https://vibetrading.wiki/)에 열렸고, docs, tutorials, Research Lab, Alpha Library 섹션을 Cloudflare Pages로 배포합니다. 영구 메모리도 이제 `vibe-trading memory list/show/search/forget`으로 CLI에서 확인할 수 있으며([#102](https://github.com/HKUDS/Vibe-Trading/pull/102), @Teerapat-Vatpitak 감사합니다), memory tokenization/slug는 태국어, 아랍어, 히브리어, 키릴 문자도 지원합니다([#104](https://github.com/HKUDS/Vibe-Trading/pull/104)).

- **2026-05-13** 🧭 Swarm 실행은 이제 가져온 시장 데이터로 worker를 grounding하고, 더 깔끔한 영구 리포트를 남깁니다([#93](https://github.com/HKUDS/Vibe-Trading/pull/93), [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).
- **2026-05-12** 🧾 백테스트는 이제 재현 가능한 리서치 실행을 위해 artifacts와 함께 `run_card.json` 및 `run_card.md`를 생성합니다.
- **2026-05-11** 🧭 **Memory slug, swarm 집계, CLI 프리플라이트**: 영구 메모리는 파일 slug를 생성할 때 CJK 문자를 보존하여 중국어/일본어/한국어 노트에서 조용한 파일명 충돌이 발생하지 않도록 합니다([#95](https://github.com/HKUDS/Vibe-Trading/pull/95), @voidborne-d 감사합니다). Swarm 실행 합계는 이제 provider가 보고한 token usage를 우선 사용하고 기존 추정 fallback도 유지합니다([#94](https://github.com/HKUDS/Vibe-Trading/pull/94), @Teerapat-Vatpitak 감사합니다). CLI 실행 UI에는 일반적인 환경 문제를 확인하는 시작 프리플라이트 체크도 추가되었습니다([#96](https://github.com/HKUDS/Vibe-Trading/pull/96), @ykykj 감사합니다).
- **2026-05-10** 🧱 **회귀 가드레일 + run 메타데이터**: Memory recall은 이제 밑줄을 token 경계로 취급하므로 `mcp_wiring_test` 같은 snake_case 저장 메모리가 "mcp wiring" 같은 자연어 쿼리와 매칭됩니다([#87](https://github.com/HKUDS/Vibe-Trading/pull/87), @hp083625 감사합니다). MCP server에는 initialize → `tools/list` → `tools/call` 경로를 실제 subprocess로 검증하는 smoke test가 추가되어 첫 호출 deadlock 경로를 방지합니다([#86](https://github.com/HKUDS/Vibe-Trading/pull/86)). Windows 경로 민감 테스트, API best-effort 예외 처리, backtest `run_dir` 허용 루트 검증, SwarmRun provider/model 메타데이터에 대한 저위험 강화도 반영되었습니다([#88](https://github.com/HKUDS/Vibe-Trading/pull/88), [#90](https://github.com/HKUDS/Vibe-Trading/pull/90), [#91](https://github.com/HKUDS/Vibe-Trading/pull/91), [#92](https://github.com/HKUDS/Vibe-Trading/pull/92), @Teerapat-Vatpitak 감사합니다).
- **2026-05-09** 🛡️ **API 경로 강화 + MCP server 안정성**: API run/session 라우트는 조회 전에 path ID를 검증하여 개행이 포함된 잘못된 파라미터를 거부하고, 이 동작을 auth/security 회귀 테스트에 고정했습니다([#80](https://github.com/HKUDS/Vibe-Trading/pull/80), @SJoon99 감사합니다). MCP server는 `tools/call`을 제공하기 전에 메인 스레드에서 도구 레지스트리를 미리 워밍업하여 lazy tool discovery의 첫 호출 deadlock을 피합니다([#85](https://github.com/HKUDS/Vibe-Trading/pull/85), @Teerapat-Vatpitak 감사합니다). Vite dev proxy도 기본값이 아닌 백엔드 타깃을 위해 `VITE_API_URL`을 존중합니다([#82](https://github.com/HKUDS/Vibe-Trading/pull/82), @voidborne-d 감사합니다).
- **2026-05-08** 🧾 **Tushare 재무제표 필드를 필터에 연결**: A주 일간 백테스트에서 `fundamental_fields`를 통해 PIT-safe 재무제표 필드를 요청할 수 있으므로 signal engine은 공시/공개일 이후 `income_total_revenue`, `income_n_income`, `balancesheet_total_hldr_eqy_exc_min_int`, `fina_indicator_roe` 등 테이블 접두사 컬럼으로 선별할 수 있습니다([#76](https://github.com/HKUDS/Vibe-Trading/pull/76), @mrbob-git 감사합니다). 후속 강화로 명시적 재무제표 필드 요청 시 Tushare enrichment가 실행되지 않으면 원시 가격 bar로 조용히 fallback하지 않고 즉시 실패합니다([#77](https://github.com/HKUDS/Vibe-Trading/pull/77)).
- **2026-05-07** 📈 **Tushare fundamentals + 커뮤니티 정리**: 펀더멘털 리서치 워크플로를 위해 point-in-time `TushareFundamentalProvider` 계약을 추가하고, 프로젝트 `TUSHARE_TOKEN` 환경 경로를 회귀 테스트로 고정했습니다([#74](https://github.com/HKUDS/Vibe-Trading/pull/74)). 커뮤니티 정리에서는 Vibe-Trading이 당분간 빠른 반복을 위해 하나의 UI 언어에 집중하고, DuckDuckGo 기반 `web_search`가 이미 번들되어 있으므로 중복 검색 의존성을 추가하지 않으며, 비공식 호스팅 배포를 API 키나 데이터 소스 토큰을 입력할 수 있는 신뢰 지점으로 보지 않는다는 점도 명확히 했습니다.
- **2026-05-06** 🚀 **v0.1.7 릴리스**([Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7), `pip install -U vibe-trading-ai`): 보안 경계 강화가 PyPI와 ClawHub에 게시되었습니다. API/read/upload/file/URL/generated-code/shell-tool/Docker 기본값을 더 안전하게 하면서 localhost CLI/Web UI 워크플로는 낮은 마찰을 유지합니다. 이번 사이클에는 Web UI Settings, 상관관계 히트맵, OpenAI Codex OAuth, A주 pre-ST 필터, 대화형 CLI UX, swarm preset inspection, 배당 분석, 개발 워크플로 개선, 감사된 frontend build dependency 하한도 포함됩니다. 0.1.7 기여자들과 조율된 보안 검증을 도와준 lemi9090 (S2W)에게 감사드립니다.
- **2026-05-05** 🛡️ **보안 경계 후속 조치**: 명시적 CORS origin, Settings credential indicator, web URL reading, Shadow Account code generation 주변의 남은 보안 경계 강화를 완료하고 각 경로에 회귀 테스트를 추가했습니다. 일반적인 localhost CLI/Web UI 워크플로는 그대로 유지되며, 원격 배포는 계속 `API_AUTH_KEY`와 명시적인 trusted origin을 사용해야 합니다.
- **2026-05-04** 🖥️ **대화형 CLI UX + CI 정리**: 대화형 모드에 provider/model, 세션 시간, 직전 실행 latency, 누적 tool-call 통계를 보여주는 live bottom status bar가 추가되었고, `prompt_toolkit`을 통해 방향키 기반 prompt history 탐색과 cursor editing을 지원합니다([#69](https://github.com/HKUDS/Vibe-Trading/pull/69)). `prompt_toolkit` 또는 TTY를 사용할 수 없으면 CLI는 여전히 Rich prompt로 fallback합니다. 강화된 file-import sandbox와 cross-platform `/tmp` 해석에 맞춰 CI path expectation도 정렬되어 main이 다시 green 상태가 되었습니다([`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)).
- **2026-05-03** 🛡️ **보안 강화 패치**: 비로컬 배포의 기본 API 인증을 강화하고, 민감한 run/session/swarm read를 보호하며, upload와 local file-reading 경계를 제한하고, shell-capable tool을 entry point별로 제어하며, 생성 전략을 import 전에 검증하고, Docker image를 기본적으로 non-root 사용자와 localhost-only published port로 실행합니다. Local CLI와 localhost Web UI 워크플로는 낮은 마찰을 유지하며, 원격 API/Web 배포는 `API_AUTH_KEY`를 설정해야 합니다.
- **2026-05-02** 🧭 **배당 분석 + 더 선명한 로드맵**: income stock, payout sustainability, dividend growth, shareholder yield, ex-dividend mechanics, yield-trap check를 위한 `dividend-analysis` 스킬을 추가하고 bundled-skill 회귀 테스트로 고정했습니다. 공개 로드맵은 Research Autopilot, Data Bridge, Options Lab, Portfolio Studio, Alpha Zoo, Research Delivery, Trust Layer, Community sharing에 집중하도록 정리되었습니다.
- **2026-05-01** 🔥 **상관관계 히트맵 + OpenAI Codex OAuth + A주 pre-ST 필터**: 새 correlation dashboard/API가 rolling return correlation을 계산하고 포트폴리오 및 종목 분석용 ECharts heatmap을 렌더링합니다([#64](https://github.com/HKUDS/Vibe-Trading/pull/64)). OpenAI Codex provider support는 이제 `vibe-trading provider login openai-codex`를 통해 ChatGPT OAuth를 사용하며, Settings metadata와 adapter regression test가 포함됩니다([#65](https://github.com/HKUDS/Vibe-Trading/pull/65)). A주 ST/*ST 리스크 스크리닝용 `ashare-pre-st-filter` 스킬도 추가 및 강화되었고, Sina penalty relevance filtering으로 securities-account 언급이 E2 count를 부풀리지 않도록 했습니다([#63](https://github.com/HKUDS/Vibe-Trading/pull/63)).
- **2026-04-30** ⚙️ **Web UI Settings + validation CLI 강화**: LLM provider/model, base URL, reasoning effort, data source credential을 위한 새 Settings page가 추가되었고, local/auth-protected settings API와 data-driven provider metadata가 이를 뒷받침합니다([#57](https://github.com/HKUDS/Vibe-Trading/pull/57)). 또한 `python -m backtest.validation <run_dir>`가 missing, blank, malformed, non-existent, non-directory input을 validation 시작 전에 operator-facing message로 명확히 실패하도록 강화했습니다([#60](https://github.com/HKUDS/Vibe-Trading/pull/60)).
- **2026-04-28** 🚀 **v0.1.6 릴리스**(`pip install -U vibe-trading-ai`): `pip install` / `uv tool install` 이후 `vibe-trading --swarm-presets`가 비어 있던 문제를 수정했습니다([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)). preset YAML은 이제 `src.swarm` 패키지 내부에 번들되며 6개 테스트 회귀 suite로 고정됩니다. AKShare loader도 ETF(`510300.SH`)와 forex(`USDCNH`)를 올바른 endpoint로 routing하고 registry fallback을 강화했습니다. v0.1.5 이후의 benchmark comparison panel, `/upload` streaming + size limit, Futu loader(HK + A주), vnpy export skill, security hardening, frontend lazy loading(688KB → 262KB)을 모두 포함합니다.
- **2026-04-27** 📊 **벤치마크 패널 + 업로드 안전성**: 백테스트 출력에 yfinance 기반 SPY, CSI 300 등 resolution을 사용하는 benchmark comparison panel(ticker / benchmark return / excess return / information ratio)이 포함됩니다([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). 또한 `/upload`는 request body를 1MB chunk로 streaming하고 `MAX_UPLOAD_SIZE` 초과 시 중단하여 oversized/malformed client에서도 메모리를 제한합니다([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)). 4-case regression suite로 고정되었습니다.
- **2026-04-22** 🛡️ **하드닝 + 신규 통합**: `safe_path`와 journal/shadow tool sandbox에서 path containment를 강제하고, `MANIFEST.in`이 sdist에 `.env.example` / tests / Docker files를 포함하며, route-level lazy loading으로 frontend initial bundle을 688KB → 262KB로 줄였습니다. Futu data loader for HK & A-share equities([#47](https://github.com/HKUDS/Vibe-Trading/pull/47))와 vnpy CtaTemplate export skill([#46](https://github.com/HKUDS/Vibe-Trading/pull/46))도 추가되었습니다.
- **2026-04-21** 🛡️ **워크스페이스 + 문서**: 상대 `run_dir`이 active run dir로 정규화되었습니다([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). README usage example도 추가되었습니다([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **Reasoning + Swarm**: 모든 `ChatOpenAI` 경로에서 `reasoning_content`가 보존되어 Kimi / DeepSeek / Qwen thinking이 end-to-end로 작동합니다([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). Swarm streaming과 깔끔한 Ctrl+C 처리도 반영되었습니다([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: PyPI와 ClawHub에 게시되었습니다. `python-multipart` CVE floor bump, 신규 MCP tools 5개 연결(`analyze_trade_journal` + 4 shadow-account tools), `pattern_recognition` → `pattern` registry fix, Docker dependency parity, SKILL manifest sync(22 MCP tools / 71 skills)가 포함됩니다.
- **2026-04-18** 👥 **Shadow Account**: broker journal에서 전략 규칙 추출 → 여러 시장에서 shadow backtest → 규칙 위반, 조기 청산, 놓친 signal, counterfactual trade를 통해 정확히 얼마를 놓치는지 보여주는 8-section HTML/PDF report. 신규 tools 4개, skill 1개, 총 tools 32개. Trade Journal + Shadow Account sample은 이제 web UI welcome screen에 있습니다.
- **2026-04-17** 📊 **Trade Journal Analyzer + Universal File Reader**: broker export(同花顺/东财/富途/generic CSV) 업로드 → auto trading profile(holding days, win rate, PnL ratio, drawdown) + 4가지 bias diagnostics(disposition effect, overtrading, chasing momentum, anchoring). `read_document`는 이제 PDF, Word, Excel, PowerPoint, image(OCR), 40+ text format을 하나의 unified call로 dispatch합니다.
- **2026-04-16** 🧠 **Agent Harness**: persistent cross-session memory, FTS5 session search, self-evolving skills(full CRUD), 5-layer context compression, read/write tool batching. tools 27개, 신규 tests 107개.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.ai provider([#35](https://github.com/HKUDS/Vibe-Trading/pull/35)), MiniMax temperature fix + model update([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). providers 13개.
- **2026-04-14** 🔧 **MCP 안정성**: stdio transport에서 backtest tool `Connection closed` error를 수정했습니다([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **Cross-Market Composite Backtest**: 새 `CompositeEngine`이 A주 + crypto 같은 mixed-market portfolio를 shared capital pool과 per-market rule로 backtest합니다. swarm template variable fallback과 frontend timeout도 수정되었습니다.
- **2026-04-12** 🌍 **Multi-Platform Export**: `/pine`은 TradingView(Pine Script v6), TDX(通达信/同花顺/东方财富), MetaTrader 5(MQL5)로 전략을 한 번에 내보냅니다.
- **2026-04-11** 🛡️ **Reliability & DX**: `vibe-trading init` .env bootstrap([#19](https://github.com/HKUDS/Vibe-Trading/pull/19)), preflight checks, runtime data-source fallback, hardened backtest engine. Multi-language README([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: Docker fix([#8](https://github.com/HKUDS/Vibe-Trading/issues/8)), `web_search` MCP tool, LLM providers 12개, `akshare`/`ccxt` dependencies. PyPI와 ClawHub에 게시되었습니다.
- **2026-04-09** 📊 **Backtest Wave 2**: ChinaFutures, GlobalFutures, Forex, Options v2 engines. Monte Carlo, Bootstrap CI, Walk-Forward validation.
- **2026-04-08** 🔧 **Multi-market backtest** with per-market rules, Pine Script v6 export, 5 data sources with auto-fallback.

</details>

---

## ✨ 주요 기능

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="자가 개선 트레이딩 에이전트"/><br>
      <h3>🔍 자가 개선 트레이딩 에이전트</h3>
      <div align="left">
        • 자연어 기반 시장 리서치<br>
        • 전략 초안 작성 및 파일/웹 분석<br>
        • 메모리 기반 워크플로
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="멀티 에이전트 트레이딩 팀"/><br>
      <h3>🐝 멀티 에이전트 트레이딩 팀</h3>
      <div align="left">
        • 투자, 퀀트, 크립토, 리스크 팀<br>
        • 스트리밍 진행 상황과 영구 저장 리포트<br>
        • 가져온 시장 데이터로 grounding된 worker
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="크로스마켓 데이터와 백테스팅"/><br>
      <h3>📊 크로스마켓 데이터 & 백테스팅</h3>
      <div align="left">
        • A/HK/US 주식, 크립토, 선물, 외환<br>
        • 데이터 fallback과 composite backtest<br>
        • PIT 데이터, 검증, run card
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • 브로커 거래 일지 행동 진단<br>
        • 규칙 기반 Shadow Account 비교<br>
        • 내보낼 수 있는 감사 리포트와 전략 코드
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 Vibe-Trading이란?

Vibe-Trading은 금융 질문을 실행 가능한 분석으로 바꾸는 오픈소스 리서치 워크스페이스입니다. 자연어 프롬프트를 시장 데이터 로더, 전략 생성, 백테스트 엔진, 리포트, 내보내기, 영구 리서치 메모리와 연결합니다.

리서치, 시뮬레이션, 백테스팅을 위해 설계되었습니다 — 그리고 원하신다면, 사용자가 직접 인가한 브로커(예: Robinhood Agentic Trading)를 통한 자율 거래도 가능합니다. 자금을 일절 보유하지 않고, 사용자가 설정한 한도를 결코 넘지 않으며, 언제든 즉시 중단할 수 있습니다.

---

## ✨ 무엇을 할 수 있나요?

| 작업 | 출력 |
|------|------|
| **트레이딩 질문하기** | 도구, 데이터, 문서, 재사용 가능한 세션 컨텍스트를 활용한 시장 리서치. |
| **전략 아이디어 백테스트** | 전략 코드, 지표, 벤치마크 컨텍스트, 검증 artifacts, run cards. |
| **내 거래 검토하기** | 브로커 일지 파싱, 행동 진단, 규칙 추출, Shadow Account 비교. |
| **반복 리서치 개선하기** | 영구 메모리와 편집 가능한 스킬로 유용한 루틴을 재사용 가능한 워크플로로 전환. |
| **애널리스트 팀 실행하기** | 투자, 퀀트, 크립토, 매크로, 리스크 워크플로를 위한 멀티 에이전트 리서치 리뷰. |
| **사용 가능한 artifacts 만들기** | 리포트, TradingView Pine Script, TDX, MetaTrader 5, MCP tools, 이후 리서치 세션. |
| **사전 빌드된 alpha zoo 벤치** | 452개의 alpha 인자(Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart)에 대해 한 줄 CLI로 IC + IR + alive/reversed/dead 분류 수행 |

---

## ⚡ 빠른 예제

```bash
pip install vibe-trading-ai

# 자연어 리서치
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# 한 줄로 사전 빌드된 alpha zoo 벤치
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 👥 섀도우 계정

Shadow Account는 일반적인 전략 템플릿이 아니라 사용자의 실제 거래 기록에서 시작합니다.

브로커 export를 업로드하고 에이전트가 행동을 요약하게 한 뒤, 실제 거래 경로를 규칙 기반 shadow strategy와 비교합니다.

| 단계 | 에이전트 출력 |
|------|--------------|
| **1. 일지 읽기** | 同花顺, 东方财富, 富途, generic CSV 형식의 브로커 export를 파싱합니다. |
| **2. 행동 프로파일링** | 보유 일수, 승률, 손익비, drawdown, disposition effect, overtrading, momentum chasing, anchoring 점검. |
| **3. 규칙 추출** | 반복되는 진입/청산을 모호한 요약이 아닌 명시적인 strategy profile로 변환합니다. |
| **4. Shadow 실행** | 추출된 규칙을 백테스트하고 규칙 위반, 조기 청산, 놓친 signal, 대안 거래 경로를 강조합니다. |
| **5. 리포트 제공** | 나중에 점검, 보관, 개선할 수 있는 HTML/PDF 리포트를 생성합니다. |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 🧪 리서치 워크플로

대부분의 실행은 같은 evidence path를 따릅니다. 요청을 라우팅하고, 적절한 시장 컨텍스트를 로드하고, 도구를 실행하고, 출력을 검증하며, artifacts를 점검 가능한 상태로 유지합니다.

| 계층 | 수행 내용 |
|------|-----------|
| **Plan** | 유용한 경우 관련 finance skills, tools, data sources, swarm preset을 선택합니다. |
| **Ground** | 사용 가능한 loader로 A주, HK/US 주식, 크립토, 선물, 외환, 문서, 웹 컨텍스트를 가져옵니다. |
| **Execute** | 테스트 가능한 전략 코드를 생성하고, 도구를 실행하며, 적절한 backtest engine 또는 analysis workflow를 사용합니다. |
| **Validate** | 지표, benchmark comparison, Monte Carlo, Bootstrap, Walk-Forward, run cards, 관련 warning을 추가합니다. |
| **Deliver** | TradingView, TDX, MetaTrader 5, MCP client, 이후 세션을 위한 리포트, artifacts, tool traces, exports를 반환합니다. |

---

## 🔩 상세 기능

메인 README를 읽기 쉽게 유지하기 위해 상세 목록은 아래에 접어 두었습니다. 사용 가능한 구성 요소를 확인하고 싶을 때 열어보세요.

<details>
<summary><b>금융 스킬 라이브러리</b> <sub>8개 카테고리 77개 스킬</sub></summary>

- 📊 8개 카테고리로 구성된 77개 전문 금융 스킬
- 🌐 전통 시장부터 크립토 & DeFi까지 완전한 커버리지
- 🔬 데이터 sourcing부터 정량 리서치까지 포괄하는 기능

| 카테고리 | 스킬 | 예시 |
|----------|------|------|
| Data Source | 7 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 17 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 11 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `alpha-zoo` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>프리셋 트레이딩 팀</b> <sub>29개 swarm preset</sub></summary>

- 🏢 바로 사용할 수 있는 29개 에이전트 팀
- ⚡ 사전 구성된 금융 워크플로
- 🎯 투자, 트레이딩, 리스크 관리 preset

| 프리셋 | 워크플로 |
|--------|----------|
| `investment_committee` | bull/bear 토론 → 리스크 리뷰 → PM 최종 판단 |
| `global_equities_desk` | A주 + HK/US + 크립토 리서처 → 글로벌 전략가 |
| `crypto_trading_desk` | funding/basis + liquidation + flow → 리스크 매니저 |
| `earnings_research_desk` | 펀더멘털 + revision + options → 실적 전략가 |
| `macro_rates_fx_desk` | rates + FX + commodity → macro PM |
| `quant_strategy_desk` | screening + factor research → backtest → risk audit |
| `technical_analysis_panel` | classic TA + Ichimoku + harmonic + Elliott + SMC → consensus |
| `risk_committee` | drawdown + tail risk + regime review → sign-off |
| `global_allocation_committee` | A주 + 크립토 + HK/US → cross-market allocation |

<sub>추가로 20개 이상의 전문 preset이 있습니다. 전체 목록은 vibe-trading --swarm-presets로 확인하세요.

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>4개 zoo에 걸친 452개 사전 빌드된 quant alpha</sub></summary>

- 🧬 operator 계층에서 lookahead가 금지된 452개 cross-sectional alpha
- 📈 한 줄 CLI로 IC + IR + alive/reversed/dead 분류 수행
- 🔬 AST 순수성 게이트 + 300-row lookahead sentinel 테스트 + `pytest-socket` 네트워크 kill-switch
- 📦 Qlib에 대한 Apache-2 출처 표기, zoo별 `LICENSE.md`에서 수식을 수학적 콘텐츠로 명시
- 🤝 커뮤니티 PR을 위한 Developer Certificate of Origin (DCO) 서명 워크플로

| Zoo | Count | Source | License |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0, 커밋 고정) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | 수식은 수학적 콘텐츠 |
| **gtja191** | 191 | 국태군안 (2014), "191 Short-period Trading Alpha Factors" | 수식은 수학적 콘텐츠 |
| **academic** | 6 | Fama-French 5 + Carhart 모멘텀 (가격 기반 proxy) | 공개 학술 문헌 |

`vibe-trading alpha list`로 카탈로그를 탐색하고, `vibe-trading alpha show <id>`로 수식과 소스 코드를 확인하며, `vibe-trading alpha bench --zoo X --universe Y --period Z`로 zoo 전체를 점수화하세요.

</details>

## 🎬 데모

<div align="center">
<table>
<tr>
<td width="50%">

https://github.com/user-attachments/assets/4e4dcb80-7358-4b9a-92f0-1e29612e6e86

</td>
<td width="50%">

https://github.com/user-attachments/assets/3754a414-c3ee-464f-b1e8-78e1a74fbd30

</td>
</tr>
<tr>
<td colspan="2" align="center"><sub>☝️ 자연어 백테스트 & 멀티 에이전트 swarm 토론 — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 빠른 시작

### 한 줄 설치 (PyPI)

```bash
pip install vibe-trading-ai
```

첫 리서치 작업을 실행하세요:

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **패키지 이름 vs 명령:** PyPI 패키지는 `vibe-trading-ai`입니다. 설치하면 세 가지 명령을 사용할 수 있습니다:
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | 대화형 CLI / TUI |
> | `vibe-trading serve` | FastAPI 웹 서버 실행 |
> | `vibe-trading-mcp` | MCP 서버 시작(Claude Desktop, OpenClaw, Cursor 등) |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### 또는 경로 선택

| 경로 | 적합한 용도 | 시간 |
|------|-------------|------|
| **A. Docker** | 즉시 체험, 로컬 설정 없음 | 2분 |
| **B. Local install** | 개발, 전체 CLI 접근 | 5분 |
| **C. MCP plugin** | 기존 에이전트에 연결 | 3분 |
| **D. ClawHub** | 한 번의 명령, clone 불필요 | 1분 |

### 사전 요구사항

- 지원 provider 중 하나의 **LLM API key** 또는 **Ollama** 로컬 실행(key 불필요)
- 경로 B용 **Python 3.11+**
- 경로 A용 **Docker**
- OpenAI Codex도 ChatGPT OAuth로 사용할 수 있습니다. `LANGCHAIN_PROVIDER=openai-codex`를 설정한 뒤 `vibe-trading provider login openai-codex`를 실행하세요. 이 방식은 `OPENAI_API_KEY`를 사용하지 않습니다.

> **지원 LLM provider:** OpenRouter, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama(local). 설정은 `.env.example`을 참고하세요.

> **팁:** 자동 fallback 덕분에 모든 시장은 API key 없이도 작동합니다. yfinance(HK/US), OKX(crypto), mootdx(A주, TCP 직결, IP 제한 없음), AKShare(A주, US, HK, futures, forex)는 모두 무료입니다. Tushare token은 선택 사항이며, mootdx가 권장 no-token A주 fallback이고 AKShare는 더 넓은 커버리지의 백업입니다.

### 경로 A: Docker (설정 불필요)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

`http://localhost:8899`를 여세요. Backend + frontend가 하나의 container에 들어 있습니다.

Docker는 기본적으로 backend를 `127.0.0.1:8899`에 게시하고 앱을 non-root container user로 실행합니다. API를 자신의 머신 밖으로 의도적으로 노출하는 경우 강력한 `API_AUTH_KEY`를 설정하고 client에서 `Authorization: Bearer <key>`를 보내세요.

### 경로 B: Local install

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

<details>
<summary><b>웹 UI 시작(선택 사항)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev
```

`http://localhost:5899`를 여세요. Frontend는 API 호출을 `localhost:8899`로 proxy합니다.

**Production mode(single server):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

</details>

### 경로 C: MCP plugin

아래 [MCP Plugin](#-mcp-plugin) 섹션을 참고하세요.

### 경로 D: ClawHub (한 번의 명령)

```bash
npx clawhub@latest install vibe-trading --force
```

skill + MCP config가 agent의 skills directory에 다운로드됩니다. 자세한 내용은 [ClawHub install](#-mcp-plugin)을 참고하세요.

---

## 🧠 환경 변수

`agent/.env.example`을 `agent/.env`로 복사하고 사용할 provider block의 주석을 해제하세요. 각 provider에는 3~4개의 변수가 필요합니다:

| 변수 | 필수 | 설명 |
|------|:----:|------|
| `LANGCHAIN_PROVIDER` | Yes | Provider name(`openrouter`, `deepseek`, `groq`, `ollama` 등) |
| `<PROVIDER>_API_KEY` | Yes* | API key(`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` 등) |
| `<PROVIDER>_BASE_URL` | Yes | API endpoint URL |
| `LANGCHAIN_MODEL_NAME` | Yes | Model name(예: `deepseek-v4-pro`) |
| `TUSHARE_TOKEN` | No | A주 data용 Tushare Pro token(AKShare로 fallback) |
| `TIMEOUT_SECONDS` | No | LLM call timeout, 기본 120s |
| `API_AUTH_KEY` | 네트워크 배포 권장 | API가 non-local client에서 접근 가능할 때 필요한 Bearer token |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | remote API/MCP-SSE 형태 배포에서 shell-capable tools 명시적 opt-in |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | document와 broker-journal import용 추가 comma-separated roots |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | generated-code run directory용 추가 comma-separated roots |

<sub>* Ollama는 API key가 필요 없습니다. OpenAI Codex는 ChatGPT OAuth를 사용하며 token을 `agent/.env`가 아니라 `oauth-cli-kit`을 통해 저장합니다.</sub>

**무료 데이터(key 불필요):** AKShare를 통한 A주, yfinance를 통한 HK/US equities, OKX를 통한 crypto, CCXT를 통한 100개 이상 crypto exchanges. 시스템은 시장별로 가장 적합한 source를 자동 선택합니다.

### 🎯 권장 모델

Vibe-Trading은 tool-heavy agent입니다. skills, backtests, memory, swarms가 모두 tool call을 통해 흐릅니다. 모델 선택은 에이전트가 실제로 *도구를 사용하는지*, 아니면 학습 데이터에서 답을 만들어내는지를 직접 결정합니다.

| 등급 | 예시 | 사용 시점 |
|------|------|-----------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | 복잡한 swarms(3+ agents), 긴 리서치 세션, 논문급 분석 |
| **Sweet spot**(기본값) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | Daily driver — 약 1/10 비용으로 안정적인 tool-calling |
| **Agent 사용 시 피할 것** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | tool-calling이 불안정합니다. agent가 skills를 로드하거나 backtest를 실행하는 대신 "기억에서 답하는" 것처럼 보일 수 있습니다. |

기본 `agent/.env.example`은 DeepSeek official API + `deepseek-v4-pro`를 포함합니다. OpenRouter 사용자는 `deepseek/deepseek-v4-pro`를 사용할 수 있습니다.

---

## 🖥 CLI 참조

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # 사전 빌드된 452개 alpha 탐색; show / bench / compare / export-manifest 서브커맨드 사용 가능
```

<details>
<summary><b>TUI 내 slash commands</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | 모든 명령 표시 |
| `/skills` | 77개 finance skills 목록 |
| `/swarm` | 29개 swarm team presets 목록 |
| `/swarm run <preset> [vars_json]` | live streaming으로 swarm team 실행 |
| `/swarm list` | Swarm run history |
| `/swarm show <run_id>` | Swarm run details |
| `/swarm cancel <run_id>` | 실행 중인 swarm 취소 |
| `/list` | Recent runs |
| `/show <run_id>` | Run details + metrics |
| `/code <run_id>` | Generated strategy code |
| `/pine <run_id>` | indicators export(TradingView + TDX + MT5) |
| `/trace <run_id>` | Full execution replay |
| `/continue <run_id> <prompt>` | 새 instruction으로 run 계속 |
| `/sessions` | Chat sessions 목록 |
| `/settings` | Runtime config 표시 |
| `/clear` | 화면 지우기 |
| `/quit` | 종료 |

</details>

<details>
<summary><b>Single run & flags</b></summary>

```bash
vibe-trading run -p "Backtest BTC-USDT MACD strategy, last 30 days"
vibe-trading run -p "Analyze AAPL momentum" --json
vibe-trading run -f strategy.txt
echo "Backtest 000001.SZ RSI" | vibe-trading run
```

```bash
vibe-trading -p "your prompt"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # Export indicators (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

```bash
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

---

## 💡 예제

### 전략 & 백테스팅

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

**한 줄로 사전 빌드된 alpha zoo 벤치하기**:
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**카탈로그 탐색** 후 단일 alpha 확인:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**zoo 인자들로 다인자 신호 구성**(Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### 시장 리서치

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm 워크플로

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'
```

### 크로스세션 메모리

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### 문서 업로드 & 분석

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 API 서버

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | runs 목록 |
| `GET` | `/runs/{run_id}` | run details |
| `GET` | `/runs/{run_id}/pine` | multi-platform indicator export |
| `POST` | `/sessions` | session 생성 |
| `POST` | `/sessions/{id}/messages` | message 전송 |
| `GET` | `/sessions/{id}/events` | SSE event stream |
| `POST` | `/upload` | PDF/file 업로드 |
| `GET` | `/swarm/presets` | swarm presets 목록 |
| `POST` | `/swarm/runs` | swarm run 시작 |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE stream |
| `GET` | `/alpha/list` | zoo/theme/universe로 alpha 목록 필터링 |
| `GET` | `/alpha/{alpha_id}` | Alpha 메타데이터 + 소스 코드 |
| `POST` | `/alpha/bench` | Bench 작업 시작 (`job_id` 반환) |
| `GET` | `/alpha/bench/{job_id}/stream` | SSE 진행 스트림 |
| `GET` | `/settings/llm` | Web UI LLM settings 읽기 |
| `PUT` | `/settings/llm` | local LLM settings 업데이트 |
| `GET` | `/settings/data-sources` | local data source settings 읽기 |
| `PUT` | `/settings/data-sources` | local data source settings 업데이트 |

Interactive docs: `http://localhost:8899/docs`

### 보안 기본값

localhost 개발에서 `vibe-trading serve`는 browser workflow를 단순하게 유지합니다. non-local client에서는 민감한 API endpoint에 `API_AUTH_KEY`가 필요합니다. JSON/upload request에는 `Authorization: Bearer <key>`를 사용하세요. Browser EventSource stream은 Web UI Settings에 같은 key를 한 번 입력하면 Web UI가 처리합니다.

Shell-capable tools는 local CLI와 trusted localhost workflow에서 사용할 수 있지만, `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`을 명시적으로 설정하지 않는 한 remote API session에는 노출되지 않습니다. Document와 journal reader는 기본적으로 upload/import roots로 제한됩니다. 파일은 `agent/uploads`, `agent/runs`, `./uploads`, `./data`, `~/.vibe-trading/uploads`, `~/.vibe-trading/imports` 아래에 두거나, `VIBE_TRADING_ALLOWED_FILE_ROOTS`로 전용 directory를 추가하세요.

### Web UI Settings

Web UI Settings page에서는 local user가 LLM provider/model, base URL, generation parameters, reasoning effort, Tushare token 같은 선택적 market data credentials를 업데이트할 수 있습니다. Settings는 `agent/.env`에 저장되며 provider defaults는 `agent/src/providers/llm_providers.json`에서 로드됩니다.

Settings read는 side effect가 없습니다. `GET /settings/llm`과 `GET /settings/data-sources`는 `agent/.env`를 만들지 않으며 project-relative path만 반환합니다. Settings read/write는 credential state를 노출하거나 credential/runtime environment를 업데이트할 수 있으므로 `API_AUTH_KEY`가 설정되어 있으면 인증이 필요합니다. dev mode에서 `API_AUTH_KEY`가 설정되지 않은 경우 settings access는 loopback client에서만 허용됩니다.

---

## 🔌 MCP Plugin

Vibe-Trading은 모든 MCP-compatible client를 위해 22개 MCP tools를 제공합니다. stdio subprocess로 실행되므로 server setup이 필요 없습니다. **22개 중 21개 tools는 API key 없이 작동합니다**(HK/US/crypto). `run_swarm`만 LLM key가 필요합니다.

<details>
<summary><b>Claude Desktop</b></summary>

`claude_desktop_config.json`에 추가:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

</details>

<details>
<summary><b>OpenClaw</b></summary>

`~/.openclaw/config.yaml`에 추가:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / 기타 MCP clients</b></summary>

```bash
vibe-trading-mcp                  # stdio (default)
vibe-trading-mcp --transport sse  # SSE for web clients
```

</details>

**노출되는 MCP tools(22):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

<details>
<summary><b>ClawHub에서 설치(한 번의 명령)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> skill이 외부 API를 참조하여 VirusTotal 자동 스캔이 트리거되므로 `--force`가 필요합니다. 코드는 완전한 오픈소스이며 검토할 수 있습니다.

이 명령은 skill + MCP config를 agent의 skills directory에 다운로드합니다. clone은 필요 없습니다.

ClawHub에서 보기: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — 자가 진화 스킬</b></summary>

77개 finance skills는 모두 [open-space.cloud](https://open-space.cloud)에 게시되어 있으며 OpenSpace의 self-evolution engine을 통해 자율적으로 발전합니다.

OpenSpace와 함께 사용하려면 두 MCP server를 agent config에 추가하세요:

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "toolTimeout": 600,
      "env": {
        "OPENSPACE_HOST_SKILL_DIRS": "/path/to/vibe-trading/agent/src/skills",
        "OPENSPACE_WORKSPACE": "/path/to/OpenSpace"
      }
    },
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

OpenSpace는 77개 skills를 모두 자동 발견하여 auto-fix, auto-improve, community sharing을 활성화합니다. OpenSpace-connected agent에서 `search_skills("finance backtest")`로 Vibe-Trading skills를 검색하세요.

</details>

---

## 📁 프로젝트 구조

<details>
<summary><b>펼쳐 보기</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # CLI package — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 22 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (77 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 31 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 4개 zoo에 걸친 452개 alpha
│   │   │   ├── base.py             #   19개 operator (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST-only 메타데이터 로딩 + lazy compute + sanity gate
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead 분류
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (6)
│   │   │
│   │   ├── api/                    # FastAPI 라우트 모듈
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 77 finance skills in 8 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   29 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   7 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   7 sources: tushare, okx, yfinance, akshare, mootdx, ccxt, futu
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + auto-fallback chains
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, AlphaZoo, RunDetail, Compare, Correlation, Settings
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand state management
│
├── Dockerfile                      # Multi-stage build
├── docker-compose.yml              # One-command deploy
├── pyproject.toml                  # Package config + CLI entrypoint
├── tools/                          # 레포 단위 CI helper
│   └── ci_grep_gates.sh            # yaml.load / 트레이드마크 / 종목별 데이터 누출 차단
└── LICENSE                         # MIT
```

</details>

---

## 🏛 생태계

Vibe-Trading은 **[HKUDS](https://github.com/HKUDS)** agent ecosystem의 일부입니다:

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>초경량 개인 AI 어시스턴트</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Agent-Native Signal &amp; Copy Trading Platform</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>모든 소프트웨어를 agent-native로</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>자가 진화 AI agent skills</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
  </tr>
</table>

---

## 🗺 로드맵

> 단계적으로 배포합니다. 작업이 시작되면 항목은 [Issues](https://github.com/HKUDS/Vibe-Trading/issues)로 이동합니다.

| Phase | Feature | Status |
|-------|---------|--------|
| **Trust Layer** | 재현 가능한 run cards는 생성 및 Run Detail 표시까지 완료. v1은 tool traces와 citations 추가 | v0 출시 |
| **Hypothesis Registry** | lifecycle status, data sources, skills, run-card links, invalidation notes를 가진 durable research hypotheses | Backend MVP 출시 |
| **Research Autopilot** | 수동 실행 우선 research loop: hypothesis → deterministic backtest → evidence report | 다음 |
| **Data Bridge** | Bring-your-own data: local CSV/Parquet/SQL connectors with schema mapping | Planned |
| **Options Lab** | Vol surface, Greeks dashboard, payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray, constraints, turnover-aware optimizer, rebalance notes | Planned |
| **Alpha Zoo** | 4개 zoo에 걸친 452개의 사전 빌드된 alpha 인자(Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart), 한 줄 CLI 벤치, agent 통합, Web UI | **0.1.8 출시 완료** |
| **Research Delivery** | Slack / Telegram / email-style channels로 예약 brief 전달 | Planned |
| **Community** | 공유 가능한 skills, presets, strategy cards | Exploring |

---

## 기여하기

기여를 환영합니다! 가이드는 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

**Good first issues**는 [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 라벨이 붙어 있습니다. 하나를 골라 시작해 보세요.

더 큰 기여를 하고 싶나요? 위 [로드맵](#-로드맵)을 확인하고 시작 전에 issue를 열어 논의해 주세요.

---

## 기여자

Vibe-Trading에 기여해 주신 모든 분께 감사드립니다!

최근 v0.1.8 cycle contributors and credits:

- @GTC2080 / TaoMu — Web UI Settings and provider/data-source configuration APIs (#57)
- @BigNounce90 — validation CLI hardening for backtest `run_dir` input (#60)
- @shadowinlife — A-share pre-ST filter skill (#63)
- @MB-Ndhlovu — correlation heatmap dashboard and review fixes (#64, #66)
- @ykykj — OpenAI Codex OAuth provider option (#65)
- @RuifengFu — interactive CLI live status bar and prompt editing (#69)
- @SiMinus — swarm preset inspection command (#73)
- @warren618 / Haozhe Wu — security hardening, release integration, docs, Docker, packaging, and local dev workflow
- lemi9090 (S2W) — coordinated security research, validation, and disclosure support

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## 면책조항

Vibe-Trading은 리서치 및 거래 소프트웨어입니다. 투자 조언이 아니며, 자금을 보유하지 않고, 거래소를 운영하지 않습니다. 거래는 사용자가 명시적으로 인가한 브로커 채널(예: Robinhood Agentic Trading)을 통해서만, 사용자가 설정한 한도 내에서 이루어지며 언제든 중단할 수 있습니다. 이 브로커 거래 기능은 실험적이며 당사가 실제 브로커 계정으로 검증하지 않았습니다 — 사용에 따른 책임은 본인에게 있습니다. 과거 성과가 미래 수익을 보장하지 않습니다.

## 라이선스

MIT License — [LICENSE](LICENSE) 참조

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

<p align="center">
  ⭐ <b>Vibe-Trading</b>이 연구에 도움이 되었다면, Star를 눌러 더 많은 분들이 찾을 수 있도록 도와주세요.
</p>

---

<p align="center">
  <b>Vibe-Trading</b>에 방문해 주셔서 감사합니다 ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
