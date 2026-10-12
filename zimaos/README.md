# Vibe-Trading on ZimaOS

Import `docker-compose.yml` as a custom app, or run it with Docker Compose.
Set `VIBE_TRADING_IMAGE` to an image and version you have reviewed,
`VIBE_TRADING_APPDATA` to your persistent directory (default
`/DATA/AppData/vibe-trading`), `API_AUTH_KEY` to a strong random key, and
`OPENROUTER_API_KEY` to your provider key. `LANGCHAIN_MODEL_NAME` is optional.
Compose refuses to start without the required values. Set these variables in
ZimaOS before importing, or substitute their values in your private copy.

```bash
docker compose -f zimaos/docker-compose.yml config --quiet
docker compose -f zimaos/docker-compose.yml up -d
```

Open `http://<zimaos-ip>:8899` and enter `API_AUTH_KEY` in Settings → API
authentication key. The initialization container changes ownership only within
the mounted application directories to the image's `vibe` user. It does not
mount the Docker socket. Keep `home`, `runs`, `sessions`, `swarm-runs`, `uploads`
and `br-data` on persistent storage.

## Optional Brazilian data

The application accepts B3 symbols such as `PETR4.SA`, `VALE3.SA` and
`BOVA11.SA`. Yahoo/yfinance provide adjusted bars; the optional local COTAHIST
store provides raw bars with their adjustment basis labelled. Backtests use
BRL, configurable fees, share lots and tick rounding. They do not model
personal income tax, stock-borrow availability/cost or settlement cash locks;
review these assumptions before interpreting results.

The `get_br_market_data` agent tool reads B3 quotes, CVM company/fund data,
Banco Central series and Tesouro Direto prices. CVM statements are the latest
stored revisions, **not** point-in-time backtest inputs. Fund subclasses remain
separate. Data is stored outside the checkout in `~/.vibe-trading/br-data/`,
or at `VIBE_BR_DATA_DB`.

Run selected sources manually inside the application container:

```bash
python -m src.br_data status
python -m src.br_data sync --only bcb tesouro
python -m src.br_data sync --only cotahist --cotahist-from 2025
```

The initial full download can be several GB. The daily sync service is off by
default; enable it explicitly with `--profile br-data-sync` when starting
Compose. Its schedule is controlled by `VIBE_BR_SYNC_TIME` in São Paulo time.
Historical coverage starts at `VIBE_BR_COTAHIST_START_YEAR` (default 2015) and
`VIBE_BR_CVM_START_YEAR` (default 2022). No sync is launched by opening the UI.

## Optional fork publishing

`sync-and-publish.yml.example` is an inactive template for operators who want
to maintain their own fork and GHCR image. It is outside `.github/workflows`
and does not schedule anything in this repository. Review its write permissions,
upstream merge behavior and publishing destination before copying it to your
fork's workflow directory. Configure `UPSTREAM_REPO`, `UPSTREAM_BRANCH` and
`ZIMAOS_PLATFORMS` there. The template supports a manual run and a 30-minute
schedule after explicit installation; conflicts fail for manual resolution.

Use your fork's image tag as `VIBE_TRADING_IMAGE`. Watchtower labels are off by
default; opt in only if automatic replacement of that image is desired. To
roll back, select a previous immutable `sha-<commit>` tag and restart Compose.

## Resumo em português

Configure a imagem, a pasta persistente e as chaves antes de importar o Compose.
O aplicativo não inicia com chaves de exemplo. A sincronização diária dos dados
brasileiros e as atualizações automáticas ficam desativadas por padrão. Ative o
perfil `br-data-sync` somente se quiser baixar a base oficial e mantê-la atualizada.
O workflow é um modelo inativo para seu próprio fork; não publica no upstream.
