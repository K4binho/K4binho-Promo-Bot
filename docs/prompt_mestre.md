# Prompt Mestre — K4binho Promo Bot

Contexto atualizado em **2026-08-31** para continuar o projeto com outra IA.

## Objetivo

Transformar o bot em uma plataforma inteligente de curadoria de ofertas, equilibrando:

```text
valor para o usuário
→ confiança
→ retenção
→ cliques
→ compras
→ receita de afiliados
```

Não remover a camada PLUS apenas por não monetizar.

## Fontes

- **Mercado Livre** — comercial principal, afiliado.
- **AliExpress** — comercial, afiliado.
- **Steam** — PLUS/editorial.
- **Nuuvem** — PLUS/editorial.
- **GMG** — PLUS, código impact.com pronto.
- **Shopee** — cliente de API pronto, ainda sem ciclo no bot.

## Arquitetura real

```text
Sources
  ↓
Normalization
  ↓
Promotion Engine
  ↓
Effective Price / Conditions
  ↓
Price History
  ↓
Quality / Conversion / Retention / Confidence
  ↓
Ranking + Diversity
  ↓
Telegram
  ↓
Click Tracking + Analytics + Alerts
```

## Promotion Engine V1

Arquivo: `promotion_engine.py`.

Responsabilidades:

- normalizar cupom/desconto/campanha;
- compra mínima/teto;
- condição por usuário/app/moedas;
- preço garantido vs preço potencial;
- catálogo `promotions.json`;
- cache `promotion_cache.json`;
- estado de campanhas `promotion_state.json`;
- parser conservador de texto renderizado do ML.

### Regra crítica

**Preço condicional nunca entra como preço garantido no score.**

Ex.: “R$100 OFF apenas para usuários selecionados” pode ser exibido como possibilidade, mas o ranking usa o preço normal.

### ML

`bot.py` escolhe até `ML_COUPON_SCAN_ITEMS` anúncios fortes sem cache e chama `ml_playwright.discover_promotions()`.

O resultado fica em cache por `ML_COUPON_CACHE_HOURS`.

Cupom confirmado:

- reduz `effective_price`;
- aumenta evidência de preço;
- aumenta quality/conversion;
- aparece no Telegram;
- vai para analytics.

O histórico continua registrando preço listado.

### AliExpress

Cupons de evento entram via `promotions.json`. O motor testa automaticamente compra mínima e escolhe a melhor regra aplicável.

### Shopee

Promotion Engine e template suportam `coupon_rescue` e selected users, mas o source ainda não está integrado ao loop.

## Mercado Livre — estratégia comercial

ML tem prioridade monetária e não deve ficar silencioso por excesso de conservadorismo.

Existe fallback comercial:

- preço precisa passar no gate;
- item não pode estar em seen;
- score mínimo do fallback = `max(60, SCORE_MIN - 10)`;
- precisa de sinal forte: bestseller/trending/loja oficial/vendas/rating/cupom garantido;
- pensado para itens ainda sem histórico completo.

Diagnóstico de funil inclui:

```text
Encontrados
Preco OK
Historico pronto
Launch score
Sinal comercial forte
Ja vistos
Promocao
Codigos
Scaneados
Aprovados estritos
Fallback comercial
Candidatos
Selecionados
```

## Steam

Estado atual:

- busca ~500 ofertas;
- app/package/bundle;
- descoberta limitada de bundles a partir de páginas de apps;
- Steam Reviews para review score/count;
- ITAD `/games/lookup/v1` para UUID;
- ITAD waitlist + history low;
- bundles/packages podem passar por score editorial mesmo sem reviews próprias.

Não voltar a usar `games/info/v2?id=app/{steamid}` — isso causava 400.

## Analytics

`analytics.record_deal()` registra também:

- `listed_price`;
- `promotion_code`;
- `promotion_savings`;
- `promotion_conditional`.

O campo `price` passa a representar o preço efetivo garantido quando houver cupom aplicável.

## Segurança

- Não imprimir segredos.
- `.env`, token ML, perfil Chrome, logs e runtime JSON ficam fora do export.
- `httpx/httpcore` ficam em WARNING no `bot.py`.
- `export_project.py` ignora qualquer ZIP interno.
- Use somente export sanitizado para compartilhar o projeto.

## Testes

Estado desta versão:

```text
104 passed
```

Comando:

```bash
python -m pytest -q
```

## Próximos passos recomendados

1. Validar Promotion Engine em ciclos reais do ML.
2. Medir quantos cupons descobertos realmente aplicam no checkout.
3. Criar fonte confiável de descoberta de cupons/eventos AliExpress.
4. Publicar click redirect em URL HTTPS pública.
5. Integrar Shopee quando credenciais/API estiverem disponíveis.
6. Migrar persistência para SQLite antes de ML/analytics crescerem demais.

## Regras para futuras alterações

- não quebrar ML, Steam, Nuuvem, GMG ou Ali existentes;
- não remover PLUS;
- rodar testes antes/depois;
- preferir mudanças incrementais;
- atualizar documentação junto com código;
- não inventar preço de cupom;
- não tratar promoção personalizada como universal;
- medir antes de automatizar aprendizado de pesos.
