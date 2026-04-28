<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <b>한국어</b> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading 로고"/>
</p>

<h1 align="center">Vibe-Trading: 당신의 개인 트레이딩 에이전트</h1>

<p align="center">
  <b>한 번의 명령으로 에이전트를 종합 트레이딩 기능으로 강화</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <img src="https://img.shields.io/badge/Skills-72-orange" alt="Skills">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="Swarm">
  <img src="https://img.shields.io/badge/Tools-27-0F766E" alt="Tools">
  <img src="https://img.shields.io/badge/Data_Sources-6-2563EB" alt="Data Sources">
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-주요-기능">기능</a> &nbsp;&middot;&nbsp;
  <a href="#-데모">데모</a> &nbsp;&middot;&nbsp;
  <a href="#-vibe-trading이란">개요</a> &nbsp;&middot;&nbsp;
  <a href="#-빠른-시작">시작하기</a> &nbsp;&middot;&nbsp;
  <a href="#-cli-참조">CLI</a> &nbsp;&middot;&nbsp;
  <a href="#-api-서버">API</a> &nbsp;&middot;&nbsp;
  <a href="#-mcp-플러그인">MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-프로젝트-구조">구조</a> &nbsp;&middot;&nbsp;
  <a href="#-로드맵">로드맵</a> &nbsp;&middot;&nbsp;
  <a href="#기여하기">기여</a> &nbsp;&middot;&nbsp;
  <a href="#기여자">기여자</a>
</p>

<p align="center">
  <a href="#-빠른-시작"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 뉴스

