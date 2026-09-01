# Roadmap — K4binho Promo Bot

Atualizado em **2026-08-31**.

## Status atual

O projeto está na fase de **curadoria comercial + inteligência promocional**. A arquitetura básica de fontes, scoring, histórico, PLUS, alertas, analytics e tracking já existe.

### Entregue

- Mercado Livre com scraping de ofertas, highlights, trending e best seller.
- Fallback comercial ML para reduzir silêncio sem liberar oferta fraca.
- Geração de link afiliado `meli.la` via Chrome persistente.
- AliExpress via API afiliada.
- Steam com busca paginada, reviews oficiais Steam, lookup UUID ITAD, waitlist, historical low e descoberta de bundles/packages.
- Nuuvem via ITAD.
- GMG via impact.com, aguardando condição operacional/afiliada.
- PLUS editorial com fallback após janela sem publicação.
- Histórico de preço ML.
- Price-drop e cooldown anti-spam.
- Digest diário persistente, sem duplicar após reinício.
- Alertas personalizados no Telegram.
- Analytics multidimensional.
- Click tracking/redirect opcional.
- Export sanitizado do projeto.
- **Promotion Engine V1**.
- 104 testes passando.

## Promotion Engine V1 — entregue

### Mercado Livre

- descoberta de cupom em texto renderizado da página via Playwright;
- scan limitado por ciclo;
- cache com TTL;
- cupom entra no preço efetivo;
- cupom confirmado aumenta evidência de preço e conversion score;
- condição por usuário/app/moedas não é tratada como preço garantido;
- Telegram exibe código, economia e condições.

### AliExpress

- catálogo `promotions.json` para campanhas/códigos conhecidos;
- melhor cupom aplicável é escolhido automaticamente por preço mínimo/desconto;
- preço efetivo participa do ranking;
- suporte a aviso pré-campanha único.

### Shopee

- modelo de promoção e template já suportam página de resgate e desconto condicional;
- integração de descoberta/postagem segue pendente.

## Próximas prioridades

### P0 — observar dados reais do Promotion Engine

Antes de aumentar agressividade:

1. acompanhar `Promocao`, `Codigos`, `Scaneados`, `Fallback comercial` e `Selecionados` no log do ML;
2. validar se o parser encontra cupons reais como `VANTAGEMJA` quando visíveis para a conta;
3. verificar quantos cupons detectados realmente aplicam no checkout;
4. ajustar `ML_COUPON_SCAN_ITEMS` apenas se o custo/tempo do Chrome estiver aceitável.

### P1 — AliExpress Campaign Discovery

Hoje o motor aplica automaticamente cupons cadastrados, mas a descoberta de códigos de evento ainda precisa de uma fonte confiável. Próximo passo:

- endpoint/feed oficial se disponível;
- importação manual rápida de tabela de cupons;
- validade automática por início/fim;
- combinação segura com moedas sem prometer preço universal.

### P1 — Shopee comercial

Quando AppID/Secret estiverem disponíveis:

- source de produtos;
- links afiliados;
- cupom/voucher landing page;
- loja oficial, vendas e rating;
- preço potencial vs garantido;
- ciclo próprio + analytics.

### P1 — Tracking real em produção

O click server existe, mas `CLICK_BASE_URL=http://localhost:8321` não é clicável pelos usuários do Telegram. Publicar o redirect em domínio/host HTTPS e medir:

```text
source → post → click → compra/conversão
```

Sem impressões do Telegram, usar inicialmente cliques por publicação e cliques por fonte/categoria.

### P2 — SQLite

Migrar gradualmente:

- `seen.json`;
- `price_history.json`;
- `deal_store.json`;
- `alerts.json`;
- `promotion_cache.json`;
- `promotion_state.json`;
- `analytics.jsonl`.

### P2 — Health Check real

Expandir `/status` para mostrar:

- último ciclo por fonte;
- duração do ciclo;
- produtos encontrados/aprovados;
- erros 24h;
- último cupom detectado;
- sessão ML;
- status do redirect de cliques.

## Regras de produto

- ML/Ali são fontes comerciais e merecem prioridade de conversão.
- Steam/Nuuvem/GMG continuam como PLUS e não devem ser removidos por não monetizarem.
- Cupom só deve alterar o score quando o desconto for suficientemente confiável.
- Promoção para usuários selecionados deve ser mostrada como possibilidade, nunca como preço garantido.
- Não aumentar volume apenas para preencher canal.
- Primeiro medir comportamento real; só depois automatizar pesos de scoring.

## Limites conhecidos

| Limite | Situação |
|---|---|
| ML depende de Chrome visível | Necessário por sessão/anti-bot. |
| Parser de cupom ML depende do texto renderizado | Mudanças de UI podem exigir ajuste. |
| Ali não descobre todos os códigos de campanha sozinho | `promotions.json` cobre V1. |
| Shopee ainda não está no loop | Cliente de auth apenas. |
| Click tracking local não funciona para público remoto | Precisa endpoint público. |
| JSON é suficiente para MVP, não para escala alta | SQLite é próximo passo. |

## Segurança

`bot.log` antigo podia registrar URLs completas do `httpx` contendo token/chave. O `bot.py` agora reduz `httpx/httpcore` para WARNING. Mesmo assim:

- rotacione credenciais que já foram expostas em logs compartilhados;
- não envie `.env`;
- não envie `ml_token.json`;
- não envie `ml_profile/`;
- não use ZIP manual da pasta;
- use `export_project.py`.

O exporter agora também ignora **qualquer `.zip` interno**, evitando carregar snapshots antigos com segredos dentro de um novo export.
