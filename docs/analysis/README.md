# Vibe-Trading 분석 자료 — AI 핸드오프

> **다른 AI에게 넘길 때: 이 폴더만 주면 된다.**  
> 경로: `docs/analysis/`

---

## AI가 볼 본문 (읽는 순서)

| 우선순위 | 파일 | 용도 |
|----------|------|------|
| **1 (필수)** | [`README.md`](./README.md) (지금 이 파일) | 핸드오프 계약·범위·잔여 |
| **2 (본문)** | [`REPORT.md`](./REPORT.md) | Part 1–28 아키텍처·계약·흐름 (서술 기준) |
| **3 (표)** | [`catalog/INDEX.md`](./catalog/INDEX.md) | 스킬/알파/스웜/채널/테스트 전수 표 입구 |
| **4 (필요 시)** | `catalog/*.md` · `catalog/*.json` | 특정 id 조회 |

채팅 로그·IDE 캔버스는 **보조**다. 코드 해석의 단일 출처는 **이 폴더**다.

---

## 이 폴더에 있는 것

```
docs/analysis/
├── README.md          ← AI 진입점 (핸드오프)
├── REPORT.md          ← 통합 분석 보고서
└── catalog/
    ├── INDEX.md
    ├── SKILLS.md (+ skills_inventory.json)      # 88
    ├── ALPHAS.md (+ alphas_inventory.json)      # 462
    ├── SWARM_PRESETS.md (+ swarm_inventory.json)# 30
    ├── CHANNELS.md                              # 16
    ├── TESTS.md                                 # 315
    └── _build_*.py                              # 재생성 스크립트
```

---

## 프로젝트에서 이미 끝난 것 (요약)

- 코어: AgentLoop · Session · API · backtest (`_align` / `_execute_bars` / AST / Runner)
- 라이브: mandate · OrderGuard · connectors 12
- 확장: swarm · channels · shadow/SDM/hypotheses · frontend · wiki/CI
- 카탈로그 전수 메타: skills 88 · alphas 462 · presets 30 · channels 16 · tests 315

상세는 `REPORT.md` Part 1–28.

---

## 의도적으로 안 깐 것 (온디맨드)

- 개별 스킬 references 대량 md, 개별 알파 `compute()` 전 라인
- 서드파티 IM/SDK 라이브러리 내부
- 테스트 assertion 한 줄씩

→ id를 지정하면 그때 해당 파일만 추가 딥.

---

## 다른 AI에게 붙일 프롬프트 예시

```
워크스페이스: Vibe-Trading
먼저 읽고 따르기: docs/analysis/README.md → docs/analysis/REPORT.md
표·목록: docs/analysis/catalog/
이미 분석된 계약을 재탐색하지 말고, 위 문서를 기준으로 답하거나 지정한 잔여만 딥할 것.
```

---

## 사람용 vs AI용

| | 사람 | AI |
|--|------|-----|
| 본문 | `REPORT.md` (같은 파일) | **먼저 `README.md`**, 그다음 `REPORT.md` |
| 목록 | `catalog/*.md` | 동일 + `*.json`으로 기계 조회 |
| 캔버스 | IDE에서 시각화 | 무시해도 됨 |

한 폴더로 묶으면 **경로 하나·컨텍스트 오염 감소·재탐색 비용 감소**에 도움이 된다.