- **2026-04-28** 🚀 **v0.1.6 릴리스**（`pip install -U vibe-trading-ai`）: `pip install` / `uv tool install` 설치 후 `vibe-trading --swarm-presets`가 비어 있는 문제 수정([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)) — 프리셋 YAML을 `src.swarm` 패키지 내부에 번들링, 6개 회귀 테스트로 고정. 또한 AKShare 로더가 ETF(`510300.SH`)와 외환(`USDCNH`)을 올바른 엔드포인트로 라우팅하고 레지스트리 폴백 강화. v0.1.5 이후 업데이트 종합: 벤치마크 비교 패널, `/upload` 스트리밍 + 크기 제한, Futu 로더(HK + A주), vnpy 내보내기 스킬, 보안 강화, 프론트엔드 지연 로딩(688KB → 262KB).
- **2026-04-27** 📊 **벤치마크 비교 패널 + 업로드 안전성**: 백테스트 출력에 벤치마크 비교 패널(티커 / 벤치마크 수익률 / 초과 수익률 / 정보 비율) 추가, yfinance로 SPY · CSI 300 등 자동 해석([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). 또한 `/upload` 엔드포인트를 1MB 청크 스트리밍으로 전환, `MAX_UPLOAD_SIZE` 초과 시 즉시 중단 + 부분 파일 정리. 50MB 상한이 악성/초대형 요청에도 실효화([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)) — 4개 회귀 테스트로 고정.
- **2026-04-22** 🛡️ **하드닝 + 신규 연동**: `safe_path`에 경로 컨테인먼트 강제 + 거래 명세서/섀도우 계정 도구 샌드박스화, `MANIFEST.in` 추가로 sdist에 `.env.example` / 테스트 / Docker 파일 포함, 프론트엔드 라우트 단위 지연 로딩으로 초기 번들 688KB → 262KB. 또한 Futu 홍콩/A주 데이터 로더([#47](https://github.com/HKUDS/Vibe-Trading/pull/47))와 vnpy CtaTemplate 내보내기 스킬([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)) 추가.

<details>
<summary>이전 뉴스</summary>

- **2026-04-21** 🛡️ **워크스페이스 + 문서**: 상대 `run_dir`을 활성 run 디렉토리로 정규화([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). README 사용 예제 추가([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **추론 모델 + Swarm 수정**: `reasoning_content`을 모든 `ChatOpenAI` 직렬화 경로에서 보존 — Kimi / DeepSeek / Qwen thinking 엔드투엔드 작동([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). Swarm 스트리밍 + 깔끔한 Ctrl+C 종료([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: PyPI 및 ClawHub에 게시. `python-multipart` CVE 하한 버전 업데이트, 5개 신규 MCP 도구 연결(`analyze_trade_journal` + 4개 섀도우 계정 도구), `pattern_recognition` → `pattern` 레지스트리 이름 불일치 수정, Docker 의존성 동기화, SKILL 매니페스트 동기화(22개 MCP 도구 / 71개 스킬).
- **2026-04-18** 👥 **섀도우 계정 Shadow Account**: 증권사 거래 명세서에서 자신의 전략 규칙을 추출 → 여러 시장에서 섀도우 백테스트 실행 → 8개 섹션 HTML/PDF 리포트가 어디에서 얼마를 놓쳤는지(규칙 위반, 조기 익절, 놓친 시그널, 역방향 거래) 정확히 보여줌. 신규 도구 4개, 신규 스킬 1개, 총 32개 도구. Trade Journal / Shadow Account 샘플 프롬프트가 Web UI 웰컴 화면에 추가.
- **2026-04-17** 📊 **거래 명세서 분석기 + 유니버설 파일 리더**: 증권사 거래 명세서(同花顺/东财/富途/일반 CSV) 업로드 → 거래 프로필(보유 일수, 승률, 손익비, 최대 드로다운) + 4가지 행동 편향 진단(처분 효과, 과잉 거래, 추격 매수, 앵커링) 자동 생성. `read_document`는 이제 PDF, Word, Excel, PowerPoint, 이미지(OCR), 40+ 텍스트 형식을 하나의 호출로 통합 처리.
- **2026-04-16** 🧠 **에이전트 하네스**: 크로스세션 영구 메모리, FTS5 세션 검색, 자가 진화 스킬(전체 CRUD), 5계층 컨텍스트 압축, 읽기/쓰기 도구 배치 처리. 27개 도구, 107개 신규 테스트.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.ai 제공자 추가([#35](https://github.com/HKUDS/Vibe-Trading/pull/35)), MiniMax temperature 수정 + 모델 업데이트([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13개 제공자.
- **2026-04-14** 🔧 **MCP 안정성**: 백테스트 도구의 stdio 전송에서 `Connection closed` 오류 수정([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **크로스마켓 복합 백테스트**: 새 `CompositeEngine`으로 서로 다른 시장 종목(예: A주 + 암호화폐)을 공유 자금 풀로 동시 백테스트, 시장 규칙은 종목별 적용. Swarm 템플릿 변수 폴백 및 프론트엔드 타임아웃도 수정.
- **2026-04-12** 🌍 **멀티 플랫폼 내보내기**: `/pine`으로 TradingView (Pine Script v6), TDX (통달신/동화순/동방재부), MetaTrader 5 (MQL5) 한 번에 내보내기.
- **2026-04-11** 🛡️ **안정성 및 DX**: `vibe-trading init` .env 부트스트랩([#19](https://github.com/HKUDS/Vibe-Trading/pull/19)), 프리플라이트 체크, 데이터소스 폴백, 백테스트 엔진 강화. 다국어 README([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: Docker 수정([#8](https://github.com/HKUDS/Vibe-Trading/issues/8)), `web_search` MCP 도구, 12개 LLM 제공자, `akshare`/`ccxt` 의존성. PyPI와 ClawHub에 게시.
- **2026-04-09** 📊 **Backtest Wave 2**: ChinaFutures, GlobalFutures, Forex, Options v2 엔진. 몬테카를로, Bootstrap CI, 워크포워드 검증.
- **2026-04-08** 🔧 **다중 시장 백테스트**: 시장별 규칙, Pine Script v6 내보내기, 자동 폴백 5개 데이터 소스.

</details>

---

## 💡 Vibe-Trading이란?

Vibe-Trading은 AI 기반 멀티 에이전트 금융 워크스페이스로, 자연어 요청을 전 세계 시장의 실행 가능한 트레이딩 전략, 리서치 인사이트, 포트폴리오 분석으로 전환합니다.

### 핵심 역량:
• **자연어 → 전략** — 아이디어를 설명하면 에이전트가 코드 작성, 테스트, 내보내기까지 실행<br>
• **5개 데이터 소스, 무설정** — A주, HK/US, 크립토, 선물, FX 자동 폴백<br>
• **29개 전문 팀** — 투자, 트레이딩, 리스크를 위한 멀티 에이전트 스웜 워크플로우<br>
• **크로스세션 메모리** — 선호도와 인사이트를 기억하고 재사용 가능한 스킬을 자동 생성·진화<br>
• **7개 백테스트 엔진** — 크로스마켓 복합 테스트 + 통계 검증 + 4개 옵티마이저<br>
• **멀티 플랫폼 내보내기** — 클릭 한 번으로 TradingView, TDX(통달신/동화순), MetaTrader 5

---

## ✨ 주요 기능

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="Research"/><br>
      <h3>🔍 트레이딩용 DeepResearch</h3>
      <img src="https://img.shields.io/badge/72_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="Skills" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 72개 전문 스킬 + 크로스세션 영구 메모리<br>
        • 자가 진화: 에이전트가 경험으로부터 워크플로우를 생성·개선<br>
        • 5계층 컨텍스트 압축 — 긴 대화에서도 정보 손실 없음<br>
        • 전 금융 도메인에 걸친 자연어 태스크 라우팅
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="Swarm"/><br>
      <h3>🐝 스웜 인텔리전스</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="Swarm" /><br><br>
      <div align="left">
        • 29개 즉시 사용 가능한 트레이딩 팀 프리셋<br>
        • DAG 기반 멀티 에이전트 오케스트레이션<br>
        • 실시간 스트리밍 대시보드(에이전트 상태 표시)<br>
        • FTS5 크로스세션 검색으로 모든 과거 대화 검색
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-backtest.png" height="150" alt="Backtest"/><br>
      <h3>📊 크로스마켓 백테스트</h3>
      <img src="https://img.shields.io/badge/5_Data_Sources-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="Backtest" /><br><br>
      <div align="left">
        • A주, 홍콩/미국 주식, 크립토, 선물 및 FX<br>
        • 7개 시장 엔진 + 크로스마켓 복합 엔진(공유 자금 풀)<br>
        • 통계 검증: 몬테카를로, Bootstrap CI, 워크포워드<br>
        • 15+ 성과 지표 및 4개 옵티마이저
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-quant.png" height="150" alt="Quant"/><br>
      <h3>🧮 퀀트 분석 툴킷</h3>
      <img src="https://img.shields.io/badge/Quant_Tools-C77DFF?style=for-the-badge&logo=wolfram&logoColor=white" alt="Quant" /><br><br>
      <div align="left">
        • 팩터 IC/IR 분석 및 분위 백테스트<br>
        • 블랙-숄즈 가격 산출 및 풀 그릭스 계산<br>
        • 기술적 패턴 인식 및 감지<br>
        • MVO/리스크 패리티/BL 기반 포트폴리오 최적화
      </div>
    </td>
  </tr>
</table>

## 7개 카테고리에 걸친 72개 스킬

- 📊 7개 카테고리에 조직된 72개 금융 스킬
- 🌐 전통 시장부터 크립토·DeFi까지 완전 커버리지
- 🔬 데이터 소싱부터 정량 리서치까지 포괄적 기능

| 카테고리 | 스킬 | 예시 |
|----------|------|------|
| Data Source | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 15 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 8 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader` |

## 29개 에이전트 스웜 팀 프리셋

- 🏢 29개 즉시 사용 가능한 에이전트 팀
- ⚡ 사전 구성된 금융 워크플로우
- 🎯 투자, 트레이딩 및 리스크 관리 프리셋

| 프리셋 | 워크플로우 |
|--------|------------|
| `investment_committee` | 불/베어 토론 → 리스크 리뷰 → PM 최종 결정 |
| `global_equities_desk` | A주 + HK/US + 크립토 리서처 → 글로벌 전략가 |
| `crypto_trading_desk` | 펀딩/베이시스 + 청산 + 플로우 → 리스크 매니저 |
| `earnings_research_desk` | 펀더멘털 + 리비전 + 옵션 → 실적 전략가 |
| `macro_rates_fx_desk` | 금리 + FX + 원자재 → 매크로 PM |
| `quant_strategy_desk` | 스크리닝 + 팩터 리서치 → 백테스트 → 리스크 감사 |
| `technical_analysis_panel` | 클래식 TA + 일목균형표 + 하모닉 + 엘리엇 + SMC → 컨센서스 |
| `risk_committee` | 드로다운 + 테일 리스크 + 레짐 리뷰 → 승인 |
| `global_allocation_committee` | A주 + 크립토 + HK/US → 크로스마켓 배분 |

<sub>추가로 20+ 특화 프리셋 — 모든 항목은 vibe-trading --swarm-presets로 확인.</sub>

### 🎬 데모

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
<td colspan="2" align="center"><sub>☝️ 자연어 백테스트 & 멀티 에이전트 스웜 토론 — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 빠른 시작

### 한 줄 설치 (PyPI)

```bash
pip install vibe-trading-ai
```

> **패키지 이름 vs 명령:** PyPI 패키지는 `vibe-trading-ai`입니다. 설치하면 세 가지 명령을 얻습니다:
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | 인터랙티브 CLI / TUI |
> | `vibe-trading serve` | FastAPI 웹 서버 실행 |
> | `vibe-trading-mcp` | MCP 서버 시작(Claude Desktop, OpenClaw, Cursor 등) |

```bash
vibe-trading init              # 인터랙티브 .env 설정
vibe-trading                   # CLI 실행
vibe-trading serve --port 8899 # 웹 UI 실행
vibe-trading-mcp               # MCP 서버 시작(stdio)
```

### 또는 경로 선택

| Path | 최적 용도 | 소요 시간 |
|------|-----------|-----------|
| **A. Docker** | 즉시 체험, 로컬 설정 없음 | 2분 |
| **B. Local install** | 개발, 전체 CLI 접근 | 5분 |
| **C. MCP plugin** | 기존 에이전트에 플러그인 | 3분 |
| **D. ClawHub** | 한 줄 설치, 클론 불필요 | 1분 |

### 사전 요구사항

- 지원 제공자의 **LLM API 키** — 또는 **Ollama** 로컬 실행(키 불필요)
- 경로 B용 **Python 3.11+**
- 경로 A용 **Docker**

> **지원 LLM 제공자:** OpenRouter, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama(로컬). 설정은 `.env.example` 참고.

> **팁:** 모든 시장은 자동 폴백 덕분에 API 키 없이도 작동합니다. yfinance(HK/US), OKX(크립토), AKShare(A주, 미국, HK, 선물, FX)는 모두 무료입니다. Tushare 토큰은 선택 사항 — AKShare가 A주 무료 폴백을 제공합니다.

### 경로 A: Docker (설정 불필요)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# agent/.env 수정 — 사용할 LLM 제공자를 주석 해제하고 API 키 설정
docker compose up --build
```

`http://localhost:8899`를 엽니다. 백엔드 + 프런트엔드가 하나의 컨테이너에 있습니다.

### 경로 B: 로컬 설치

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# 활성화
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # 편집 — LLM 제공자 API 키 설정
vibe-trading                       # 인터랙티브 TUI 실행
```

<details>
<summary><b>웹 UI 시작(선택 사항)</b></summary>

```bash
# 터미널 1: API 서버
vibe-trading serve --port 8899

# 터미널 2: 프런트엔드 개발 서버
cd frontend && npm install && npm run dev
```

`http://localhost:5899`를 엽니다. 프런트엔드는 `localhost:8899`로 API를 프록시합니다.

**프로덕션 모드(단일 서버):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI가 dist/를 정적 파일로 서빙
```

</details>

### 경로 C: MCP 플러그인

아래 [MCP 플러그인](#-mcp-플러그인) 섹션을 참조하세요.

### 경로 D: ClawHub (한 줄)

```bash
npx clawhub@latest install vibe-trading --force
```

스킬과 MCP 설정이 에이전트의 스킬 디렉터리에 다운로드됩니다. 자세한 내용은 [ClawHub 설치](#-mcp-플러그인)를 참고하세요.

---

## 🧠 환경 변수

`agent/.env.example`을 `agent/.env`로 복사하고 원하는 제공자 블록의 주석을 해제하세요. 각 제공자에 3~4개의 변수가 필요합니다:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | 제공자 이름(`openrouter`, `deepseek`, `groq`, `z.ai`, `ollama` 등) |
| `<PROVIDER>_API_KEY` | Yes* | API 키(`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` 등) |
| `<PROVIDER>_BASE_URL` | Yes | API 엔드포인트 URL |
| `LANGCHAIN_MODEL_NAME` | Yes | 모델 이름(예: `deepseek/deepseek-v3.2`) |
| `TUSHARE_TOKEN` | No | A주 데이터용 Tushare Pro 토큰(AKShare 폴백) |
| `TIMEOUT_SECONDS` | No | LLM 호출 타임아웃, 기본 120초 |

<sub>* Ollama는 API 키가 필요 없습니다.</sub>

**무료 데이터(키 불필요):** AKShare의 A주, yfinance의 HK/US 주식, OKX의 크립토, CCXT의 100+ 크립토 거래소. 시스템이 시장별로 최적 소스를 자동 선택합니다.

### 🎯 권장 모델

Vibe-Trading은 툴 호출에 크게 의존하는 에이전트입니다 — skill, 백테스트, 메모리, swarm이 모두 tool call을 통해 실행됩니다. 모델 선택이 에이전트가 **실제로 툴을 사용하는지**, 아니면 학습 데이터에서 답을 꾸며내는지를 결정합니다.

| 등급 | 예시 | 용도 |
|------|------|------|
| **최상** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.4`, `google/gemini-3.1-pro-preview` | 복잡한 swarm(3+ 에이전트), 긴 연구 세션, 논문급 분석 |
| **가성비**(기본값) | `deepseek/deepseek-v3.2`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.5`, `qwen/qwen3-max-thinking` | 일상 사용 — 안정적인 tool-calling, 비용 약 1/10 |
| **에이전트용으로 피할 것** | `*-nano`, `*-flash-lite`, `*-coder-next`, 소형 / 증류 버전 | tool-calling 불안정 — skill 로드나 backtest 실행 대신 "기억으로 답변" |

기본 `agent/.env.example`은 `deepseek/deepseek-v3.2` 사용 — 가성비 등급에서 가장 저렴한 옵션.

---

## 🖥 CLI 참조

```bash
vibe-trading               # 인터랙티브 TUI
vibe-trading run -p "..."  # 단일 실행
vibe-trading serve         # API 서버
```

<details>
<summary><b>TUI 내 슬래시 명령</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | 모든 명령 표시 |
| `/skills` | 72개 금융 스킬 목록 |
| `/swarm` | 29개 스웜 팀 프리셋 목록 |
| `/swarm run <preset> [vars_json]` | 라이브 스트리밍으로 스웜 팀 실행 |
| `/swarm list` | 스웜 실행 이력 |
| `/swarm show <run_id>` | 스웜 실행 상세 |
| `/swarm cancel <run_id>` | 실행 중인 스웜 취소 |
| `/list` | 최근 실행 |
| `/show <run_id>` | 실행 상세 + 지표 |
| `/code <run_id>` | 생성된 전략 코드 |
| `/pine <run_id>` | 인디케이터 내보내기 (TradingView + TDX + MT5) |
| `/trace <run_id>` | 전체 실행 리플레이 |
| `/continue <run_id> <prompt>` | 새 지시로 실행 계속 |
| `/sessions` | 채팅 세션 목록 |
| `/settings` | 런타임 설정 표시 |
| `/clear` | 화면 지우기 |
| `/quit` | 종료 |

</details>

<details>
<summary><b>단일 실행 & 플래그</b></summary>

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
vibe-trading --pine <run_id>           # 인디케이터 내보내기 (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

</details>

---

## 🌐 API 서버

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | 실행 목록 |
| `GET` | `/runs/{run_id}` | 실행 상세 |
| `GET` | `/runs/{run_id}/pine` | 멀티 플랫폼 인디케이터 내보내기 |
| `POST` | `/sessions` | 세션 생성 |
| `POST` | `/sessions/{id}/messages` | 메시지 전송 |
| `GET` | `/sessions/{id}/events` | SSE 이벤트 스트림 |
| `POST` | `/upload` | PDF/파일 업로드 |
| `GET` | `/swarm/presets` | 스웜 프리셋 목록 |
| `POST` | `/swarm/runs` | 스웜 실행 시작 |
| `GET` | `/swarm/runs/{id}/events` | 스웜 SSE 스트림 |

인터랙티브 문서: `http://localhost:8899/docs`

---

## 🔌 MCP 플러그인

Vibe-Trading은 MCP 호환 클라이언트용 22개 MCP 도구를 제공합니다. stdio 서브프로세스로 실행 — 서버 설정 불필요. **22개 중 21개 도구는 API 키 없이 작동**(HK/US/크립토). `run_swarm`만 LLM 키가 필요합니다.

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
<summary><b>Cursor / Windsurf / 기타 MCP 클라이언트</b></summary>

```bash
vibe-trading-mcp                  # stdio (default)
vibe-trading-mcp --transport sse  # 웹 클라이언트용 SSE
```

</details>

**제공 MCP 도구(22):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

<details>
<summary><b>ClawHub에서 설치(한 줄)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> 외부 API를 참조하는 스킬이 있어 VirusTotal 자동 스캔이 트리거되므로 `--force`가 필요합니다. 코드는 완전 오픈소스이며 검토 가능합니다.

이 명령은 스킬과 MCP 설정을 에이전트의 스킬 디렉터리에 다운로드합니다. 클론이 필요 없습니다.

ClawHub에서 보기: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — 자가 진화 스킬</b></summary>

모든 72개 금융 스킬은 [open-space.cloud](https://open-space.cloud)에 게시되어 OpenSpace의 자가 진화 엔진을 통해 스스로 발전합니다.

OpenSpace와 함께 사용하려면 두 MCP 서버를 에이전트 설정에 추가하세요:

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

OpenSpace는 모든 72개 스킬을 자동으로 탐지하여 자동 수정, 자동 개선, 커뮤니티 공유를 활성화합니다. OpenSpace 연결 에이전트에서 `search_skills("finance backtest")`로 Vibe-Trading 스킬을 검색하세요.

</details>

---

## 📁 프로젝트 구조

<details>
<summary><b>클릭하여 펼치기</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli.py                      # CLI 엔트리포인트 — 인터랙티브 TUI + 서브커맨드
│   ├── api_server.py               # FastAPI 서버 — 실행, 세션, 업로드, 스웜, SSE
│   ├── mcp_server.py               # MCP 서버 — OpenClaw / Claude Desktop용 22개 도구
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct 에이전트 코어
│   │   │   ├── loop.py             #   5계층 압축 + 읽기/쓰기 도구 배치 처리
│   │   │   ├── context.py          #   시스템 프롬프트 + 영구 메모리 자동 리콜
│   │   │   ├── skills.py           #   스킬 로더(69 번들 + 사용자 CRUD 생성)
│   │   │   ├── tools.py            #   도구 기본 클래스 + 레지스트리
│   │   │   ├── memory.py           #   실행별 경량 워크스페이스 상태
│   │   │   ├── frontmatter.py      #   공유 YAML frontmatter 파서
│   │   │   └── trace.py            #   실행 트레이스 기록기
│   │   │
│   │   ├── memory/                 # 크로스세션 영구 메모리
│   │   │   └── persistent.py       #   파일 기반 메모리 (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 27개 자동 탐지 에이전트 도구
│   │   │   ├── backtest_tool.py    #   백테스트 실행
│   │   │   ├── remember_tool.py    #   크로스세션 메모리 (저장/리콜/삭제)
│   │   │   ├── skill_writer_tool.py #  스킬 CRUD (저장/패치/삭제/파일)
│   │   │   ├── session_search_tool.py # FTS5 크로스세션 검색
│   │   │   ├── swarm_tool.py       #   스웜 팀 실행
│   │   │   ├── web_search_tool.py  #   DuckDuckGo 웹 검색
│   │   │   └── ...                 #   bash, 파일 I/O, 팩터 분석, 옵션 등
│   │   │
│   │   ├── skills/                 # 7개 카테고리의 72개 금융 스킬(SKILL.md 각각)
│   │   ├── swarm/                  # 스웜 DAG 실행 엔진
│   │   │   └── presets/            #   29개 스웜 프리셋 YAML 정의
│   │   ├── session/                # 멀티턴 채팅 + FTS5 세션 검색
│   │   └── providers/              # LLM 제공자 추상화
│   │
│   └── backtest/                   # 백테스트 엔진
│       ├── engines/                #   7개 엔진 + 크로스마켓 복합 엔진 + options_portfolio
│       ├── loaders/                #   6개 소스: tushare, okx, yfinance, akshare, ccxt, futu
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   레지스트리 + 자동 폴백 체인
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, RunDetail, Compare
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand 상태 관리
│
├── Dockerfile                      # 멀티 스테이지 빌드
├── docker-compose.yml              # 원커맨드 배포
├── pyproject.toml                  # 패키지 설정 + CLI 엔트리포인트
└── LICENSE                         # MIT
```

</details>

---

## 🏛 생태계

Vibe-Trading은 **[HKUDS](https://github.com/HKUDS)** 에이전트 생태계의 일부입니다:

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>에이전트 스웜 인텔리전스</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>초경량 개인 AI 어시스턴트</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>모든 소프트웨어를 에이전트 네이티브로</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>자가 진화 AI 에이전트 스킬</sub>
    </td>
  </tr>
</table>

---

## 🗺 로드맵

> 단계적으로 배포합니다. 작업이 시작되면 항목이 [Issues](https://github.com/HKUDS/Vibe-Trading/issues)로 이동합니다.

| Phase | Feature | Status |
|-------|---------|--------|
| **Agent Harness** | 크로스세션 영구 메모리 (저장 / 리콜 / 삭제) | **Done** |
| | 자가 진화 스킬 — 에이전트가 스스로 워크플로우를 생성·수정·삭제 | **Done** |
| | FTS5 크로스세션 검색 (모든 과거 대화 횡단) | **Done** |
| | 5계층 컨텍스트 압축 (micro → collapse → auto → manual → iterative) | **Done** |
| | 읽기/쓰기 도구 배치 처리 — 읽기 전용 도구 병렬 실행 | **Done** |
| **Next Up** | 자율 리서치 루프 — 에이전트가 밤새 가설을 반복 | In Progress |
| | IM 통합 (Slack / Telegram / WeChat) | Planned |
| **Analysis & Viz** | 옵션 변동성 서피스 및 그릭스 3D 시각화 | Planned |
| | 롤링 윈도우 + 클러스터링 기반 크로스자산 상관 히트맵 | Planned |
| | CLI 백테스트 출력에 벤치마크 비교 | Planned |
| **Skills & Presets** | 배당 분석 스킬 | Planned |
| | ESG / 지속가능 투자 스웜 프리셋 | Planned |
| **Portfolio & Optimization** | 레버리지, 섹터 캡, 턴오버 제약을 포함한 고급 포트폴리오 옵티마이저 | Planned |
| **Future** | 전략 마켓플레이스 (공유 & 발견) | Exploring |
| | WebSocket 기반 실시간 데이터 스트리밍 | Exploring |

---

## 기여하기

기여를 환영합니다! 가이드는 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.

**Good first issues**는 [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 라벨로 표시되어 있습니다 — 선택해 바로 시작해 보세요.

더 큰 기여를 원하나요? 위 [로드맵](#-로드맵)을 확인하고 시작 전에 이슈를 열어 논의해주세요.

---

## 기여자

Vibe-Trading에 기여해 주신 모든 분들께 감사드립니다!

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## 면책조항

Vibe-Trading은 리서치, 시뮬레이션, 백테스트 용도입니다. 투자 조언이 아니며 실거래를 실행하지 않습니다. 과거 성과는 미래 수익을 보장하지 않습니다.

## 라이선스

MIT License — [LICENSE](LICENSE) 참조

---

## 스타 히스토리

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  방문해 주셔서 감사합니다 <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
