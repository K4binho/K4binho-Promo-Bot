# K4binho Promo Bot

Plataforma Python de curadoria automática de ofertas para Telegram. O projeto combina fontes comerciais monetizadas com uma camada editorial PLUS de games, histórico de preços, scoring multidimensional, cupons/promoções condicionais, alertas, tracking e analytics.

## Estado atual — 2026-08-31

Pipeline principal:

```text
FONTES
  ↓
NORMALIZAÇÃO
  ↓
PROMOTION ENGINE
  ↓
PREÇO EFETIVO / CONDIÇÕES
  ↓
HISTÓRICO
  ↓
QUALITY + CONVERSION + RETENTION + CONFIDENCE
  ↓
RANKING / DIVERSIFICAÇÃO
  ↓
TELEGRAM
  ↓
TRACKING / ANALYTICS / ALERTAS
```

### Fontes

| Fonte | Papel | Afiliado | Status |
|---|---|---:|---|
| Mercado Livre | Comercial principal | Sim | Ativo |
| AliExpress | Comercial | Sim | Ativo |
| Steam | PLUS / retenção | Não | Ativo |
| Nuuvem | PLUS / retenção | Não | Ativo |
| Green Man Gaming | PLUS | Não por enquanto | Código pronto; depende da aprovação/credenciais impact.com |
| Shopee | Comercial futuro | Sim quando habilitado | Cliente de API pronto, ciclo ainda não integrado |

## Promotion Engine V1

O módulo `promotion_engine.py` normaliza promoções de lojas diferentes e evita tratar toda promoção como se fosse garantida.

Suporta:

- cupom por código;
- desconto fixo;
- desconto percentual;
- compra mínima;
- teto de desconto;
- promoções apenas para usuários selecionados;
- promoções exclusivas do app;
- promoções que exigem moedas;
- páginas para resgate de cupons;
- campanhas com data/hora e aviso único;
- cálculo de preço garantido e preço potencial;
- cache das promoções descobertas no Mercado Livre.

### Mercado Livre

O ML continua usando `/ofertas` + `/highlights` + sinais de tendência/mais vendidos. Antes do score final, o bot pode abrir uma pequena amostra dos anúncios no Chrome logado e procurar cupons visíveis no texto renderizado.

Por padrão:

- escaneia até `ML_COUPON_SCAN_ITEMS=8` anúncios por ciclo;
- guarda o resultado por `ML_COUPON_CACHE_HOURS=6`;
- usa cupom confirmado no cálculo do preço efetivo e do score;
- não grava o preço com cupom no histórico base, evitando contaminar a série histórica;
- promoções condicionais não reduzem o preço usado no score.

O ML também possui fallback comercial seguro: produto forte pode publicar antes de completar as 4 observações de histórico quando tem evidência de preço + sinal comercial relevante.

### AliExpress

A API de afiliado continua fornecendo produtos e links. Cupons/campanhas adicionais podem ser cadastrados em `promotions.json`. O motor escolhe automaticamente a melhor faixa aplicável ao preço do produto e usa o preço efetivo no ranking.

Exemplo conceitual:

```text
R$ 1.350
BRFS4 = R$ 80 OFF em R$ 680
BRFS5 = R$ 140 OFF em R$ 1.200  ← melhor regra aplicável
Preço efetivo = R$ 1.210
```

### Shopee

A estrutura do Promotion Engine já suporta:

- link separado para resgatar cupons;
- desconto na finalização;
- restrição a usuários selecionados;
- mensagens transparentes sobre preço potencial.

O ciclo de descoberta/postagem da Shopee ainda não está ligado ao `bot.py` porque depende da integração de produto/credenciais da Open API.

## Componentes principais

| Arquivo | Papel |
|---|---|
| `bot.py` | Orquestra ciclos, ranking, campanhas, Telegram e analytics. |
| `promotion_engine.py` | Cupons, promoções condicionais, preço efetivo, cache e campanhas. |
| `promotions.example.json` | Modelo de catálogo manual de promoções/campanhas. |
| `ml_scraper.py` | Parser das páginas públicas de ofertas do ML. |
| `mercadolivre.py` | Descoberta ML via OAuth `/highlights` + `/items`. |
| `ml_playwright.py` | Descobre cupom renderizado e gera `meli.la` em Chrome logado. |
| `ml_signals.py` | Mais vendidos e tendências do Mercado Livre. |
| `aliexpress.py` | API de afiliado AliExpress. |
| `steam.py` | Steam search + reviews Steam + ITAD + bundles/packages. |
| `nuuvem.py` | Ofertas Nuuvem + ITAD. |
| `gmg_cj.py` | Catálogo/promos GMG via impact.com. |
| `shopee_api.py` | Cliente GraphQL Shopee, ainda fora do loop principal. |
| `scoring.py` | Score multidimensional comercial e PLUS. |
| `telegram.py` | Templates de ofertas, cupons, campanhas e games. |
| `price_history.py` | Histórico de preço base do ML. |
| `deal_store.py` | Último preço publicado e price-drop. |
| `analytics.py` | Eventos publicados + scores + dados de promoção. |
| `click_tracker.py` / `click_server.py` | Redirect para medir cliques. |
| `digest_store.py` | Proteção persistente contra TOP diário duplicado. |
| `export_project.py` | Export sanitizado sem segredos/estado/ZIPs antigos. |

## Testes

A suíte atual possui **104 testes automatizados** e passa com:

```bash
python -m pytest -q
```

Use `python -m pytest`, não apenas `pytest`, para garantir que a raiz do projeto entre corretamente no `sys.path` neste ambiente.

## Documentos

- `docs/OPERACAO.md` — instalação, configuração e execução.
- `docs/ROADMAP.md` — status real e próximos passos.
- `docs/ProximosPasso.md` — prioridades de produto/engenharia.
- `docs/prompt_mestre.md` — contexto compacto para continuar o projeto com outra IA.

> Nunca compartilhe `.env`, `ml_token.json`, `ml_profile/`, `bot.log` ou ZIP manual da pasta. Use `python export_project.py` para gerar um pacote sanitizado.
