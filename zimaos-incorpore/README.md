# Vibe-Trading no ZimaOS (atualização automática)

```
HKUDS/Vibe-Trading ──(a cada 30 min)──▶ incorpore/Vibe-Trading:main
                                              │ build
                                              ▼
                              ghcr.io/incorpore/vibe-trading:latest
                                              │ seu Watchtower (já instalado)
                                              ▼
                                         ZimaOS
```

Tudo é feito por `.github/workflows/zimaos-sync-and-publish.yml` + o
`docker-compose.yml` desta pasta (`zimaos-incorpore/`, exclusiva deste fork; a pasta `zimaos/` é o modelo genérico do projeto oficial). Os arquivos ficam separados do código do
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
   privado, faça `docker login ghcr.io` no ZimaOS com um PAT `read:packages`
   e dê as mesmas credenciais ao seu Watchtower.

Variáveis opcionais (*Settings → Variables*): `UPSTREAM_REPO`,
`UPSTREAM_BRANCH`, `ZIMAOS_PLATFORMS` (ex.: `linux/amd64,linux/arm64`).

## 2. Instalar no ZimaOS

1. App Store → **+** → *Install a customized app* → **Import** → cole o
   conteúdo de `zimaos-incorpore/docker-compose.yml`.
2. Troque `API_AUTH_KEY` por um valor aleatório (`openssl rand -hex 32`).
   Ele é obrigatório: a porta 8899 fica acessível na rede local e a API
   recusa clientes fora do loopback sem chave.
3. Troque `OPENROUTER_API_KEY` pela sua chave (https://openrouter.ai/keys) e,
   se quiser, `LANGCHAIN_MODEL_NAME` por outro modelo do OpenRouter (use o id
   exato da lista em https://openrouter.ai/models, no formato `empresa/modelo`).
   O modelo deve ser trocado aqui, não no *Settings* do Web UI: os valores do
   compose voltam a valer a cada reinício.
4. Instale e abra `http://<ip-do-zima>:8899`. O Web UI não pede a chave
   sozinho: até ela ser informada aparece "O acesso remoto à API requer uma
   chave de API". Vá em **Configurações → Chave de autenticação da API**, cole
   o valor de `API_AUTH_KEY` e salve. A chave fica guardada só naquele
   navegador; repita em cada computador/celular.

### Pastas

Tudo fica em `/media/URSUS/AppData/vibe-trading/`:

| Pasta | Conteúdo |
| --- | --- |
| `home/` | configurações (`.env`), memória, skills, índice de sessões |
| `br-data/` | base oficial brasileira (`br_data.db`, vários GB) |
| `runs/`, `sessions/`, `swarm-runs/`, `uploads/` | arquivos de trabalho do agente |

O container `vibe-trading-init` roda uma vez a cada início: cria as pastas e
passa a posse para o usuário `vibe` da imagem (UID 1000), porque o Docker cria
pastas novas como root. Se ele falhar no seu ZimaOS, rode uma vez no terminal:

```bash
mkdir -p /media/URSUS/AppData/vibe-trading/{home,br-data,runs,sessions,swarm-runs,uploads}
chown -R 1000:1000 /media/URSUS/AppData/vibe-trading
```

### Atualização

Os containers `vibe-trading` e `vibe-trading-br-data` têm o label
`com.centurylinklabs.watchtower.enable=true`, então o Watchtower que você já
tem instalado os atualiza (se ele estiver em modo `--label-enable`, só esses
são atualizados; senão ele já monitora todos). Os dados ficam nas pastas acima
e não são afetados.

## Comportamento

| Evento | Resultado |
| --- | --- |
| Upstream recebeu commits | merge em `main` → build → `:latest` → ZimaOS atualiza |
| Você fez push em `main` | build → `:latest` → ZimaOS atualiza |
| Conflito de merge | o job falha (GitHub te avisa por e-mail); resolva manualmente em `main` |
| *Run workflow* manual | sincroniza e publica mesmo sem mudanças |

Cada build também recebe a tag `:sha-<commit>`; para voltar a uma versão,
troque `latest` por essa tag no compose.

## Dados do mercado brasileiro

### Ações da B3 em tempo quase real (Yahoo)
Use o sufixo `.SA`: `PETR4.SA`, `VALE3.SA`, `BOVA11.SA` (ETF), `HGLG11.SA`
(FII), `AAPL34.SA` (BDR), `PETR4F.SA` (fracionário). O backtest usa regras da
B3: moeda BRL, taxas de negociação + liquidação (0,030% por ordem), corretagem
configurável, lote de 1 ação (`br_lot_size: 100` para lote-padrão), tick de
R$0,01 e venda a descoberto permitida. O benchmark padrão é o `BOVA11.SA`.
Imposto de renda não é descontado por operação.

### Base oficial completa (gratuita)
O serviço `vibe-trading-br-data` do compose baixa e atualiza todo dia às
21:30 (horário de Brasília):

| Fonte | Conteúdo |
| --- | --- |
| B3 COTAHIST | cotação diária de **todos** os ativos da B3 (ações, FIIs, ETFs, BDRs, opções, termo) |
| CVM – fundos | cadastro e informe diário de todos os fundos (cota, PL, captação, resgate, cotistas) |
| CVM – companhias | cadastro, mapa ticker→CNPJ, DFP (anual) e ITR (trimestral) |
| Banco Central (SGS) | Selic, CDI, IPCA, IGP-M, INPC, PTAX, euro, PIB, desemprego (outras séries sob demanda) |
| Tesouro Direto | preços e taxas de todos os títulos, histórico completo |

Os dados ficam em `/media/URSUS/AppData/vibe-trading/br-data/br_data.db`.
O agente consulta tudo pela ferramenta `get_br_market_data`, e o backtest usa
a COTAHIST como fonte reserva quando o Yahoo falha. Os preços da COTAHIST são
os negociados, **sem ajuste** de proventos.

A primeira execução baixa vários GB e pode levar horas. Variáveis do serviço:
`VIBE_BR_COTAHIST_START_YEAR` (padrão 2015; mínimo 1986),
`VIBE_BR_CVM_START_YEAR` (padrão 2022) e `VIBE_BR_SYNC_TIME`.

Comandos manuais (no terminal do container):

```bash
python -m src.br_data status                      # o que já foi baixado
python -m src.br_data sync --only bcb tesouro     # só algumas fontes
python -m src.br_data sync --cotahist-from 1986   # histórico completo da B3
```
