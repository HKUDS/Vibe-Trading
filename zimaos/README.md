# Vibe-Trading no ZimaOS (atualização automática)

```
HKUDS/Vibe-Trading ──(a cada 30 min)──▶ incorpore/Vibe-Trading:main
                                              │ build
                                              ▼
                              ghcr.io/incorpore/vibe-trading:latest
                                              │ Watchtower (a cada 5 min)
                                              ▼
                                         ZimaOS
```

Tudo é feito por `.github/workflows/zimaos-sync-and-publish.yml` + o
`docker-compose.yml` desta pasta. Os arquivos ficam separados do código do
upstream para que o merge automático não gere conflitos.

## 1. Configuração única no GitHub

1. **Actions habilitadas** no fork (aba *Actions* → "I understand… enable").
   Em forks, workflows agendados ficam desligados até você habilitar.
2. **Secret `UPSTREAM_SYNC_TOKEN`** (recomendado): *Settings → Secrets and
   variables → Actions → New repository secret*. Use um *fine-grained PAT* só
   para este repositório com **Contents: Read and write** e
   **Workflows: Read and write**. Sem ele o sync funciona, mas falha quando o
   upstream altera arquivos em `.github/workflows/`.
3. Rode o workflow uma vez manualmente (*Actions → ZimaOS - Sync upstream and
   publish image → Run workflow*) para publicar a primeira imagem.
4. **Torne o pacote público** (uma vez): *github.com/incorpore → Packages →
   vibe-trading → Package settings → Change visibility → Public*. Se preferir
   privado, descomente `REPO_USER`/`REPO_PASS` no compose (PAT com
   `read:packages`) e faça `docker login ghcr.io` no ZimaOS.

Variáveis opcionais (*Settings → Variables*): `UPSTREAM_REPO`,
`UPSTREAM_BRANCH`, `ZIMAOS_PLATFORMS` (ex.: `linux/amd64,linux/arm64`).

## 2. Instalar no ZimaOS

1. App Store → **+** → *Install a customized app* → **Import** → cole o
   conteúdo de `docker-compose.yml`.
2. Troque `API_AUTH_KEY` por um valor aleatório (`openssl rand -hex 32`).
   Ele é obrigatório: a porta 8899 fica acessível na rede local e a API
   recusa clientes fora do loopback sem chave.
3. Instale e abra `http://<ip-do-zima>:8899`; informe a chave quando o Web UI
   pedir. Chaves de LLM podem ser colocadas no compose ou no *Settings* do
   Web UI (ficam salvas no volume `vibe-home`).

O container `vibe-trading-watchtower` verifica a imagem a cada 5 minutos e
recria só o `vibe-trading` (por causa do label) mantendo os volumes.

## Comportamento

| Evento | Resultado |
| --- | --- |
| Upstream recebeu commits | merge em `main` → build → `:latest` → ZimaOS atualiza |
| Você fez push em `main` | build → `:latest` → ZimaOS atualiza |
| Conflito de merge | o job falha (GitHub te avisa por e-mail); resolva manualmente em `main` |
| *Run workflow* manual | sincroniza e publica mesmo sem mudanças |

Cada build também recebe a tag `:sha-<commit>`; para voltar a uma versão,
troque `latest` por essa tag no compose.
