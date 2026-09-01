# Próximos Passos — K4binho Promo Bot

Atualizado em **2026-08-31**. Este documento substitui o planejamento antigo por um plano alinhado ao código real.

## Visão do produto

O K4binho Promo Bot não deve ser um canal que publica qualquer desconto. A proposta é ser um **motor de curadoria de ofertas** que encontre preço bom, explique a condição corretamente e priorize aquilo que tem maior valor para usuário e negócio.

A fórmula continua:

```text
VALOR → CONFIANÇA → RETENÇÃO → CLIQUES → COMPRAS → RECEITA
```

## O que já está consolidado

### Curadoria

- histórico de preço ML;
- scoring multidimensional;
- diversidade por categoria;
- anti-spam/seen;
- price-drop;
- sinais de bestseller/trending;
- fallback comercial ML;
- feed Ali filtrado por categoria/vendas;
- PLUS de games separado do comercial.

### Games / PLUS

- Steam;
- Nuuvem;
- GMG;
- fallback editorial após período sem PLUS;
- Steam com reviews reais + ITAD + bundles/packages.

### Operação

- Telegram por tópicos;
- alertas personalizados;
- digest diário persistente;
- analytics;
- click tracking opcional;
- single-instance lock;
- export sanitizado.

### Promotion Engine V1

Já implementado:

- cupom fixo ou percentual;
- compra mínima;
- teto de desconto;
- app-only;
- moedas;
- usuários selecionados;
- resgate de cupons;
- campanhas futuras;
- preço efetivo vs potencial;
- scan/cache de cupons ML;
- catálogo manual multi-loja;
- score com cupom garantido;
- Telegram com condições claras.

## Prioridade 1 — validar ML Coupon Discovery

O objetivo agora não é adicionar mais regras no escuro. Rode o bot e observe alguns ciclos.

Precisamos responder:

1. Quantos anúncios foram escaneados?
2. Quantos retornaram promoção?
3. Quantos retornaram código de cupom?
4. Quantos cupons realmente mudaram o ranking?
5. Quantos produtos publicados vieram por fallback comercial?
6. O Chrome ficou lento demais?
7. Algum cupom detectado era personalizado/inválido no checkout?

Se a taxa de acerto estiver boa, podemos ampliar scan ou fazer descoberta de campanha global.

## Prioridade 2 — campanhas do AliExpress

O V1 aceita códigos em `promotions.json`, mas falta automatizar a descoberta.

Estratégia desejada:

```text
fonte confiável da campanha
→ códigos + valores + mínimos + validade
→ Promotion Engine
→ preço efetivo por produto
→ score
→ Telegram
```

Não raspar canais de terceiros como fonte principal. Eles servem como referência de produto, não como verdade operacional.

### Moedas

Moedas não devem ser tratadas como desconto garantido sem sabermos:

- saldo necessário;
- limite de uso;
- elegibilidade;
- se é somente app;
- se combina com cupom.

Até termos esses dados, mostrar como condição e não usar no score garantido.

## Prioridade 3 — Shopee

Quando a Open API estiver operacional:

1. criar `shopee.py` source;
2. buscar ofertas com venda/rating/loja;
3. gerar link afiliado;
4. associar página de resgate de vouchers;
5. suportar desconto de checkout para selected users;
6. criar `run_shopee_cycle()`;
7. analytics + alerts + digest;
8. testes.

Objetivo de mensagem:

```text
🔥 OFERTA • SHOPEE
Produto
R$ X
🎟 Resgate os cupons antes da compra
⚠ condição quando houver
[RESGATAR CUPONS]
[VER PRODUTO]
```

## Prioridade 4 — monetização baseada em dados

ML merece mais espaço porque é a fonte comercial principal, mas isso deve ser medido.

Métricas mínimas:

- posts por fonte;
- cliques por fonte;
- cliques por categoria;
- cliques por faixa de preço;
- posts com cupom vs sem cupom;
- click rate relativo por tipo de mensagem;
- price-drop vs oferta nova.

Quando houver conversão/receita disponível, adicionar:

- EPC aproximado;
- receita por 100 posts;
- receita por categoria;
- receita por horário.

## Prioridade 5 — click tracking público

O redirect já existe. Falta colocar em endereço público HTTPS.

Depois disso:

```text
Telegram → /go/{deal_id} → analytics click → loja
```

Sem isso, não ajustar score automaticamente.

## Prioridade 6 — SQLite

JSON ainda funciona, mas o projeto já tem estados demais.

Migrar quando a validação comercial estiver estável:

- seen;
- preços;
- deals publicados;
- alertas;
- promo cache/state;
- analytics;
- clicks.

## Prioridade 7 — scheduler inteligente

Hoje o ciclo publica os melhores candidatos encontrados. Depois de termos dados de clique, testar:

- horários por categoria;
- reserva de slots para ML;
- evitar sequências longas da mesma fonte;
- fast lane para cupom de validade curta;
- campanha com hora de ativação;
- expiração automática da promoção.

## O que NÃO fazer agora

- não adicionar dez novas lojas;
- não treinar ML/IA de ranking sem dados reais;
- não baixar todos os filtros só para aumentar volume;
- não transformar Steam/Nuuvem em fonte comercial;
- não publicar preço de selected users como garantido;
- não fazer scraping massivo do ML a cada ciclo;
- não armazenar segredo em log/export.

## Critério para Promotion Engine V2

Só evoluir para V2 quando houver amostra suficiente de ciclos reais.

V2 pode incluir:

- descoberta global de campanha ML;
- detecção de validade/estoque de cupom;
- stacking explícito de `cupom + moedas`;
- regras por seller/categoria;
- prioridade por expiração;
- cupom compartilhado entre produtos elegíveis com confirmação;
- dashboard de campanhas.

## Estado dos testes

```text
104 passed
```

Qualquer mudança deve manter a suíte verde e incluir teste para nova regra promocional.
