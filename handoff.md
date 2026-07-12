# handoff.md — VIBE LAB (Vibe-Trading fork aislado)
**Última actualización:** 2026-07-12 (2ª pasada — puesta en marcha) | **Upstream:** HKUDS/Vibe-Trading v0.1.11 (sync @ 5f88f39) | **Rama de trabajo:** `claude/vibe-trading-setup-w0m9fg`

> **Cierre 2026-07-12b (puesta en marcha — automatización de deploy):** Construido el camino completo
> para la VM aislada SIN poder crearla desde aquí (eso es del owner): `vibe-deploy.yml` (workflow SSH:
> escribe `agent/.env` desde Secrets → `docker compose up -d --build` → health-check; skip limpio sin
> secrets; ABORTA si el host es el box de OLIMPO), `vibe-validate-data.yml` + `scripts/probe_data_sources.py`
> (sonda de feeds desde el runner, reutilizable en la VM), `scripts/vm_bootstrap.sh` (prep one-shot de la VM,
> con guard anti-OLIMPO). `DEPLOY_ISOLATED.md` reescrito con Camino A automatizado (los 5 min del owner:
> crear VM CX22 Ubuntu 24.04 → bootstrap one-liner → 4 secrets → disparar workflow). Nueva invariante I-V8
> (ops vía Actions, secretos solo en GitHub Secrets). **BLOQUEADO EN:** owner crea la VM + añade secrets
> (`VIBE_SSH_HOST/VIBE_SSH_USER/VIBE_SSH_KEY/OPENROUTER_API_KEY`); después cualquier sesión dispara
> "VIBE LAB deploy" y verifica `/health`. **VERIFICADO EN VIVO:** Actions del fork habilitadas;
> deploy run#1 (push) = success con skip limpio sin secrets; probe run#1 = success **4/6 fuentes
> desde el runner** (yfinance BTC/AAPL OK, kraken OK, okx OK; binance 451 geo-US, stooq 404 —
> ver trampa en MEMORY.md). El research con datos reales YA es posible vía runner sin esperar la VM.

## 🚀 CÓMO ARRANCAR LA PRÓXIMA SESIÓN (LEER PRIMERO)

1. Activar skills `crypto-agent-protocol` + `vibe-lab-agent` (I-V4) y leer `MEMORY.md` (invariantes I-V1…I-V7).
2. Recordar dónde estás: el sandbox de sesión tiene egress restringido (I-V5) — datos vivos NO;
   desarrollo + tests offline SÍ.
3. Continuar por "PRÓXIMA SESIÓN" (abajo).

## Goal

Laboratorio de research cuantitativo AISLADO sobre la plataforma HKUDS/Vibe-Trading: minar
alphas/factores/estrategias con evidencia honesta (IS/OOS + walk-forward) y producir HIPÓTESIS
re-validables en OLIMPO. Nunca dinero real, nunca el entorno de OLIMPO (regla de oro I-V1/I-V7).
Destino de ejecución futuro: VM Hetzner NUEVA y dedicada (runbook: `DEPLOY_ISOLATED.md`).

## Estado actual (2026-07-12 — sesión fundacional)

**Qué funciona (verificado hoy en el sandbox):**
- Python 3.11.15 + venv en `.venv/` con `pip install -e .` completo (vibe-trading-ai 0.1.11 editable).
- CLI `vibe-trading` operativa (`--help`, `alpha list` → Alpha Zoo 460 alphas carga offline).
- API server: `vibe-trading serve --port 8899` → `GET /health` = healthy, `GET /api` = v0.1.11.
- Frontend React 19: `npm install` + `npm run build` OK (Vite, ~13 s, chunks grandes = warning benigno).
- Suite offline verde en los subsets probados: engines (crypto/base) 48/48, metrics + robustness +
  runner-security 67 passed / 1 skipped. La suite completa (~4700) corre en CI upstream.
- Node v22.22.2, npm 10.9.7.

**Qué NO funciona aquí (esperado, no es bug — I-V5):**
- Egress a datos: yfinance/Binance/Kraken → 403 del proxy del sandbox. `alpha bench`, `data` y
  cualquier fetch vivo necesitan la VM aislada o un runner de GitHub.

**Qué está incompleto:**
- VM Hetzner aislada: NO provisionada (requiere acción del owner — crear VM y pagar). Runbook listo.
- LLM provider: sin key configurada (`agent/.env` no existe; plantilla en `agent/.env.example`).
  El agente "piensa" solo cuando haya key propia (OpenRouter recomendado) — en la VM, no aquí.
- Primer ciclo de research real (hipótesis → evidencia → spec para OLIMPO): pendiente de lo anterior.

## Files in flight (andamiaje creado hoy, rama `claude/vibe-trading-setup-w0m9fg`)

- `CLAUDE.md` — instrucciones de sesión del fork (nuevo).
- `MEMORY.md` — invariantes I-V1…I-V7 + trampas (nuevo).
- `handoff.md` — este archivo (nuevo).
- `DEPLOY_ISOLATED.md` — runbook VM Hetzner aislada (nuevo).
- `.claude/skills/crypto-agent-protocol/SKILL.md` — copiado de OLIMPO sin cambios (protocolo de sesión).
- `.claude/skills/vibe-lab-agent/SKILL.md` — skill de proyecto: rol, límites, mapa de arquitectura (nuevo).
- `.gitignore` — excepciones fork-local al final (trackear `.claude/skills/**` y `CLAUDE.md`).
- Código del agente/plataforma: **CERO cambios** (solo andamiaje).

