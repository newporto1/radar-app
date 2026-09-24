# Radar Crypto

App própria, gratuita e fora do Claude:

- **GitHub Actions** corre o algoritmo v3 todos os dias às 06:30 UTC.
- **GitHub Pages** aloja a app, que se instala no telemóvel como qualquer outra.
- **ntfy** manda-te uma notificação push quando há alertas.

Nada disto coloca ordens. Executas as compras e vendas à mão na Binance.

## Instalação (≈10 minutos, uma vez)

1. **Cria um repositório** no GitHub (ex.: `radar`), público.
   Os repositórios privados só têm Pages nos planos pagos.
   Carrega **todo** o conteúdo desta pasta, incluindo a pasta escondida `.github`.
   A forma mais fácil é arrastar os ficheiros em *Add file → Upload files*.
2. **Ativa o Pages:** *Settings → Pages → Source: Deploy from a branch → Branch: `main`, pasta `/docs`* → *Save*.
   Um minuto depois, a app fica em `https://<o-teu-utilizador>.github.io/radar/`.
3. **Notificações:**
   1. Instala a app **ntfy** (iOS ou Android).
   2. Na ntfy, subscreve um tópico com um nome difícil de adivinhar, por exemplo `radar-lima-7f3k9q2x`. Quem souber o nome pode ler as mensagens.
   3. No GitHub, vai a *Settings → Secrets and variables → Actions → New repository secret*.
   4. Cria o segredo com o nome `NTFY_TOPIC` e, como valor, o nome desse tópico.
4. **Permissões:** *Settings → Actions → General → Workflow permissions → Read and write* → *Save*.
5. **Testa:** *Actions → Radar diário → Run workflow*.
   Se o dataset ainda não tiver dados novos, o registo diz «sem dados novos hoje». Isso é normal.
6. **No telemóvel:** abre o link da app.
   - iPhone: Safari → Partilhar → *Adicionar ao ecrã principal*.
   - Android: Chrome → ⋮ → *Instalar app*.

## Como funciona

| Ficheiro | Função |
|---|---|
| `radar/radar_run.py`, `radar/signals.py` | Algoritmo v3 (idêntico ao do projeto) |
| `scripts/update.py` | Corre o radar, compara com o estado anterior, grava `docs/data/*.json` e notifica |
| `.github/workflows/radar.yml` | Agenda diária e commit automático dos dados |
| `docs/` | A app (HTML estático + PWA) |

- O estado inicial em `docs/data/` é o que estava na app antiga (v3, dados até 22/09).
  Os alertas continuam a ser calculados a partir daí.
- O botão «Feito» fica guardado no dispositivo onde carregas nele.
- Para mudar o capital, altera `CAPITAL` em `.github/workflows/radar.yml`.
- O GitHub pode atrasar corridas agendadas alguns minutos, e às vezes mais.
  Desativa-as se o repositório estiver 60 dias sem atividade, mas os commits diários dos dados evitam isso.
