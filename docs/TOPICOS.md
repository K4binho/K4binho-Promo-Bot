# Distribuição por Tópicos — K4binho Promo Bot

Atualizado em **2026-09-03**.

O grupo Telegram (fórum) tem sete tópicos. Cada publicação é roteada pelo
módulo `services/router.py`; o ID de cada tópico vem de `TELEGRAM_TOPIC_<NOME>` no
`.env` (defaults abaixo). As variáveis antigas `TELEGRAM_*_THREAD_ID` deixaram
de ser usadas.

| Tópico | ID | Lojas prioritárias | Lojas complementares |
|---|---|---|---|
| 🔥 Melhores do Dia | 2194 | ML, Shopee, AliExpress, KaBuM, GMG | Steam e Nuuvem só em oferta excepcional |
| 🎮 Jogos em Promoção | 2195 | Green Man Gaming | Steam e Nuuvem |
| 📱 Tecnologia | 2197 | KaBuM, ML, AliExpress | Shopee |
| 🏠 Casa & Cozinha | 2198 | Shopee, ML | AliExpress, KaBuM |
| 👗 Moda & Beleza | 2201 | Shopee, AliExpress | ML |
| 🔧 Ferramentas & Auto | 2202 | ML, AliExpress | Shopee, KaBuM |
| 🎁 Achadinhos | 2205 | Shopee, AliExpress | ML, KaBuM |

A prioridade está em `domain/topics.py`, em `STORE_TOPIC_PRIORITY` (mesma ordem da tabela).
Lojas fora da lista de um tópico não publicam nele.

## Regras de roteamento

- Lojas de jogos (GMG, Steam, Nuuvem) publicam **somente** em Jogos.
- Lojas físicas (ML, Shopee, AliExpress, KaBuM) **nunca** publicam em Jogos.
  Consoles, controles, headsets e componentes gamer vão para Tecnologia.
- O tópico de um produto físico é decidido por palavras-chave do título
  (`services/categorizer.py`). Palavras mais longas/específicas pesam mais, por
  isso "relógio inteligente" vai para Tecnologia e "relógio masculino" para
  Moda & Beleza; "câmera veicular" vai para Ferramentas & Auto e "câmera
  Wi-Fi" para Tecnologia.
- Sem match de palavra-chave, o produto cai em Achadinhos.
- Se a loja não é permitida no tópico classificado (ex.: KaBuM em Moda &
  Beleza), o produto também cai em Achadinhos.
- Avisos de campanha (`promotions.json`): lojas de jogos → Jogos; demais →
  Melhores do Dia. O digest "TOP OFERTAS DO DIA" vai para Melhores do Dia.

## 🔥 Melhores do Dia (vitrine)

Não tem coleta própria. Ao fim de cada ciclo, `services/showcase.py` copia para
o tópico as melhores publicações que já saíram nos outros tópicos.

Critérios (`services/showcase_rules.py`):

- Produto físico: precisa de imagem e reputação não negativa (nota ≥ 4,0 quando
  conhecida) **e** pelo menos um critério forte — desconto real ≥ 40 %
  (`MELHORES_DO_DIA_MIN_DISCOUNT`), cupom garantido ≥ 5 % do preço ou menor
  preço registrado — **ou** dois critérios de apoio (≥ 1000 vendas, frete grátis).
- GMG: jogo gratuito ou desconto ≥ 70 % (`MELHORES_DO_DIA_MIN_GAME_DISCOUNT`).
- Steam/Nuuvem: gratuito, ou desconto ≥ 70 % **com** forte valor editorial
  (review ≥ 85 % ou menor preço histórico). Sempre entram atrás das lojas com
  comissão.

Ordem de cópia: prioridade da loja (ML > Shopee > Ali > KaBuM > GMG > Steam/
Nuuvem) e, dentro da mesma loja, maior score. Limites:
`MELHORES_DO_DIA_MAX_PER_CYCLE` (2) e `MELHORES_DO_DIA_MAX_PER_DAY` (8). O
mesmo produto não é copiado de novo por 7 dias (`showcase_state.json`).

