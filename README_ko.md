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
  <a href="https://trendshift.io/repositories/25527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25527" alt="HKUDS%2FVibe-Trading | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
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
  <a href="https://discord.gg/6TdQnT5xcF"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
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

- **2026-06-25** 🧪 **엄격한 validation JSON + 더 안정적인 agent context**: 독립 backtest validation 이 `artifacts/validation.json` 또는 CLI stdout 을 쓰기 전에 중첩된 `NaN` / `Infinity` 값을 정규화해, strict JSON parser 가 validation payload 에서 막히지 않습니다([#306](https://github.com/HKUDS/Vibe-Trading/pull/306), @gyx09212214-prog 님 감사합니다). Agent prompt 도 loader registry 에서 현재 data-source 수를 동적으로 계산하고, `_microcompact()` 는 실제 token pressure 가 있을 때만 실행되어 짧은 실행에서 오래된 tool result 를 너무 일찍 비우지 않습니다([#296](https://github.com/HKUDS/Vibe-Trading/pull/296), [#282](https://github.com/HKUDS/Vibe-Trading/issues/282) 종료, @MarkfuGod 님 감사합니다).
- **2026-06-24** 🎯 **Shadow Account 가격 context + 반응형 중국어 UI + LAN auth 수정**: Shadow Account 규칙 추출은 이제 `buy_dt` 기준 point-in-time-safe entry context 인 `entry_rsi14` 와 `prior_5d_return` 을 loader registry 로 가져오며, offline / no-data 상황에서는 기존처럼 graceful 하게 feature 를 제외합니다([#302](https://github.com/HKUDS/Vibe-Trading/pull/302), [#295](https://github.com/HKUDS/Vibe-Trading/issues/295) follow-up, @Robin1987China 님 감사합니다). 주요 Web UI 패널은 charts, chat, Alpha Library, Correlation, Run Detail 까지 반응형 English / zh-CN translation 을 사용합니다([#301](https://github.com/HKUDS/Vibe-Trading/pull/301), @skloxo 님 감사합니다). CSRF hardening 이후에도 `API_AUTH_KEY` 가 설정된 remote same-origin Web UI deployment 는 POST / upload 가 다시 통과하고, mismatch 된 cross-site origin 은 계속 차단됩니다([#304](https://github.com/HKUDS/Vibe-Trading/pull/304), @Hinotoi-agent 님 감사합니다).
- **2026-06-23** 🛡️ **로컬 API CSRF 강화**: 악성 웹 페이지가 루프백 API에 안전하지 않은 크로스 사이트 요청(POST/PUT/DELETE)을 보낼 수 없게 했습니다 — CORS는 응답 읽기는 막아도 부작용은 막지 못하므로, 루프백 dev-mode 신뢰를 허용하기 **전에** 안전하지 않은 메서드에 기존 크로스 사이트 가드를 적용합니다. 안전한 메서드와 로컬 CLI / 비브라우저 업로드에는 영향이 없습니다([#293](https://github.com/HKUDS/Vibe-Trading/pull/293), @Hinotoi-agent 님 감사합니다).
<details>
<summary>이전 뉴스</summary>

- **2026-06-22** 🔧 **라이브 인가 OAuth 수정 + Alpha Zoo 헤드라인 수정**: `connector authorize`가 몇 분이 걸리는 브로커 로그인 동안 OAuth 핸드셰이크를 유지하고(`VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`로 조정 가능), 재시도 시 경쟁하는 콜백 서버를 더 이상 띄우지 않아 토큰이 실제로 저장됩니다([#281](https://github.com/HKUDS/Vibe-Trading/pull/281), [#259](https://github.com/HKUDS/Vibe-Trading/issues/259) 종료, @Robin1987China 님 감사합니다). Alpha Zoo 페이지가 alpha 개수를 두 번 표시하지 않습니다([#287](https://github.com/HKUDS/Vibe-Trading/pull/287), [#286](https://github.com/HKUDS/Vibe-Trading/issues/286) 종료, @digger-yu 님 감사합니다). 예약 리서치에도 엔드투엔드 사용 문서가 추가됐습니다([#288](https://github.com/HKUDS/Vibe-Trading/pull/288)).
- **2026-06-21** ⏰ **예약 리서치 실행기 + 리포트 라이브러리 + 백테스트 사후 기여도 분석**: 예약 리서치가 이제 **엔드투엔드**로 동작합니다 — 기본 비활성화된 백그라운드 실행기(`VIBE_TRADING_ENABLE_SCHEDULER`)가 interval/cron 으로 도래한 작업을 세션 런타임을 통해 실행합니다([#278](https://github.com/HKUDS/Vibe-Trading/pull/278), @mvanhorn 님 감사합니다, [#254](https://github.com/HKUDS/Vibe-Trading/issues/254) 종료). 새 **`/reports` 실행 라이브러리** 페이지는 리포트를 생성한 실행을 나열·검색·필터링하고 Run Detail + Compare 로 연결됩니다([#224](https://github.com/HKUDS/Vibe-Trading/pull/224), @LemonCANDY42 님 감사합니다). 또한 백테스트가 끝날 때마다 에이전트가 **계층형 기여도 분석** — 거래 단위 손익 Top, 베타 회귀, 시장 레짐 분석, 몬테카를로 순열 검정 — 을 데이터 가용성과 라우팅 조건에 따라 자동으로 수행합니다([#280](https://github.com/HKUDS/Vibe-Trading/pull/280), @shadowinlife 님 감사합니다).
- **2026-06-20** 🔬 **Research Autopilot 루프 완성(3단계) + 로더 OHLC 무결성 가드 + 학술 알파 4종**: **Research Autopilot** 이 **가설 → 시그널 엔진 → 백테스트** 를 엔드투엔드로 실행합니다 — `scaffold_signal_engine` 이 runner 계약에 맞는 엔진을 생성하고, `link_autopilot_backtest` 가 백테스트 지표를 가설로 자동 회신합니다(**68개 도구**)([#267](https://github.com/HKUDS/Vibe-Trading/pull/267)). 구조적 **OHLC 정합성 검사**가 로더 경계에서 잘못된 bar(`high < low`, 음수 가격, high/low가 open/close를 감싸지 못함)를 일괄 제거해 모든 데이터 소스를 보호합니다([#274](https://github.com/HKUDS/Vibe-Trading/pull/274), @Shizoqua 님 감사합니다). 그리고 **academic 알파 패밀리가 6 → 10으로 확장**됩니다 — Jegadeesh 반전, George-Hwang 52주 고점, Amihud 비유동성, Harvey-Siddique 왜도(**456개 팩터**)([#277](https://github.com/HKUDS/Vibe-Trading/pull/277), @Robin1987China 님 감사합니다).
- **2026-06-19** 🚀 **v0.1.10 — 글로벌 데이터 계층**: 시장 데이터 소스가 10 → 18개로 확대(무료 **Eastmoney / Sina / Stooq / Yahoo** + 키 기반 **Finnhub / Alpha Vantage / Tiingo / FMP**, IP 차단 위험 순 fallback). 여기에 **읽기 전용 데이터 도구 18종**(자금 흐름, 용호방, 북향, 신용거래, 대종거래, SEC EDGAR + XBRL, 재무, 옵션 체인, 전체 시장 스크리닝…)을 A주 / 미국 / 홍콩 전반에 걸쳐 모두 MCP로 노출. 이번 릴리스는 0.1.9 이후의 모든 업데이트도 함께 포함합니다 — 브로커 커넥터 10종, `alpha compare`, 프로바이더 신뢰성 대개편, 옵션형 데이터 캐시. `pip install -U vibe-trading-ai`
- **2026-06-18** 🔬 **Research Autopilot 1단계 + 로컬 Data Bridge 로더, 그리고 Discord 보안 공지**: 새 `run_research_autopilot` + `generate_backtest_config`가 **Hypothesis → Research Goal → backtest**를 끝까지 연결하고(이제 **50개 도구**), 새 **`local`** 로더가 사용자 본인의 **CSV / Parquet / DuckDB** 파일에서 직접 OHLCV를 읽습니다([#260](https://github.com/HKUDS/Vibe-Trading/pull/260), [#252](https://github.com/HKUDS/Vibe-Trading/pull/252), @Robin1987China 님 감사합니다). 또한 DeepSeek `DSML` tool call 파싱과 식별자 봉쇄 강화가 들어왔습니다. ⚠️ **보안 공지**: 이전 커뮤니티 Discord 초대는 이제 우리가 관리하지 않는 서버(가짜 Collab.Land 지갑 "인증" 피싱)로 연결됩니다 — 모두 제거됐고, **유일한** 공식 Discord는 HKUDS 서버([discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF))입니다. 지갑 연결을 요구하는 일은 결코 없습니다.
- **2026-06-17** 🧩 **설치 호환성 + Opus/Kimi 프로바이더 수정**: 기본 `pip install vibe-trading-ai`는 더 이상 선택 기능인 `pyharmonics` / `ta` 의존성 체인을 끌어오지 않습니다. harmonic detection은 `vibe-trading-ai[harmonic]` extra 뒤로 이동했고, 내장 fallback detector는 그대로 사용할 수 있습니다([#250](https://github.com/HKUDS/Vibe-Trading/pull/250), [#249](https://github.com/HKUDS/Vibe-Trading/issues/249) 종료). Agent loop는 Opus 4.8+가 거부하는 assistant-prefill handoff message를 보내지 않으며, Kimi/Moonshot은 `MOONSHOT_USER_AGENT`로 client `User-Agent`를 덮어쓸 수 있습니다([#248](https://github.com/HKUDS/Vibe-Trading/pull/248), [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) 및 [#204](https://github.com/HKUDS/Vibe-Trading/issues/204) 종료). 후속 테스트는 background-result와 auto-compact handoff 경로를 직접 커버합니다([#251](https://github.com/HKUDS/Vibe-Trading/pull/251)).
- **2026-06-16** 🛡️ **보안/API 강화 + GLM/Zhipu alias**: Settings 쓰기는 인증 설정 시 auth가 필요합니다([#245](https://github.com/HKUDS/Vibe-Trading/pull/245)); API session의 shell-capable tools는 명시적인 `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` opt-in이 필요합니다([#243](https://github.com/HKUDS/Vibe-Trading/pull/243)); API key가 설정된 local shutdown도 auth가 필요합니다([#241](https://github.com/HKUDS/Vibe-Trading/pull/241)); loopback처럼 보이지만 신뢰할 수 없는 Host는 local로 취급하지 않고 거부합니다([#242](https://github.com/HKUDS/Vibe-Trading/pull/242)). 런타임 세부도 다듬었습니다: Web chat은 완료된 attempts와 동기화되고([#236](https://github.com/HKUDS/Vibe-Trading/pull/236)), run card는 유한하지 않은 metric을 strict JSON으로 출력하며([#238](https://github.com/HKUDS/Vibe-Trading/pull/238)), 잘못된 `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S`는 안전하게 fallback합니다([#240](https://github.com/HKUDS/Vibe-Trading/pull/240)). ddgs retry fallback도 regression coverage가 추가됐습니다([#239](https://github.com/HKUDS/Vibe-Trading/pull/239)). GLM/Zhipu는 first-class provider alias가 되었고 model-name inference도 추가됐습니다([#247](https://github.com/HKUDS/Vibe-Trading/pull/247), [#237](https://github.com/HKUDS/Vibe-Trading/issues/237) 종료).

- **2026-06-15** 🧭 **웹 검색 견고성 + Web UI 실행 연속성 수정**: `web_search`는 단일 엔진이 레이트리밋되어도 더 이상 실패하지 않습니다——이제 여러 무료·키 불필요 엔진(DuckDuckGo, Google, Bing, Brave, Mojeek, Yahoo)을 순서대로 조회하고 재시도/백오프를 적용하며, "결과 없음"을 오류가 아닌 빈 답변으로 처리하고, 모든 엔진이 제한될 때는 무미건조한 ❌ 대신 실행 가능한 메시지를 반환합니다(엔진 목록은 `VIBE_TRADING_SEARCH_BACKENDS`로 재정의 가능)([#232](https://github.com/HKUDS/Vibe-Trading/pull/232), [#231](https://github.com/HKUDS/Vibe-Trading/issues/231) 종료, @Ethan-sun01 님 감사합니다). Web UI에서는 실행 중 페이지를 전환해도 더 이상 멈추지 않습니다——채팅이 돌아올 때 라이브 스트림에 다시 구독하고 놓친 진행을 재생합니다([#234](https://github.com/HKUDS/Vibe-Trading/pull/234))——그리고 중지 버튼이 이터레이션 경계뿐 아니라 스트리밍 중과 도구 사이에서도 즉시 적용됩니다([#235](https://github.com/HKUDS/Vibe-Trading/pull/235)). 이로써 [#229](https://github.com/HKUDS/Vibe-Trading/issues/229)의 두 증상이 모두 해결됩니다(@kalkinj 님 감사합니다). baostock loader도 tushare 스타일 `601398.SH`와 함께 네이티브 `sh.601398` / `sz.000001` 코드를 받아들입니다([#230](https://github.com/HKUDS/Vibe-Trading/pull/230), @bhlt 님 감사합니다).

- **2026-06-14** 📊 **실행 단위 토큰 사용량 + Run Detail 차트 지연 로딩**: 이제 모든 agent 실행은 프로바이더가 보고한 토큰 사용량을 실행 범위의 `llm_usage.json`으로 영속화합니다——프로바이더/모델, 누적 합계, 이터레이션별 카운트——`/runs/{id}`에 추가로 노출되어, 실행이 끝나고 라이브 스트림이 사라진 뒤에도 토큰 비용을 감사할 수 있습니다(프로바이더 보고값만; prompt/내용 캡처나 가격 추정 없음)([#223](https://github.com/HKUDS/Vibe-Trading/pull/223), @LemonCANDY42 님 감사합니다). Run Detail 페이지는 더 이상 모든 심볼의 캔들을 처음부터 불러오지 않습니다: 기본 `/runs/{id}` 응답은 그대로 유지되지만, UI는 먼저 실행 요약을 렌더링한 뒤 옵트인 `?chart_payload=summary` / `?chart_symbol=` 모드로 각 심볼의 차트를 필요할 때 불러옵니다. 심볼별 로딩 상태와 "전체 로드 + 진행률" 컨트롤이 함께 제공됩니다([#225](https://github.com/HKUDS/Vibe-Trading/pull/225), @LemonCANDY42 님 감사합니다). 두 가지 loader 수정으로 마무리: yfinance의 배타적 `end` 경계가 요청 범위의 마지막 거래일을 더 이상 누락하지 않습니다——다운로드 호출은 `end + 1일`을 전달하고 캐시 키는 원래 범위를 유지합니다([#226](https://github.com/HKUDS/Vibe-Trading/pull/226), @gyx09212214-prog 님 감사합니다)——그리고 잘못된 `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` 값은 import 시 예외를 던져 시작을 막는 대신 경고하고 기본값으로 폴백합니다([#227](https://github.com/HKUDS/Vibe-Trading/pull/227), @gyx09212214-prog 님 감사합니다).
- **2026-06-13** ↩️ **CLI에서 ID로 과거 세션 재개**: 인터랙티브 CLI가 이제 종료 시 session-id를 출력하고, 복사해 붙여넣을 수 있는 `vibe-trading resume <session-id>` 힌트도 함께 보여줍니다——끝난 실행의 trace를 찾으려고 `agent/sessions/` 아래 어느 폴더가 타임스탬프상 가장 최신인지 추측할 필요가 더는 없습니다. 새 `vibe-trading resume <session-id>` 서브커맨드는 바로 그 세션을 다시 열고 최근 턴들을 loop에 재생합니다; 존재하지 않는 id는 빈 세션을 조용히 시작하는 대신 즉시 오류로 종료합니다([#218](https://github.com/HKUDS/Vibe-Trading/pull/218), @zwrong 님 감사합니다).
- **2026-06-12** 🩺 **프로바이더 신뢰성 전면 강화——DeepSeek 행, Kimi 접속, 스트리밍 라이브니스**: 일련의 프로바이더 리포트——DeepSeek 실행이 "Agent is working…"에서 멈춤([#208](https://github.com/HKUDS/Vibe-Trading/issues/208), @XYWOX 님 감사합니다), `reached max iterations`가 모델의 빈 응답을 가림([#203](https://github.com/HKUDS/Vibe-Trading/issues/203), @mojianliang 님 감사합니다), 멈춘 뒤 UI가 복구되지 않음([#195](https://github.com/HKUDS/Vibe-Trading/issues/195), @mafia23 님 감사합니다), Kimi가 클라이언트를 거부([#204](https://github.com/HKUDS/Vibe-Trading/issues/204), @liao497 님 감사합니다)——의 근본 원인은 하나였습니다: 모든 OpenAI 호환 프로바이더가 단일 shim을 공유하며 DeepSeek/Kimi/Gemini 고유 동작을 전역으로 적용하고 스트림 실패를 조용히 삼켰습니다. 이제 프로바이더별 동작은 명시적인 **케이퍼빌리티 계층**으로 이동——reasoning 캡처/재전송, Gemini thought signature, Kimi `User-Agent`, OpenRouter reasoning body가 각자의 프로바이더에만 적용되어 상호 오염이 없습니다. reasoning 전용 스트림은 실시간 **"Reasoning…"** 표시를 보여주고; 스트림 실패는 컨텍스트가 담긴 `provider_stream_error`를 발생시키며 일시적 끊김은 한 번 자동 재시도(결정적 4xx는 즉시 실패), 느린 비스트리밍 호출로의 조용한 폴백은 제거; 모델의 빈 응답은 `empty_model_response`로 정확히 진단; SSE 하트비트가 재연결 리플레이를 깨뜨리지 않으며; 멈춘 읽기 전용 도구는 타임아웃됩니다. 새 명령 **`vibe-trading provider doctor`**는 마스킹된 provider/모델/패키지/프록시 스냅샷을 출력해 환경 쪽 행을 한 번에 분류합니다. DeepSeek은 `pip install "vibe-trading-ai[deepseek]"`로 공식 네이티브 어댑터를 선택할 수 있고, kimi-k2.x의 `temperature=1` 요구는 자동 적용——Kimi 경로는 실제 API로 엔드투엔드 검증되었습니다(`kimi-k2.6` 도구 호출 + 엄격한 멀티턴 reasoning 재전송).

- **2026-06-11** 🐝 **swarm worker가 loader 계층을 통해 시장 데이터를 가져옵니다**: NVDA 투자위원회 실행에서 일련의 공백이 드러났습니다——worker가 임시 yfinance 스크립트를 직접 작성하고, 손상된 최신 봉(거래량은 있지만 OHLC가 빈)을 신뢰했으며, `NaN`이 비엄격 JSON으로 새고, 컨텍스트를 잃은 이어가기 프롬프트가 잘못된 preset으로 라우팅됐습니다([#198](https://github.com/HKUDS/Vibe-Trading/issues/198), 탁월한 진단과 두 수정 PR을 보내준 @BillDin 님 감사합니다). 이제 swarm worker는 MCP와 동일한 정규화 loader 레지스트리가 뒷받침하는 로컬 `get_market_data` 도구를 갖습니다——엄격한 JSON, 비유한 부동소수는 `null`로 직렬화——**모든 시장 데이터 preset**(13개 preset, 21개 worker)에 연결되고, 프롬프트 정책이 OHLCV 작업을 도구 우선으로 유도합니다([#199](https://github.com/HKUDS/Vibe-Trading/pull/199)). `run_swarm`은 명시적 `preset_name`을 받으며, 모호한 이어가기 조각은 `equity_research_team`으로 조용히 폴백하는 대신 거부됩니다([#200](https://github.com/HKUDS/Vibe-Trading/pull/200)). 그라운딩도 더 똑똑해졌습니다: swarm 프롬프트의 맨 미국 티커(예: `NVDA`)는 `NVDA.US`로 승격되어(불용어 가드) worker가 처음부터 신뢰할 수 있는 사전 조회 가격을 갖고 시작합니다. 이 도구는 메인 agent 레지스트리에도 합류——이제 **48개 도구**입니다. 또한: **Docker 데이터가 업데이트 후에도 유지됩니다**——영구 메모리, 세션 검색 인덱스, 사용자 생성 스킬, shadow account, broker 설정이 명명된 볼륨에 저장되어 `docker compose up --build`로 더 이상 지워지지 않습니다([#197](https://github.com/HKUDS/Vibe-Trading/issues/197), @FlyerJ 님 감사합니다).
- **2026-06-10** 🐳 **Docker가 호스트 측 Ollama에 기본으로 연결됩니다**: 컨테이너 안의 `localhost`는 컨테이너 자신을 가리키므로 기본 `OLLAMA_BASE_URL=http://localhost:11434`로는 Docker + Ollama 조합의 LLM 사전 점검이 항상 실패했습니다. `docker-compose.yml`이 이제 기본으로 `http://host.docker.internal:11434`를 가리키며(`OLLAMA_BASE_URL` 내보내기로 재정의 가능), `host-gateway`의 `extra_hosts` 매핑이 추가되어 Docker Desktop뿐 아니라 Linux에서도 같은 파일이 그대로 동작합니다([#196](https://github.com/HKUDS/Vibe-Trading/pull/196), @ShahNewazKhan 님 감사합니다).
- **2026-06-09** 🔑 **다른 컴퓨터에서 Web UI를 열 때의 오류 메시지 개선**: `API_AUTH_KEY`를 설정하지 않은 채 비루프백 클라이언트(다른 컴퓨터, VM 호스트, LAN의 휴대폰)에서 채팅에 접속하면 메시지 전송·세션 목록·live 상태 등 모든 민감한 엔드포인트가 `403`을 반환했지만, 채팅에는 일반적인 “Failed to send message, please retry.”만 표시됐습니다. 이제 전송 경로가 실제 이유——*“Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.”*——를 보여주며, README의 Web UI 설정 설명도 localhost와 LAN의 차이 및 세 가지 해결책(같은 컴퓨터에서 `localhost`로 접속 / `API_AUTH_KEY` 설정 후 Settings에 한 번 입력 / Docker Desktop 호스트 게이트웨이는 `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1`)을 명시했습니다([#191](https://github.com/HKUDS/Vibe-Trading/issues/191), @mafia23 님 감사합니다).
- **2026-06-08** 🔧 **Gemini 3.x 멀티턴 도구 호출 수정**: Gemini 3.x 사고 모델 수정을 완성했습니다. 6/05의 왕복([#176](https://github.com/HKUDS/Vibe-Trading/pull/176))은 인메모리 히스토리만 다뤘지만, 실제 agent loop는 히스토리를 OpenAI 형식 dict로 재생하며 LangChain이 요청 구성 전에 도구 호출별 `thought_signature`를 버렸기 때문에 멀티턴 도구 호출이 여전히 `missing thought_signature`로 400을 냈습니다. 이제 `invoke`와 `stream`이 공유하는 단일 길목 `_convert_input`에서 다시 부착됩니다(병렬 호출——N개 중 첫 번째만 서명됨——도 포함)([#184](https://github.com/HKUDS/Vibe-Trading/pull/184), @ngoanpv 님 감사합니다).
- **2026-06-07** 🐝 **채팅 타임라인의 실시간 swarm 상태**: agent가 멀티에이전트 swarm(투자위원회, 퀀트 데스크, 리스크 위원회……)을 시작하면 채팅에 각 worker의 상태——대기 / 실행 / 완료 / 실패 / 차단 / 재시도——를 실시간 스트리밍하는 인라인 **상태 카드**가 표시됩니다. 독립 swarm 대시보드와 동일한 에이전트별 가시성입니다. 런타임 이벤트는 기존 `/swarm/runs` API를 바꾸지 않고 세션 SSE 스트림으로 브리지되며, 재연결이나 히스토리 재생 시 완료된 카드가 최종 `run_swarm` 결과에서 복원됩니다([#188](https://github.com/HKUDS/Vibe-Trading/pull/188), @BillDin 님 감사합니다). preset 라우팅도 더 정밀해졌습니다: 명시적으로 지정한 preset(예: `investment_committee`, 밑줄 유무 무관)이 키워드 점수보다 우선하고, 맨 `IV` 파생상품 키워드가 “g**iv**en” 같은 일반 단어에 더 이상 오매칭되지 않습니다([#189](https://github.com/HKUDS/Vibe-Trading/pull/189), @BillDin 님 감사합니다).
- **2026-06-06** ⚖️ **Alpha 비교 — CLI / Web UI / REST / agent 전 영역 지원**: 새 `alpha compare`는 직접 고른 Alpha Zoo 팩터들을 같은 universe·기간에서 상호 비교하고 IC 평균/표준편차, IR, IC>0 비율, 샘플 수로 순위를 매기며 각 팩터와 선두의 격차를 보여줍니다. 전체 zoo bench와 달리 **지정한 팩터만** 평가합니다(새 `run_bench(only=…)` 부분집합 필터). 그래서 3개를 비교해도 zoo의 191개를 모두 돌리지 않습니다. 하나의 공유 코어가 모든 영역을 구동합니다: `vibe-trading alpha compare <id1> <id2> … --sort ir`(CLI), Alpha Zoo Web UI의 **Compare 뷰**(카탈로그에서 팩터 체크 → 원클릭 비교 + 스트리밍 순위표), `POST /alpha/compare` + SSE(REST), 읽기 전용 `alpha_compare` agent 도구(이제 **47개 도구**).
- **2026-06-05** 🇮🇳 **Dhan + Shoonya connector(인도) — 브로커 총 10곳**: connector-first 거래 레이어에 인도 시장용 **Dhan**과 **Shoonya**(NSE/BSE 주식 + F&O)가 추가되어 브로커가 총 10곳이 되었습니다. 둘 다 **페이퍼 + 읽기 전용**입니다 — Longbridge와 마찬가지로 API가 런타임 paper/live 구분자를 노출하지 않으므로 `place_order` / `cancel_order`가 첫 줄에서 비페이퍼 설정을 강하게 거부합니다(규칙: 런타임 paper/live 가드가 없는 브로커는 페이퍼 + 읽기 전용으로 제한)([#181](https://github.com/HKUDS/Vibe-Trading/pull/181), [#174](https://github.com/HKUDS/Vibe-Trading/issues/174) 종료). 이번 주기에는 **Gemini 2.5 / 3.x 사고 모델**도 수정했습니다: 도구 호출별 `thoughtSignature`가 OpenAI 호환 경로를 왕복하여 멀티턴 function calling이 `INVALID_ARGUMENT`로 실패하지 않습니다([#176](https://github.com/HKUDS/Vibe-Trading/pull/176), [#170](https://github.com/HKUDS/Vibe-Trading/issues/170) 종료, @mvanhorn & @jliu6789 님 감사합니다). **452개 전체 Alpha Zoo 팩터**에 중국어 docstring(中文名称/说明/用途)이 추가되었고([#180](https://github.com/HKUDS/Vibe-Trading/pull/180), @LeeCQiang 님 감사합니다), **프런트엔드 테스트 스위트(vitest 197개)**와 백엔드 인증 / 경로 탐색 / CORS 보안 테스트가 CI에 들어왔습니다([#175](https://github.com/HKUDS/Vibe-Trading/pull/175), @sambazhu 님 감사합니다).
- **2026-06-04** 🗃️ **전체 7개 데이터 소스 대상 옵트인 로컬 캐시**: 새 `VIBE_TRADING_DATA_CACHE` 스위치로 각 백테스트 loader——tushare, okx, ccxt, akshare, mootdx, yfinance, futu——가 확정된 과거 bar를 `~/.vibe-trading/cache`(사용자 홈, 저장소에는 절대 기록하지 않음)에 캐시하여, 반복 및 장기 / 크로스마켓 백테스트가 네트워크를 건너뛰고 제공자 레이트 제한을 피합니다. 기본값은 꺼짐. 배치 / 연결형 loader(yfinance, futu)는 캐시가 전부 적중하면 대량 다운로드 / FutuOpenD 연결을 완전히 건너뛰며, staleness 가드는 오늘로 끝나는 구간(마지막 bar가 아직 형성 중)을 절대 캐시하지 않고, 캐시된 프레임은 새로 가져온 것과 바이트 단위로 동일합니다([#177](https://github.com/HKUDS/Vibe-Trading/pull/177), @mvanhorn 님 감사합니다). AI / 자동화 지원 PR을 위한 기여자 가이드도 추가되어 안전한 로컬 점검과 고위험 broker/MCP/자격 증명 영역을 정리했습니다([#173](https://github.com/HKUDS/Vibe-Trading/pull/173)).
- **2026-06-03** 🧹 **커뮤니티 트리아지 + 트레이스 상관관계**: 도구 호출 트레이스 항목에 원본 `call_id`가 포함되어, run 트레이스를 재생할 때 `tool_result`를 해당 `tool_call`에 다시 매칭할 수 있습니다 — 인자 미리보기는 트레이스 파일을 작게 유지하기 위해 계속 잘린 상태로 둡니다([#168](https://github.com/HKUDS/Vibe-Trading/pull/168), @zwrong 님 감사합니다). 소스 주석은 외부 기여자가 찾을 수 없는 내부 전용 문서 경로를 더 이상 가리키지 않습니다([#166](https://github.com/HKUDS/Vibe-Trading/issues/166), @jaleelpersonal 님 감사합니다). 또한 설치 시 나타나는 `langchain-community` 의존성 해결 경고가 실패가 아니라 잔여 패키지로 인한 무해한 알림임을 명확히 했고([#167](https://github.com/HKUDS/Vibe-Trading/issues/167)), Gemini 2.5/3.0 함수 호출의 `thoughtSignature` 왕복 처리를 완전한 수정 계획이 포함된 `help wanted` 작업으로 정리했습니다([#170](https://github.com/HKUDS/Vibe-Trading/issues/170), @jliu6789 님 감사합니다).
- **2026-06-02** 🔌 **새 브로커 connector 6종(Tiger / Longbridge / Alpaca / OKX / Binance / Futu)**: connector-first 거래 레이어에 IBKR(로컬)·Robinhood(MCP)와 나란히 direct-SDK transport가 추가되었습니다. 각 connector는 읽기 전용 account / positions / orders / quote / history에 더해 페이퍼 계좌 주문 제출을 노출하므로, 이 브로커 페이퍼 계좌들에서 전략을 검증할 수 있습니다. 그중 5종(Tiger, Alpaca, OKX, Binance, Futu)은 Robinhood와 동일한 안전 모델 뒤에서 mandate로 게이트되는 bounded 주문 제출도 지원합니다 — 사용자가 커밋한 mandate(종목 universe / 주문 규모 / 익스포저 / 레버리지 / 일일 한도), 파일 수준 kill switch, fail-closed 사전 거래 게이트, 완전한 감사 원장. Longbridge는 페이퍼 + 읽기 전용 전용입니다(API가 런타임 paper/live 구분자를 노출하지 않음). 모든 paper/live 구분은 브로커별 구조적 가드입니다. 새 `trading_place_order` / `trading_cancel_order` 도구가 추가되었고, HK·A주 asset class가 mandate universe에 들어왔습니다. 실험적 / 사용에 따른 책임은 본인에게 있습니다.
- **2026-06-01** 🚀 **v0.1.9 출시**(`pip install -U vibe-trading-ai`): 0.1.8 이후 모든 것을 롤업했습니다. Connector-first 브로커 profile(IBKR 로컬 읽기 전용 TWS / IB Gateway + OAuth·커밋된 mandate·order guard·audit ledger·instant halt 뒤의 Robinhood Agentic Trading). CLI / REST / MCP / Web을 아우르는 Research Goal 런타임. swarm 패스 — live reconcile + MCP keepalive, operator가 설정한 worker MCP 도구, 엄격 alpha-bench 랜덤 컨트롤, 실패/오래된 run을 다시 실행하는 새 `retry_run`(이제 **36개 MCP tools**). `agent/cli/` 패키지 리팩토링 + 새 터미널 UI, `mootdx` 무토큰 A주 loader, backtest / agent loop / session 견고성 패스. `--version`은 이제 항상 설치된 패키지와 일치하여 0.1.8 드리프트를 수정합니다([#156](https://github.com/HKUDS/Vibe-Trading/issues/156)).
- **2026-05-31** 🔌 **Connector-first 브로커 아키텍처(IBKR + Robinhood)**: 거래 접근은 이제 별도의 브로커/live 진입점이 아니라 선택 가능한 connector profile에서 시작합니다. `vibe-trading connector list/use/check/account/positions/orders/quote/history`와 MCP `trading_*` 도구는 동일한 선택 profile을 공유하며, paper/live는 connector의 속성으로 다룹니다. IBKR은 로컬 읽기 전용 TWS / IB Gateway profile로 즉시 사용할 수 있고, 공식 IBKR 원격 MCP 경로는 안정적인 read tool 이름이 제공될 때까지 OAuth `mcp.read` probe로 seed되어 있습니다. Robinhood Agentic Trading은 계속 OAuth, 커밋된 mandate, order guard, audit ledger, instant halt 뒤에 있는 bounded live MCP connector입니다.
- **2026-05-30** 🧰 **견고성 패스 — backtest, agent loop, session**: LLM이 생성한 signal engine은 이제 인스턴스화 전에 인터페이스 사전 검증을 거칩니다. 순환 self-import, 누락된 `generate()`, 기본값 없는 `__init__` 인자, 잘못된 반환 타입 같은 흔한 실수를 조기에 잡아 원시 traceback 대신 실행 가능한 JSON 오류로 반환합니다 ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149)). 후속 작업으로 소스 수준 AST 검증 오류도 동일한 깔끔한 JSON 봉투에 실었습니다. agent loop는 더 이상 50회 반복을 모두 소진하고 출력 없는 `failed` 상태로 끝나지 않습니다 — swarm worker의 검증된 방식을 따라 반복 예산의 80%에서 wrap-up nudge를 주입하고 마지막 반복에서 tool 정의를 제거해 텍스트 답변을 강제합니다 ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148)). 중간에만 발동하도록 가드되어 research-goal 컨텍스트를 밀어내지 않습니다. session 메시지 쓰기는 이제 append마다 `flush + fsync`하여 비싼 AI 응답이 쓰기 도중 크래시에도 살아남고, 읽기 경로는 손상된 JSONL 줄을 건너뛰며(복구용으로 앞 200자 로깅) `/messages` 엔드포인트 전체를 500으로 만들지 않습니다 ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147)). Web 입력창은 IME Enter 처리도 수정해 조합 확정 Enter가 단어 도중에 전송되지 않도록 했습니다 ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146)).
- **2026-05-29** 🔐 **Robinhood Agentic Trading 지원(옵트인, 제한된 자율성)**: Robinhood Agentic Trading을 지원합니다(원격 MCP, OAuth). 기본적으로 비활성·읽기 전용이며, 에이전트는 사용자가 커밋한 mandate(종목/주문 규모/익스포저/레버리지/일일 한도) 범위 안에서만 자율 거래합니다. 파일 수준의 즉시 kill switch, 선제적 포지션 청산, mandate 자동 만료, 완전한 감사 원장, 영속 자율 runner를 갖췄습니다. 수탁 없음·거래소 없음 — 자금 보유와 체결은 브로커가 하고, 우리는 의도만 중계합니다. 실험적 / 사용에 따른 책임은 본인에게 있습니다.
- **2026-05-28** 🧪 **Swarm 안전성 + 엄격 alpha 게이트 + worker MCP**: Swarm DAG가 상위 태스크 실패 시 하위 태스크를 차단합니다 ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). 새 `run_bench_strict()`는 IC 게이트 위에 동일 universe 랜덤 컨트롤 + 학습/테스트 OOS 분할을 추가해 시장 beta만 따라가는 가짜 factor를 잡아냅니다 ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), @Soli22de 감사). Swarm worker는 이제 operator가 설정한 외부 MCP server를 호출할 수 있으며 신뢰 경계는 전용 테스트로 고정되어 있습니다 ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), @shadowinlife 감사).
- **2026-05-27** 📊 **mootdx A주 데이터 소스 + 출력 정리**: 새 `mootdx` loader는 네이티브 通达信 TCP 프로토콜로 A주 OHLCV를 가져옵니다(인증 불필요, IP 속도 제한 없음, 일봉 + 분봉의 25 페이지 walk-back 페이지네이션). fallback chain에서 tushare와 akshare 사이에 위치합니다 ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). CCXT loader는 이제 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`를 읽어 제한된 네트워크에서 Binance/OKX 공개 데이터를 가져올 수 있습니다 ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), @ruok808 감사). 최종 답변 렌더링에서도 CLI와 Web의 보기 흉한 전체 너비 `---` 구분자를 제거했습니다: system prompt는 markdown 테이블과 `##` 헤딩 사용을 유도하고, CLI 렌더러는 독립 HR을 defense-in-depth로 제거하며, 채팅 버블은 빠져나온 `<hr>`을 숨깁니다 ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), @sdwxm188 감사).
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
| **사전 빌드된 alpha zoo 벤치** | 456개의 alpha 인자(Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart)에 대해 한 줄 CLI로 IC + IR + alive/reversed/dead 분류 수행 |

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

## 📡 데이터 소스 & 스마트 폴백

`get_market_data` 한 번의 호출, **18개 시장 데이터 소스**. `source: "auto"`로 설정하면 로더가 심볼에 따라 소스를 고르고, 시장별 체인을 **IP 차단 위험** 순으로 따라갑니다: 절대 차단되지 않는 공개 소스를 먼저, 속도 제한 / 키 기반 소스를 마지막에 둡니다. 설정 불필요, 단일 장애 지점 없음.

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share | none | never IP-banned (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / futures / fund / macro | token | richest A-share |
| `yahoo` · `sina` · `stooq` | US (/HK) | none | direct chart/quotes/options · K-line to 1984 · EOD CSV |
| `yfinance` | US / HK | none | wrapper |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `okx` · `ccxt` | crypto | none | OKX + 100+ exchanges |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

**폴백 체인 (IP 차단 위험 순):**

- **A주** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **미국** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `akshare` · `local`
- **홍콩** → `eastmoney` · `yahoo` · `futu` · `yfinance` · `akshare` · `local`
- **크립토** → `okx` · `ccxt` · `yfinance` · `local` &nbsp;·&nbsp; *(선물 / 펀드 / 매크로 / 외환 → `tushare`/`akshare` → `local`)*

OHLCV를 넘어 **18개 읽기 전용 데이터 도구**가 펀더멘털과 자금 흐름까지 닿습니다 — 자금 흐름, 용호방(dragon-tiger), 북향(northbound), 신용거래, 대종거래, 주주 수, 보호예수, 섹터, 리서치 리포트, 뉴스, SEC 공시, 재무제표, 옵션 체인, 기관 보유, 시장 스크리닝, 심볼 검색, 매크로 — 모두 MCP로 노출됩니다. 명시적인 `local:` 심볼은 절대 조용히 네트워크 소스로 폴백하지 않습니다.

---

## 🔩 상세 기능

메인 README를 읽기 쉽게 유지하기 위해 상세 목록은 아래에 접어 두었습니다. 사용 가능한 구성 요소를 확인하고 싶을 때 열어보세요.

<details>
<summary><b>금융 스킬 라이브러리</b> <sub>8개 카테고리 79개 스킬</sub></summary>

- 📊 8개 카테고리로 구성된 79개 전문 금융 스킬
- 🌐 전통 시장부터 크립토 & DeFi까지 완전한 커버리지
- 🔬 데이터 sourcing부터 정량 리서치까지 포괄하는 기능

| 카테고리 | 스킬 | 예시 |
|----------|------|------|
| Data Source | 9 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 17 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 11 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `alpha-zoo` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>커스텀 데이터 소스</b> <sub>직접 만든 과거 OHLCV loader 등록</sub></summary>

loader를 기본 제공하지 않는 시장이나 벤더가 필요하신가요? 직접 과거 봉 loader를
추가하고 `source="<name>"`으로 선택하세요. 아래 단계는 패키지 소스를 수정하므로
clone에서 실행하세요(`pip install -e .`).

1. **loader 작성** —— `agent/backtest/loaders/<name>_loader.py`를 만들고
   `DataLoaderProtocol`을 만족하는 클래스(duck-typed, 기반 클래스 불필요)를 정의한 뒤
   `@register`를 붙입니다:

   ```python
   import pandas as pd
   from backtest.loaders.registry import register

   @register
   class DataLoader:
       name = "mysource"            # the value you pass as source=
       markets = {"us_equity"}      # a_share/us_equity/hk_equity/crypto/futures/fund/macro/forex
       requires_auth = False

       def is_available(self) -> bool:
           return True              # token present? network reachable?

       def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
           # return {symbol: DataFrame indexed by trade_date,
           #         columns: open, high, low, close, volume}
           ...
   ```

2. **모듈 등록** 으로 `@register`가 실행되게 —— `agent/backtest/loaders/registry.py`의
   `_loader_modules`에 `"backtest.loaders.<name>_loader"`를 추가합니다.
3. **이름 허용** 으로 설정 검증 통과 —— `agent/backtest/runner.py`의
   `_VALID_SOURCES`에 `"mysource"`를 추가합니다.
4. *(선택)* `registry.py`의 특정 시장 `FALLBACK_CHAINS`에 넣으면
   `source="auto"`로도 도달할 수 있습니다.
5. **사용** —— 백테스트 설정에서 `source="mysource"`, 또는 CLI / agent를 통해.

> **실시간 ticks / 호가창 depth는 loader 범위 밖입니다** —— loader 계층은
> point-in-time 과거 봉만 다룹니다. 실시간 시장 데이터는 broker connector를
> 통합니다: 암호화폐는 `okx` / `binance` / `ccxt`, 주식은 `futu` / `tiger`.

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
<summary><b>Alpha Zoo</b> <sub>4개 zoo에 걸친 456개 사전 빌드된 quant alpha</sub></summary>

- 🧬 operator 계층에서 lookahead가 금지된 456개 cross-sectional alpha
- 📈 한 줄 CLI로 IC + IR + alive/reversed/dead 분류 수행
- 🔬 AST 순수성 게이트 + 300-row lookahead sentinel 테스트 + `pytest-socket` 네트워크 kill-switch
- 📦 Qlib에 대한 Apache-2 출처 표기, zoo별 `LICENSE.md`에서 수식을 수학적 콘텐츠로 명시
- 🤝 커뮤니티 PR을 위한 Developer Certificate of Origin (DCO) 서명 워크플로

| Zoo | Count | Source | License |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0, 커밋 고정) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991 | 수식은 수학적 콘텐츠 |
| **gtja191** | 191 | 국태군안 (2014), "191 Short-period Trading Alpha Factors" | 수식은 수학적 콘텐츠 |
| **academic** | 10 | Fama-French 5 + Carhart 모멘텀 (가격 기반 proxy) + Jegadeesh reversal + George-Hwang 52-week-high + Amihud illiquidity + Harvey-Siddique skew | 공개 학술 문헌 |

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

> **이전 버전에서 업그레이드하시나요?** 0.1.10은 LangChain 1.x로 이전했습니다. 0.1.10 이전 설치 위에서 `pip install -U vibe-trading-ai`를 실행한 후 임포트가 깨지면(예: langgraph 임포트 실패) venv를 다시 만들거나 `pip install --force-reinstall vibe-trading-ai`를 실행하세요. 새로 설치한 경우에는 영향이 없습니다.

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

> [!NOTE]
> `vibe-trading serve` 는 `0.0.0.0` 에 바인딩되지만 기본적으로 루프백만 신뢰합니다. **같은 컴퓨터**에서 UI를 열면(`http://localhost:8899`) 설정 없이 작동합니다. **다른 컴퓨터, VM 호스트, LAN의 휴대폰**에서 접속하면 민감한 엔드포인트가 `403` 을 반환하고 채팅에 “Remote API access requires an API key” 가 표시됩니다. `agent/.env` 에 강력한 `API_AUTH_KEY` 를 설정하고 재시작한 뒤 **Settings** 에서 같은 키를 입력하세요. (Docker Desktop 호스트 게이트웨이의 경우: 기본 `127.0.0.1` 포트 바인딩을 유지한 채 `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` 설정.)

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
vibe-trading alpha list    # 사전 빌드된 456개 alpha 탐색; show / bench / compare / export-manifest 서브커맨드 사용 가능
```

<details>
<summary><b>TUI 내 slash commands</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | 모든 명령 표시 |
| `/skills` | 79개 finance skills 목록 |
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
| `POST` | `/scheduled-runs` | 예약 리서치 작업 생성 (interval-ms 또는 cron) |
| `GET` | `/scheduled-runs` | 예약된 작업 목록 |
| `DELETE` | `/scheduled-runs/{job_id}` | 예약 작업 취소 |

Interactive docs: `http://localhost:8899/docs`

### 보안 기본값

localhost 개발에서 `vibe-trading serve`는 browser workflow를 단순하게 유지합니다. non-local client에서는 민감한 API endpoint에 `API_AUTH_KEY`가 필요합니다. JSON/upload request에는 `Authorization: Bearer <key>`를 사용하세요. Browser EventSource stream은 Web UI Settings에 같은 key를 한 번 입력하면 Web UI가 처리합니다.

Shell-capable tools는 local CLI와 trusted localhost workflow에서 사용할 수 있지만, `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`을 명시적으로 설정하지 않는 한 remote API session에는 노출되지 않습니다. Document와 journal reader는 기본적으로 upload/import roots로 제한됩니다. 파일은 `agent/uploads`, `agent/runs`, `./uploads`, `./data`, `~/.vibe-trading/uploads`, `~/.vibe-trading/imports` 아래에 두거나, `VIBE_TRADING_ALLOWED_FILE_ROOTS`로 전용 directory를 추가하세요.

### Web UI Settings

Web UI Settings page에서는 local user가 LLM provider/model, base URL, generation parameters, reasoning effort, Tushare token 같은 선택적 market data credentials를 업데이트할 수 있습니다. Settings는 `agent/.env`에 저장되며 provider defaults는 `agent/src/providers/llm_providers.json`에서 로드됩니다.

Settings read는 side effect가 없습니다. `GET /settings/llm`과 `GET /settings/data-sources`는 `agent/.env`를 만들지 않으며 project-relative path만 반환합니다. Settings read/write는 credential state를 노출하거나 credential/runtime environment를 업데이트할 수 있으므로 `API_AUTH_KEY`가 설정되어 있으면 인증이 필요합니다. dev mode에서 `API_AUTH_KEY`가 설정되지 않은 경우 settings access는 loopback client에서만 허용됩니다.

### Scheduled research (예약 리서치)

리서치 prompt나 backtest를 반복 일정으로 실행합니다. 백그라운드 executor는 **기본적으로 꺼져 있습니다** — `VIBE_TRADING_ENABLE_SCHEDULER=1`로 server를 시작하면 활성화됩니다:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

그런 다음 REST로 작업을 생성합니다. `schedule`은 단순 정수(간격, 단위 **밀리초**)이거나 5필드 cron 표현식(`분 시 일 월 요일`)입니다:

```bash
# 6시간마다 (cron)
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan CSI300 for momentum breakouts and backtest the top 5","schedule":"0 */6 * * *"}'

# 목록 / 취소
curl http://localhost:8899/scheduled-runs
curl -X DELETE http://localhost:8899/scheduled-runs/<job_id>
```

각 실행은 새 agent session에서 `prompt`를 실행하며(선택적 backtest 파라미터는 `config`에 넣습니다), 작업은 `~/.vibe-trading/`에 저장되어 재시작 후에도 유지됩니다. 이 플래그가 없으면 `/scheduled-runs` endpoint는 작업을 기록하지만 실행되지는 않습니다. `API_AUTH_KEY`가 설정된 경우 각 호출에 `-H "Authorization: Bearer <key>"`를 추가하세요.

---

## 🔌 MCP Plugin

Vibe-Trading은 모든 MCP-compatible client를 위해 54개 MCP tools를 제공합니다. stdio subprocess로 실행되므로 server setup이 필요 없습니다. 핵심 research tools는 HK/US/crypto에서 API key 없이 작동하고, trading connector tools는 선택된 connector profile을 사용하며, `run_swarm`만 LLM key가 필요합니다.

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

**노출되는 MCP tools(54):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`.

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

79개 finance skills는 모두 [open-space.cloud](https://open-space.cloud)에 게시되어 있으며 OpenSpace의 self-evolution engine을 통해 자율적으로 발전합니다.

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

OpenSpace는 79개 skills를 모두 자동 발견하여 auto-fix, auto-improve, community sharing을 활성화합니다. OpenSpace-connected agent에서 `search_skills("finance backtest")`로 Vibe-Trading skills를 검색하세요.

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
│   ├── mcp_server.py               # MCP server — 54 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (79 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 68 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 4개 zoo에 걸친 456개 alpha
│   │   │   ├── base.py             #   19개 operator (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST-only 메타데이터 로딩 + lazy compute + sanity gate
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead 분류
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (10)
│   │   │
│   │   ├── api/                    # FastAPI 라우트 모듈
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 79 finance skills in 8 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   29 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   7 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   18 sources: tushare, okx, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp
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
| **Research Autopilot** | 수동 실행 우선 research loop: hypothesis → deterministic backtest → evidence report | 1–3단계 출시 |
| **Data Bridge** | Bring-your-own data: local CSV/Parquet/SQL connectors with schema mapping | 로컬 로더 출시 |
| **Options Lab** | Vol surface, Greeks dashboard, payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray, constraints, turnover-aware optimizer, rebalance notes | Planned |
| **Alpha Zoo** | 4개 zoo에 걸친 452개의 사전 빌드된 alpha 인자(Qlib 158 + Kakushadze 101 + GTJA 191 + FF5 + Carhart), 한 줄 CLI 벤치, agent 통합, Web UI | **0.1.8 출시 완료** |
| **Research Delivery** | Slack / Telegram / email-style channels로 예약 brief 전달 | 스케줄러 출시 |
| **Community** | 공유 가능한 skills, presets, strategy cards | Exploring |

---

## 기여하기

기여를 환영합니다! 가이드는 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

**Good first issues**는 [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 라벨이 붙어 있습니다. 하나를 골라 시작해 보세요.

더 큰 기여를 하고 싶나요? 위 [로드맵](#-로드맵)을 확인하고 시작 전에 issue를 열어 논의해 주세요.

---

## 기여자

Vibe-Trading에 기여해 주신 모든 분께 감사드립니다!

최근 v0.1.10 cycle contributors and credits:

- @Hinotoi-agent — a security-hardening wave: local-shutdown auth (#241), loopback-host rebinding rejection (#242), agent shell-tool opt-in (#243), settings-write auth (#245), mandate proposal-id containment (#256), persistent-memory type validation (#257), and MCP swarm run-id containment (#258)
- @mvanhorn — the opt-in local data cache (#177), Gemini thoughtSignature round-trip over OpenAI-compat tool calls (#176), the custom data loader guide (#194), and the glm/zhipu provider alias + model-name inference (#247)
- @gyx09212214-prog — loader robustness for malformed crypto/RSSHub timeout env vars (#227, #240), requested yfinance end-date inclusion (#226), strict run-card JSON for non-finite metrics (#238), and ddgs retry-fallback coverage (#239)
- @BillDin — swarm agent status in the chat UI (#188), explicit preset-name handling (#189), the loader-backed market-data tool for swarm workers (#199), and preset-context continuations (#200)
- @Robin1987China — the Research Autopilot goal-hypothesis bridge (#260), the local CSV/Parquet/DuckDB data loader (#252), and an assistant-prefill fix + configurable Kimi User-Agent (#248)
- @LemonCANDY42 — the read-only runtime status dashboard (#210), persisted AgentLoop usage artifacts (#223), and opt-in Run Detail chart payloads (#225)
- @zwrong — the trace.jsonl overhaul with zero truncation + offload (#206) and session-id on exit + `resume <session-id>` (#218)
- @forge-builder — the AI contributor guide (#173) and the OpenClaw MCP research-only smoke-test docs (#165)
- @skloxo — Chinese (zh-CN) frontend localization (adopted from #217)
- @LeeCQiang — Chinese docstrings across all 452 Alpha Zoo factors (#180)
- @KaiLuettmann — GHCR pre-built image publishing on release (#187)
- @ngoanpv — Gemini thought_signature preservation through the AgentLoop dict path (#184)
- @ShahNewazKhan — Docker host-Ollama reachability via host.docker.internal (#196)
- @sambazhu — frontend sync of completed chat attempts (#236)
- @bhlt — baostock-native code format support (#230)
- @octo-patch — MiniMax M3 default model upgrade (#162)
- @warren618 / Haozhe Wu — the global data layer (8 sources + 18 read-only data tools), the 10 broker SDK connectors, the alpha-compare full stack, the provider-reliability overhaul, multi-engine web_search fallback, responsive Stop + SSE reconnect, and release integration

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
