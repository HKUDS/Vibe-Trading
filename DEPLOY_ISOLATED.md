# DEPLOY_ISOLATED.md — Vibe-Trading en una VM Hetzner AISLADA

> **Regla de oro (I-V1):** VM NUEVA y separada. **NUNCA** el box de OLIMPO (167.233.46.18).
> Cero secretos de OLIMPO. Sin conectores de broker (I-V2). Research/paper only (I-V7).
> Este documento es el runbook; ejecutarlo requiere acción del owner (crear la VM y pagar).

---

## ⚡ CAMINO A — Automatizado (recomendado): tus 5 minutos + workflows

El deploy real lo hace GitHub Actions (`.github/workflows/vibe-deploy.yml`) porque el sandbox
de sesión no tiene SSH de salida (I-V8). Tu parte:

1. **Crear la VM** — Hetzner Cloud → CX22 (o superior), **Ubuntu 24.04**, tu clave SSH,
   proyecto/red distintos a OLIMPO. Anota la IP.
2. **Bootstrap one-shot** (como root en la VM):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/Alexanderr003/Vibe-Trading/claude/vibe-trading-setup-w0m9fg/scripts/vm_bootstrap.sh | bash
   ```
   (si el raw no resuelve, copia/pega `scripts/vm_bootstrap.sh` a mano). Instala docker+ufw,
   crea el usuario `vibe`, cierra el firewall y clona el fork. Se niega a correr en el box de OLIMPO.
3. **Secrets del fork** — github.com/Alexanderr003/Vibe-Trading → Settings → Secrets and
   variables → Actions → New repository secret:

   | Secret | Valor |
   |---|---|
   | `VIBE_SSH_HOST` | IP de la VM |
   | `VIBE_SSH_USER` | `vibe` (opcional, es el default) |
   | `VIBE_SSH_KEY` | clave PRIVADA que corresponde a la pública de la VM |
   | `OPENROUTER_API_KEY` | key LLM creada PARA este proyecto (jamás una de OLIMPO) |

4. **Disparar el deploy** — Actions → "VIBE LAB deploy" → Run workflow (rama
   `claude/vibe-trading-setup-w0m9fg`), o simplemente avisar en sesión: cualquier push a la rama
   también lo dispara (sin secrets hace skip limpio). El workflow escribe `agent/.env` en la VM
   desde los secrets, hace `docker compose up -d --build` y verifica `/health`.

Guardas de seguridad integradas: el workflow ABORTA si `VIBE_SSH_HOST` es el box de OLIMPO, y
el bootstrap aborta si detecta la IP de OLIMPO en la máquina (I-V1 aplicada en código).

---

## 🔧 CAMINO B — Manual (fallback, mismo resultado)

## 1. Provisionar la VM (owner, ~5 min)

- Hetzner Cloud → nueva VM **CX22** (2 vCPU / 4 GB / 40 GB) o superior, Ubuntu 24.04.
  Proyecto/red distintos a los de OLIMPO si es posible — no compartir VPC ni firewall group.
- Añadir SOLO tu clave SSH. Anotar la IP (en adelante `VM_IP`).

## 2. Base del sistema

```bash
ssh root@VM_IP
adduser vibe && usermod -aG sudo vibe          # no operar como root
apt update && apt install -y docker.io docker-compose-v2 ufw git
usermod -aG docker vibe
```

## 3. Firewall — entrada cerrada, servicios solo loopback

```bash
ufw default deny incoming
ufw allow OpenSSH
ufw enable
```

- `docker-compose.yml` ya publica los puertos SOLO en `127.0.0.1` (8899 backend, 5899 frontend):
  nada queda expuesto a internet. El acceso remoto es SIEMPRE por túnel SSH:
  `ssh -L 8899:127.0.0.1:8899 -L 5899:127.0.0.1:5899 vibe@VM_IP`.
- El MCP server (`vibe-trading-mcp`, stdio) se consume vía SSH desde Claude — nunca escuchando
  en un puerto público.

## 4. Clonar y configurar (usuario `vibe`)

```bash
git clone https://github.com/Alexanderr003/Vibe-Trading.git && cd Vibe-Trading
git checkout claude/vibe-trading-setup-w0m9fg   # rama con el andamiaje del fork
cp agent/.env.example agent/.env
nano agent/.env
```

En `agent/.env` (keys PROPIAS de este servicio, jamás las de OLIMPO — I-V1):
- **Un** bloque de LLM provider (recomendado: OpenRouter, key nueva creada para este proyecto).
- NINGUNA key de broker/exchange de trading. Si más adelante hacen falta datos premium,
  keys de datos SOLO-LECTURA propias (I-V2).

## 5. Arrancar

```bash
docker compose up -d --build          # backend en 127.0.0.1:8899
docker compose --profile frontend up -d   # (opcional) frontend dev en 127.0.0.1:5899
curl -s http://127.0.0.1:8899/health      # → {"status":"healthy", ...}
```

Los volúmenes (`vibe-home`, `vibe-runs`, `vibe-sessions`, …) persisten memoria, runs y shadow
accounts entre rebuilds — no borrarlos a la ligera.

## 6. Checklist de aislamiento antes de darlo por bueno

- [ ] La VM NO es 167.233.46.18 ni comparte proyecto/VPC/firewall con OLIMPO.
- [ ] `agent/.env` no contiene NINGUNA key presente en el `.env` de OLIMPO (comparar a mano).
- [ ] Ningún connector de broker configurado (`vibe-trading connector` vacío).
- [ ] `ufw status` = deny incoming salvo SSH; `ss -tlnp` solo muestra 8899/5899 en 127.0.0.1.
- [ ] `/health` responde por túnel SSH y NO por `http://VM_IP:8899` desde fuera.

## 7. Uso previsto (I-V3)

Research en esta VM (datos gratuitos: yfinance/ccxt público/stooq/SEC EDGAR funcionan con
egress abierto) → hipótesis con evidencia (fórmula + IS/OOS + walk-forward) → se copian como
spec a OLIMPO y se re-validan en SU backtester antes de que nada toque dinero. Nunca al revés.
