# VIBE LAB — MEMORIA DEL PROYECTO (lecciones durables · NO repetir)

> **Qué es esto y en qué se diferencia de `handoff.md`:**
> - `handoff.md` = **estado VOLÁTIL** (qué se hizo, qué corre hoy, tareas pendientes). Cambia cada sesión.
> - `MEMORY.md` (este archivo) = **lecciones PERMANENTES**: invariantes que nunca romper, fallos ya
>   resueltos con su causa raíz, y trampas. **Solo crece.**
>
> **LA REGLA (obligatoria, espejo del protocolo de OLIMPO):**
> 1. **ANTES** de tocar config, conectores, datos o cualquier flag: leer este archivo y verificar que el
>    cambio NO viola una invariante ni reabre un fallo del registro.
> 2. **AL CERRAR sesión**: actualizar AMBOS — `handoff.md` (estado) y `MEMORY.md` (si hubo lección nueva).
> 3. Un fix no es completo hasta que su regla de prevención está escrita aquí.

---

## 🔒 INVARIANTES — romper una de estas es una regresión grave

| # | Invariante | Por qué (evidencia) |
|---|---|---|
| I-V1 | **AISLAMIENTO TOTAL de OLIMPO.** Este proyecto NUNCA se instala, importa ni corre en el mismo entorno/máquina que OLIMPO; NUNCA en el box Hetzner de OLIMPO (167.233.46.18, dinero real Kraken). CERO secretos de OLIMPO aquí (Kraken/Bybit/portal/API keys). | Regla de oro del runbook `docs/VIBE_TRADING_ISOLATED.md` de OLIMPO: superficie enorme (10+ SDKs de broker, LangChain, red, Docker) junto a dinero real = inaceptable. |
| I-V2 | **SIN BROKERS EN VIVO.** Ningún connector de ejecución se configura jamás (Robinhood/IB/Binance/OKX/Longbridge/Futu…). Solo módulos de datos + backtest + alpha-bench + paper/shadow account. Si algún día se usan keys de datos: solo-lectura y propias de este servicio, jamás keys de trading. | Mismo runbook, punto 3. El valor del proyecto es research; la ejecución vive (re-validada) en OLIMPO. |
| I-V3 | **FLUJO UNIDIRECCIONAL Vibe→OLIMPO.** Las salidas de aquí (alphas, factores, estrategias) son HIPÓTESIS: se copian como fórmula/spec y se re-validan con walk-forward en el backtester de OLIMPO antes de tocar cualquier money-path. NUNCA se importa código de HKUDS a OLIMPO; nunca fluye nada de OLIMPO hacia aquí. | Runbook punto 6 + patrón ya ejecutado con éxito (GTJA-191/a101 re-implementados en OLIMPO desde el paper, no desde este código). |
| I-V4 | **ARRANQUE OBLIGATORIO de cada sesión:** (1) activar skills `crypto-agent-protocol` + `vibe-lab-agent`; (2) leer `handoff.md` (top + PRÓXIMA SESIÓN) y este archivo. No saltárselo aunque la petición parezca trivial. | Espejo de la invariante I27 de OLIMPO (instrucción permanente de Xander, 2026-06-20). |
| I-V5 | **El sandbox de sesión tiene EGRESS RESTRINGIDO:** yfinance/Yahoo, Binance y Kraken públicos devuelven 403 vía proxy (verificado 2026-07-12). Aquí: desarrollo + suite de tests offline (CI-parity, pasa sin red). Datos vivos: SOLO en la VM aislada (`DEPLOY_ISOLATED.md`) o vía runner de GitHub Actions (patrón I24 de OLIMPO). NO construir/depurar clientes de datos "a ciegas" desde el sandbox. | Test de egress 2026-07-12: 3/3 fuentes → 403 proxy. En OLIMPO el mismo patrón costó sesiones perdidas antes de documentarse. |
| I-V6 | **HIGIENE DE FORK.** Upstream = HKUDS/Vibe-Trading. `main` del fork se mantiene limpio y sincronizable con upstream. El andamiaje fork-local (CLAUDE.md, `.claude/skills/`, handoff.md, MEMORY.md, DEPLOY_ISOLATED.md, excepciones del .gitignore) vive en la rama de trabajo y JAMÁS se incluye en un PR hacia upstream. | Upstream gitignora `.claude/*`, `CLAUDE.md` y `docs/` deliberadamente; nuestro fork los trackea vía excepciones. Mezclarlos en un PR upstream = ruido y fuga de contexto privado. |
| I-V7 | **PAPER-FIRST PERMANENTE.** Este proyecto nunca ejecuta dinero real. No existe "go-live" en su roadmap; cualquier excepción futura requiere decisión explícita del owner en ese momento y rediseño de seguridad. | Decisión de sesión 2026-07-12 (Xander eligió modo paper/demo sin keys reales) + I-V2. |
| I-V8 | **OPS vía GitHub Actions del fork, secretos SOLO en GitHub Secrets + `agent/.env` de la VM (0600).** El sandbox de sesión no tiene SSH de salida → deploy/validaciones corren en el runner (`vibe-deploy.yml`, `vibe-validate-data.yml`), disparables por push a la rama de trabajo, por UI o por API MCP. `agent/.env` de la VM lo escribe el workflow desde los secrets — nunca se commitea ni se edita a mano (fuente de verdad = Secrets). El deploy workflow aborta si `VIBE_SSH_HOST` = box de OLIMPO. | Espejo de I22/I24 de OLIMPO (push-to-deploy + runner con egress abierto); aplicado aquí 2026-07-12. |

---

## ✅ REGISTRO DE FALLOS RESUELTOS (no repetir)

| Fecha | Fallo | Causa raíz | Regla de prevención |
|---|---|---|---|
| — | (vacío — primera sesión) | — | — |

---

## 🪤 TRAMPAS CONOCIDAS

- **`alpha bench` / `data` necesitan red** → en el sandbox fallarán con 403 aunque el código esté bien
  (I-V5). Verificar primero DÓNDE corres antes de diagnosticar un "bug" de red.
- **El paquete PyPI se llama `vibe-trading-ai`** pero los comandos son `vibe-trading` y
  `vibe-trading-mcp`. El repo se instala editable con `pip install -e .` (pyproject en la raíz,
  código en `agent/`).
- **Tests e2e (`agent/tests/e2e_*.py`) están gitignorados** y requieren keys vivas — no existen en un
  clone fresco; la suite normal (`pytest agent/tests`) es la que corre en CI sin red.
