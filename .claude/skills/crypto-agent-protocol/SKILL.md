---
name: crypto-agent-protocol
description: >
  Master operating protocol for all of Xander's crypto projects. Combines session continuity (handoff.md system), a pre-build thinking ritual, an impeccable quality check, and a structured clarification habit. ALWAYS activate this skill from the very first message in any crypto project conversation — whether the user says "let's continue", "pick up where we left off", "build X for my crypto project", "check the status", "I need a new feature", "debug this", "what was the plan", or anything implying active development on a crypto-related system. Never start building, analyzing, or modifying anything without first running through this protocol. This skill is the backbone of Xander's crypto projects — if in doubt, use it.
---

# Crypto Agent Protocol
> Session continuity + build quality + zero assumptions — for every crypto project session.

---

## 🧠 Philosophy

Three rules extracted from hard experience:

1. **Preguntar todo** — Never assume. Every ambiguity costs 10x more to fix than to clarify upfront.
2. **Para pensar primero** — Think before touching code. The plan is the product.
3. **Impeccable before done** — Nothing ships without a quality pass. A working feature with broken architecture is debt, not progress.

---

## 🌐 Language convention

- **English** for everything that touches the code: identifiers, code comments, commit messages,
  branch names, PR titles and bodies, and in-repo technical docs. Better for tooling, diffs and review.
- **Spanish is fine** for the live conversation with the user and for non-code notes that don't affect
  the codebase.

---

## ⚡ Protocol Activation

Run this protocol **at the start of every session**, regardless of context. Three steps, always in order.

> **Coordinate with project skills.** If a project-specific skill is also active (e.g.
> `olimpo-quant-agent`), it provides the ROLE and domain rules; this protocol provides the session
> PROCESS (continuity, planning, quality). Run both — they are complementary, not competing.

---

## STEP 1 — Context Load (30 seconds)

Before anything else, check if a `handoff.md` exists in the project root.

```bash
# Check for handoff file
cat handoff.md 2>/dev/null || echo "NO_HANDOFF_FOUND"
```

### If `handoff.md` EXISTS:
Read it completely and confirm to the user:

> **"📂 Handoff cargado. Retomando desde: [GOAL]. Estado actual: [CURRENT STATE]. Archivos activos: [FILES IN FLIGHT]."**

Then ask **one single question** before proceeding:
> "¿Algún cambio de dirección desde la última sesión, o seguimos exactamente desde aquí?"

### If `handoff.md` DOES NOT EXIST:
Do NOT ask 10 questions. Ask only the critical ones, maximum 3:

```
1. ¿Cuál es el objetivo concreto de esta sesión?
2. ¿Hay código existente que deba respetar, o empezamos desde cero?
3. ¿Hay restricciones críticas? (exchange específico, chain, API keys, presupuesto de gas, etc.)
```

Wait for answers before proceeding to Step 2.

---

## STEP 2 — Pre-Build Thinking (Para Pensar)

**Never touch code without this step.** Write a visible plan before executing.

Format the plan as:

```
## 🧩 Plan de la sesión
- Objetivo: [qué vamos a lograr hoy]
- Enfoque: [qué approach técnico usaremos y por qué]
- Archivos que vamos a tocar: [lista explícita]
- Riesgos identificados: [qué puede salir mal]
- Criterio de éxito: [cómo sabemos que terminamos]
```

Ask the user to confirm the plan with a simple **"sí"** before starting.
If the user says "dale" / "go" / "sí" / "correcto" — proceed to execution.
If they correct something — update the plan and ask again.

> **This step is non-negotiable. A plan that takes 2 minutes to write saves 2 hours of debugging.**
>
> **Scale the plan to the task.** A one-line fix needs one line of plan; a new module needs the full
> block above. Don't force ceremony on trivial changes — but never skip thinking entirely.

---

## STEP 3 — Execution Rules

While building, follow these operating principles:

### 🔴 Ask Before Assuming (Preguntar Todo)
If you encounter ANY of these mid-task, stop and ask:
- Ambiguous token name, pair, or exchange
- Unclear risk parameter (stop loss %, position size, leverage)
- Unknown wallet address or chain
- Conflicting data sources
- Missing API credentials or config

**Never invent values for financial/crypto parameters. Ever.**

### 🏗️ Architecture First
For any new module:
1. Define the data structure first (types, schema)
2. Define the interface (what goes in, what comes out)
3. Then write the implementation

### 🔁 Loop Detection
If you catch yourself writing the same fix 3 times → STOP.
Write a `handoff.md` with the current state, flag the loop explicitly, and propose a fresh architectural approach in the next session.

---

## STEP 4 — /Impeccable Check (Before Closing Any Session)

Run this checklist before marking any feature or task as done:

```
## ✅ /Impeccable Checklist
[ ] El código hace exactamente lo que el plan decía que haría
[ ] No hay console.logs / prints de debugging sin limpiar
[ ] No hay credenciales hardcodeadas (API keys, seeds, private keys)
[ ] Los errores están manejados (no crashes silenciosos)
[ ] Los valores financieros usan la precisión correcta (decimales crypto)
[ ] Está probado con datos reales o un mock que los representa fielmente
[ ] El nombre de variables/funciones es claro sin necesidad de comentarios
[ ] No hay dependencias instaladas que no se usen
```

Si algún item está sin marcar → no está terminado. Resolverlo o documentarlo en `handoff.md` como deuda explícita.

---

## STEP 5 — Session Close (Handoff Write)

Al finalizar cada sesión, **siempre** escribir o actualizar `handoff.md`:

```markdown
# handoff.md — [PROJECT NAME]
Last updated: [DATE]

## Goal
[What we're ultimately trying to build — does not change often]

## Current State
[Exactly where we stand right now — honest, no sugar-coating]
- What works: ...
- What's broken: ...
- What's incomplete: ...

## Files in Flight
[Files actively being modified or that need attention]
- `src/file.ts` — [what's happening here]
- `config/settings.json` — [what changed]

## Next Session
[First 3 things to do when we open this project again]
1. ...
2. ...
3. ...

## Known Risks / Debt
[Anything that could explode later]
- ...

## Crypto-Specific Context
[Exchange, chain, pairs, API keys location, env vars]
- Exchange: ...
- Chain: ...
- Active pairs: ...
- Config: .env / secrets location: ...
```

---

## 🚨 Crypto-Specific Hard Rules

These are non-negotiable regardless of task:

| Rule | Why |
|---|---|
| **Never hardcode private keys or seeds** | One commit = funds lost forever |
| **Always validate decimals before any trade/transfer** | Off-by-one in crypto = total loss |
| **Dry-run before live execution** | Test with paper trading or minimal amount first |
| **Log every transaction attempt** | Debugging requires an audit trail |
| **Confirm the chain before any address operation** | Same address, different chain = lost funds |
| **No silent error swallowing** | `try/catch` must surface errors, never hide them |

---

## 🔄 Quick Reference — When to Use What

| Situation | Action |
|---|---|
| Starting a session | Step 1 → check handoff.md |
| Before writing code | Step 2 → write the plan |
| Confused mid-task | Stop → ask → don't guess |
| Stuck in a loop (3rd same fix) | Write handoff.md → end session |
| Feature "feels done" | Run /Impeccable checklist |
| Ending any session | Step 5 → update handoff.md |

---

## 📁 Expected Project Structure

Every crypto project should maintain this minimal structure:

```
project-root/
├── handoff.md          ← session continuity file (THIS SKILL)
├── .env                ← credentials (NEVER commit)
├── .env.example        ← template with keys but no values
├── README.md           ← project overview + setup
└── src/
    └── ...
```