A cópia recebe o cabeçalho `🏆 MELHORES DO DIA · <tópico> · <loja>` e mantém o
corpo original (preço, cupom, link afiliado, imagem).

## Fontes por tópico

### 🎮 Jogos — GMG (Impact), Steam, Nuuvem

- GMG é a única fonte com comissão e tem prioridade máxima.
- Steam e Nuuvem são editoriais (PLUS) e alimentam o fallback editorial.
- A integração da GMG é **impact.com** (`providers/gmg.py`). Impact.com não é a
  antiga CJ Affiliate. `IMPACT_ACCOUNT_SID`/`IMPACT_AUTH_TOKEN` são as
  variáveis oficiais; `CJ_ACCOUNT_SID`/`CJ_AUTH_TOKEN` seguem aceitas apenas
  como aliases.

### 📱 Tecnologia — KaBuM, ML, AliExpress, Shopee

KaBuM (`providers/kabum.py`, API pública de catálogo `catalog/v2/products` + link afiliado Awin) foi ligado ao
ciclo. Sem `KABUM_AWIN_TOKEN`/`KABUM_PUBLISHER_ID` o ciclo é pulado; sem link
afiliado gerado a oferta não é publicada.

Atenção: o "de" da KaBuM (`price`) costuma ser inflado, então o desconto
calculado (preço de tabela vs. à vista da oferta) tende a ser alto. A vitrine
já coloca a KaBuM em 4º na prioridade; se ela dominar o Melhores do Dia, suba
`KABUM_MIN_DISCOUNT_PERCENT` ou trate o desconto da KaBuM com um teto.

### 🏠 Casa & Cozinha / 👗 Moda & Beleza / 🎁 Achadinhos — Shopee em primeiro

Shopee (`providers/shopee.py`) usa a Open API GraphQL de afiliados (`productOfferV2`),
com `SHOPEE_SEARCHES` como lista de palavras-chave. `offerLink` já é o link
afiliado. Filtros: `SHOPEE_MIN_DISCOUNT_PERCENT`, `SHOPEE_MIN_SALES`.

### 🔧 Ferramentas & Auto — ML em primeiro

ML e AliExpress são as fontes principais. Para alimentar o tópico, mantenha
palavras de ferramentas/auto em `ALIEXPRESS_SEARCHES` e categorias ML
correspondentes em `ML_HIGHLIGHT_CATEGORY_IDS`.

## Ordem do ciclo

```text
campanhas → ML → Shopee → AliExpress → KaBuM → GMG → Steam → Nuuvem
→ fallback editorial (se nenhum PLUS saiu) → vitrine Melhores do Dia → digest
```

Lojas com comissão rodam antes das editoriais. Falha em Shopee/Ali/KaBuM é
registrada no log e não derruba o restante do ciclo.

## Diagnóstico no log

```text
[Shopee] Encontrados: ... | Candidatos: ... | Selecionados: ...
[Kabum] Encontrados: ... | Candidatos: ... | Selecionados: ...
[Vitrine] Candidatos: ... | Ineditos: ... | Orcamento: ...
[Vitrine] copiado: 📱 Tecnologia · Mercado Livre | desconto real 55%
```

No `--dry-run`, cada fonte lista `score | desconto | tópico | título`. A
vitrine só avalia publicações realmente enviadas, então em dry-run ela não
lista candidatos. `/status` (admin) mostra publicações por loja e por tópico.

## Pendências de validação ao vivo

- Shopee: `productOfferV2` respondeu ao vivo em 2026-09-03 (286 ofertas em um
  ciclo); observar limites de chamadas por ciclo.
- KaBuM: a API de catálogo já respondeu ao vivo (2026-09-03); falta confirmar
  que o link builder Awin devolve `shortUrl`/`url`.
- Impact: paginação e filtro `Currency=BRL` funcionaram ao vivo (9.440 itens).
- Ajustar palavras-chave de `services/categorizer.py` conforme produtos reais
  caírem em Achadinhos por falta de match.