## CICLO 1 DE RESEARCH — RESULTADO (2026-07-12, run 29205155515)

**Bench alpha101 × sp500 × 2022-2025 (diario, IC cross-sectional):** 82 alphas testeadas, 19
skipped, 7:13 min de loop (panel de ~500 tickers vía yfinance en ~3 min). **VEREDICTO HONESTO:
ningún candidato avanza.** El mejor por IR es `alpha101_032` (momentum: IC 0.020, IR 0.166,
hit 57.4%, n=768) y TODO el top-20 queda clasificado **"dead"** por el propio clasificador de la
plataforma — y eso CON survivorship bias inflando al alza (constituyentes actuales de Wikipedia).
Lectura: las fórmulas precio/volumen públicas (Kakushadze 101) están minadas en large-caps US
2022-2025 — **coincide con la conclusión R7 de OLIMPO** (GTJA-191 también murió allí; el edge
ortogonal está en datos non-price / modalidades menos concurridas). Artefacto: informe HTML +
stdout en `alpha-bench-results` (run 29205155515, retención 30 días).

**Valor real del ciclo 1:** el LOOP funciona de punta a punta en runner (~8.5 min y gratis):
fetch universo → IC bench → informe → artifact. Reproducible con
`workflow_dispatch` de "VIBE LAB research bench" (inputs: zoo/universe/period/top).

## CICLO 2 DE RESEARCH — RESULTADO (2026-07-12, runs 29206057062 + 29206467304)

**Bench fundamental (PIT SEC) × sp500 × 2020-2025.** Para poder correrlo hubo que arreglar DOS
bugs reales de la plataforma (ambos upstream-able, con tests offline):
1. `run_bench` no inyectaba columnas `fund:*` en el panel (solo el backtest runner lo hacía) →
   los 4 factores fundamentales se skipeaban siempre. Fix: `_inject_fund_panels` en
   `bench_runner.py` (commit 2072be9).
2. `_resolve_ciks` pasaba símbolos estilo proyecto (`AAPL.US`) a `cik_for`, que espera ticker
   pelado → CIK=None para TODO el sp500 (visto en vivo, run 29206057062: 0 tested/4 skipped).
   Fix: fallback quitando el sufijo `.US` (commit c7f11f6). **Este bug estaba latente también en
   el camino del backtest de la plataforma para equity global.**

**Resultado (run 29206467304, 4 tested / 0 skipped, n≈1507 días):** los 4 "dead" a horizonte
DIARIO — fund_roe IC 0.0052/IR 0.050, gross_profitability 0.0035/0.032, earnings_yield
0.0035/0.027, asset_growth −0.0018/−0.035. **Matiz metodológico (no cerrar la modalidad):** el
bench solo mide IC contra el retorno de 1 día vista; quality/value operan a meses — medir un
factor quarterly contra el retorno de mañana es un mismatch de horizonte. Veredicto honesto:
"sin edge a rebalanceo diario", NO "fundamentales muertos". Cobertura: misses puntuales de
conceptos XBRL (XOM shares/assets/equity, YUM/ZTS gross_profit) — gaps de alias normales.

## PRÓXIMA SESIÓN (primeras 3 cosas)

1. **VM Hetzner: APLAZADA por decisión del owner (2026-07-12: "montaremos vm luego").** Cuando toque:
   Camino A de `DEPLOY_ISOLATED.md` (VM + bootstrap + 4 secrets) y disparar "VIBE LAB deploy".
2. **Ciclo 3 (recomendado): IC multi-horizonte en el bench** — añadir horizonte de forward return
   configurable (1d/5d/21d/63d) a `_compute_forward_returns` y re-medir el zoo fundamental a
   21d/63d, que es donde esa clase de factores puede vivir. Cambio pequeño y también upstream-able.
   Alternativas: basket cripto multi-símbolo vía OKX; qlib158 como control negativo.
3. Los survivors (si los hay) pasan a walk-forward y de ahí a spec re-validable en OLIMPO (I-V3).
   Considerar también ofrecer upstream los 2 fixes de este ciclo (PR limpio desde una rama aparte
   basada en main, sin scaffolding — I-V6).

## Riesgos / deuda conocida

- El andamiaje vive SOLO en la rama de trabajo; `main` del fork se queda limpio para sync upstream
  (I-V6). Si se resetea la rama sin mergear, se pierde el andamiaje (lección I11 de OLIMPO).
- Upstream se mueve rápido (batches diarios de PRs) — hacer `git fetch upstream` + rebase/merge de
  `main` periódicamente para no divergir.
- `pytest` no está en las deps del proyecto (CI lo instala aparte) — en este venv se instaló a mano;
  documentado aquí para no sorprenderse en un entorno fresco.

## Contexto crypto-específico

- **Exchange/broker:** NINGUNO conectado (I-V2). Paper/shadow únicamente.
- **Chain:** N/A (no hay wallets ni chains en este proyecto).
- **Pares de referencia para research:** BTC-USDT (crypto), sp500/csi300 (equity) — universos que
  `alpha bench` soporta de serie.
- **Config/secrets:** `agent/.env` (gitignored), plantilla `agent/.env.example`. Estado de usuario en
  `~/.vibe-trading/` (volumen `vibe-home` en Docker).
- **Relación con OLIMPO:** SOLO como destinatario de hipótesis re-validables (I-V3). Nada más.
