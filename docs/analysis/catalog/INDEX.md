# Catalog Index — 한 장씩 읽기 결과

이 폴더는 이전에 “카탈로그 잔여”로 남겨 둔 항목을 **전수 추출·기록**한 결과입니다.

| 문서 | 건수 | 내용 |
|------|------|------|
| [SKILLS.md](./SKILLS.md) | **88** | 모든 `SKILL.md` frontmatter (category, description, files, example_engine) |
| [ALPHAS.md](./ALPHAS.md) | **462** | zoo별 `__alpha_meta__` (id, theme, columns, warmup, formula_latex) |
| [SWARM_PRESETS.md](./SWARM_PRESETS.md) | **30** | agents/tasks/depends_on/variables |
| [CHANNELS.md](./CHANNELS.md) | **16** | IM 어댑터 class/lines/override/프로토콜 노트 |
| [TESTS.md](./TESTS.md) | **315** | `test_*.py` 도메인 prefix 맵 |

## JSON (기계용)

- `skills_inventory.json`
- `alphas_inventory.json`
- `swarm_inventory.json`

## 재생성

```bash
python docs/analysis/catalog/_build_inventories.py
python docs/analysis/catalog/_build_channels_tests.py
```

## 읽는 방법

1. 사람이 훑을 때 → 각 `*.md` 표  
2. 필터/검색할 때 → 대응 `*.json`  
3. 전체 아키텍처 맥락 → `docs/analysis/REPORT.md` Part 28  
4. AI 핸드오프 진입 → `docs/analysis/README.md` 

## 한계 (정직하게)

- 스킬: frontmatter + 파일 수. **본문 전체 문단**은 md 길이가 커서 요약만(설명 필드에 핵심).
- 알파: AST로 `__alpha_meta__` literal. `compute()` 구현 라인 전부는 표에 formula_latex로 대체.
- 채널: 구조·프로토콜·라인 수. SDK 라이브러리 내부까지 추적하지는 않음.
- 테스트: 파일명 기반 도메인 맵. 케이스별 assertion 전수는 별도.
