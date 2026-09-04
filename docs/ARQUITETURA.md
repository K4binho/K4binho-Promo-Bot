# Arquitetura — K4binho Promo Bot

Atualizado em **2026-09-03**.

O projeto era um script único: `bot.py` com 1.863 linhas concentrava
orquestração, regras de aprovação, publicação, duplicação e os ciclos das sete
fontes. O mesmo pipeline aparecia copiado sete vezes, com variações pequenas.

Hoje o código é o pacote `k4promo`, em `src/`. O `bot.py` da raiz sobrou como
lançador de 15 linhas para que os atalhos do Windows continuem funcionando.

## Mapa

| Caminho | Responsabilidade |
|---|---|
| `src/k4promo/main.py` | Configuração, inicialização, registro das fontes, laço do ciclo, encerramento |
| `src/k4promo/config.py` | Leitura e validação do `.env` |
| `src/k4promo/domain/topics.py` | Tópicos, lojas e prioridade de loja por tópico |
| `src/k4promo/domain/models.py` | `Offer`, o modelo padronizado de oferta |
| `src/k4promo/providers/adapters.py` | Dataclass de cada loja → `Offer` |
| `src/k4promo/providers/` | Acesso a dado bruto de cada loja |
| `src/k4promo/providers/mercadolivre/` | Scraper, API, navegador, sinais, OAuth e o ciclo do ML |
| `src/k4promo/services/cycles/` | Um ciclo por loja: o que esta loja publica agora |
| `src/k4promo/services/scoring.py` | Pontuação multidimensional |
| `src/k4promo/services/categorizer.py` | Título do produto → tópico |
| `src/k4promo/services/router.py` | Tópico → thread do Telegram |
| `src/k4promo/services/publisher.py` | Link, envio, seen, vitrine, analytics e alertas |
| `src/k4promo/services/dedup.py` | Liberar o que saiu de promoção, filtrar visto, consolidar título |
| `src/k4promo/services/showcase.py` | Vitrine Melhores do Dia |
| `src/k4promo/services/promotions.py` | Motor de cupons e campanhas |
| `src/k4promo/telegram/` | `client.py` envia, `formatters.py` monta a mensagem |
| `src/k4promo/commands/admin.py` | Comandos do Telegram e alertas do usuário |
| `src/k4promo/storage/` | Repositórios JSON e resolução do diretório de dados |
| `scripts/` | Login do ML, setup do OAuth, export sanitizado |
| `tests/` | Suíte automatizada |

## O que sumiu da duplicação

Cada ciclo repetia a mesma sequência ao publicar: embrulhar link, enviar,
marcar visto, oferecer à vitrine, gravar analytics, checar alertas e espaçar o
próximo envio. Isso virou `Publisher.publish`. As regras de duplicação viraram
`dedup.release_stale` e `dedup.dedupe_by_title`.

## O modelo único de oferta

Cada loja chama os mesmos campos de um jeito: `item_id` no Mercado Livre,
`product_id` no AliExpress, `game_id` na Steam; a imagem é `thumbnail` num,
`header_image` noutro, `image_url` nos demais. Os providers continuam com o
dataclass que espelha a resposta da própria API, e os adaptadores convertem para
`Offer` na entrada do ciclo.

A partir daí ninguém mais precisa saber a loja de origem. `Offer.key` dá a chave
de deduplicação, `Offer.discount_from` calcula o desconto real pós-cupom, e o
publisher deriva sozinho os campos de analytics e os sinais da vitrine. O ciclo
só passa o que é de fato específico da loja: categoria, tipo de deal e o cupom
aplicado.

`Offer` é um superconjunto de propósito: carrega tanto os sinais de produto
físico quanto os de jogo. Por isso os portões `steam.is_quality_game` e
`nuuvem.is_most_wanted` funcionam sobre a oferta normalizada sem alteração.

Com isso, um ciclo de loja passou a ter entre 85 e 143 linhas e diz apenas o que
é específico dela: onde buscar, qual filtro mínimo, como pontuar, qual formato
de mensagem.

## Estado do ciclo

`CycleContext` carrega o que antes eram variáveis globais de módulo
(`_click_links`, `_plus_candidates`, `_showcase_candidates`) e os quatro
parâmetros repetidos em cada `run_*_cycle`. Cada ciclo recebe um contexto e
declara o que lê e escreve, o que também deixa os testes independentes.

## Onde ficam os dados

Os arquivos de estado (`seen.json`, `price_history.json`, `analytics.jsonl`,
`deal_store.json`, `showcase_state.json`, `promotion_cache.json`, `ml_token.json`,
`ml_profile/`) continuam na raiz do projeto. Antes o caminho era relativo ao
arquivo Python; agora é resolvido por `storage/paths.py`, que usa o diretório de
trabalho e aceita `K4PROMO_DATA_DIR` como alternativa. Os atalhos `.bat`/`.vbs`
já fazem `cd` para a raiz antes de iniciar, então nada muda na operação.

## Ordem do ciclo

```text
campanhas → ML → Shopee → AliExpress → KaBuM → GMG → Steam → Nuuvem
→ fallback editorial (se nenhum PLUS saiu) → vitrine Melhores do Dia → digest
```

Adicionar uma loja é escrever um `providers/<loja>.py`, um
`services/cycles/<loja>.py` e acrescentar uma linha em `COMMERCIAL_CYCLES` ou
`EDITORIAL_CYCLES` no `main.py`. Uma fonte que falhe é registrada no log e não
derruba as demais.

## Como rodar

```bash
python bot.py --dry-run --once
```

O lançador da raiz insere `src/` no path, então não é preciso instalar nada.
Para desenvolvimento, `pip install -e .` habilita `python -m k4promo` e o
comando `k4promo`. A suíte roda com `python -m pytest -q`, sem instalação,
porque o `pyproject.toml` já aponta o `pythonpath` para `src`.

## Encerramento

`main.py` trata `SIGINT`/`SIGTERM`: termina o ciclo corrente, grava `seen`,
histórico e ofertas publicadas, e libera a porta do lock de instância única.
Antes, uma interrupção podia perder o que estava em memória.

## Pendências

- `storage/` guarda JSON. A migração para SQLite continua como P2 e agora pode
  acontecer atrás dos repositórios, sem tocar nos ciclos.
- Existem dois vocabulários de categoria: `scoring.CATEGORY_KEYWORDS`, usado para
  boost de score e diversidade, e `categorizer.TOPIC_KEYWORDS`, usado para
  escolher o tópico. São propósitos diferentes, mas vale unificar quando houver
  dados de clique por categoria.
