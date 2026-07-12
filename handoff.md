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
> "VIBE LAB deploy" y verifica `/health`. Estado del probe de datos del runner: ver sección Estado.

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

## PRÓXIMA SESIÓN (primeras 3 cosas)

1. **¿Hizo Xander sus 5 minutos?** (VM creada + bootstrap + 4 secrets — Camino A de
   `DEPLOY_ISOLATED.md`). Si sí: disparar workflow "VIBE LAB deploy" (rama de trabajo), leer logs
   vía MCP de GitHub, verificar `/health` y pasar el checklist de aislamiento (sección 6 del runbook).
2. Si aún no hay VM: research puede empezar YA en el runner (patrón I-V8/I24) — `vibe-validate-data`
   dice qué feeds funcionan; se puede montar un workflow de `alpha bench` en runner si hace falta.
3. Primer ciclo de research del lab: elegir 1 hipótesis (p. ej. un alpha del Zoo sobre BTC-USDT o
   sp500), correr `alpha bench`/backtest con walk-forward (en VM o runner), y redactar la primera
   spec re-validable en OLIMPO (I-V3).

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
