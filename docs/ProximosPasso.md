# Próximos Passos — K4binho Promo Bot

Atualizado em **2026-09-01**.

## Onde estamos

A prioridade deixou de ser criar mais fontes e passou a ser **fazer o Mercado Livre converter melhor sem perder qualidade**.

### ✅ Promotion Engine V1.1 entregue no código

- fallback comercial não fica preso a `not history_ready`;
- sinais comerciais agora precisam formar evidência suficiente;
- rating alto sozinho não basta;
- scanner de promoções tenta expandir cupom/benefício/desconto;
- ações de compra/carrinho/checkout são explicitamente bloqueadas no scanner;
- itens em `seen` podem voltar ao scanner após expiração do cache;
- promoções encontradas têm cache positivo mais curto;
- nova promoção pode reativar produto visto quando reduz de verdade o preço efetivo;
- revival tem cooldown e queda mínima;
- logs ML ganharam diagnóstico detalhado;
- suíte completa: **122 testes passando** (verificado em 2026-09-01).

## Prioridade 1 — validar V1.1 ao vivo

Rode alguns ciclos reais com a sessão do Mercado Livre logada e responda:

1. Quantos itens ficam em `Promo scan elegiveis`?
2. Quantos foram `Scaneados`?
3. Quantas `Promo encontradas`?
4. Quantos códigos foram identificados?
5. O scanner encontrou promoções em produtos já vistos?
6. O fallback voltou a gerar candidatos úteis?
7. Algum `promo-revival` foi disparado corretamente?
8. O Chrome continua com tempo aceitável de execução?

Linhas importantes:

```text
[ML][promo-scan]
[ML][promo-revival]
[ML][fallback-comercial]
[ML][cupom...]
```

Não aumentar mais o número de scans antes dessa medição.

## Prioridade 2 — melhorar descoberta de campanhas

Se o scanner por produto funcionar bem, evoluir para descoberta de campanhas globais do ML, evitando abrir vários anúncios quando o mesmo código serve para muitos produtos.

No AliExpress, manter `promotions.json` como catálogo validado e só automatizar campanhas quando existir fonte confiável para código, mínimo, validade e condição.

## Prioridade 3 — tracking público

Publicar `/go/{deal_id}` em HTTPS público. Depois medir cliques por:

- fonte;
- categoria;
- faixa de preço;
- cupom vs sem cupom;
- oferta nova vs price-drop/revival.

Não mexer automaticamente nos pesos do score até existir volume de dados suficiente.

## Concluído — Shopee

Ciclo comercial real implementado (API oficial de Afiliados, GraphQL). Falta apenas validar com credenciais reais em `--dry-run` após rotacionar `SHOPEE_APP_SECRET`.

## Prioridade 5 — SQLite

Depois que ML V1.1 estiver estável, migrar estados persistentes de JSON para SQLite: seen, histórico, deals publicados, promo cache/state, analytics, alertas e cliques.

## O que NÃO fazer agora

- não adicionar várias lojas novas;
- não reduzir `SCORE_MIN` no escuro;
- não remover guardrails do fallback;
- não tratar desconto condicional como garantido;
- não raspar centenas de páginas ML a cada ciclo;
- não deixar produto já visto ser republicado só porque o texto do cupom mudou;
- não versionar segredos, perfil do Chrome ou logs operacionais.
- não ativar Kabum no ciclo principal sem validar fonte, afiliação e testes (Shopee já validado por testes e ativo).

## Próximo checkpoint

Depois da primeira rodada real com V1.1, comparar o novo funil ML com o antigo:

```text
antes: muitos produtos fortes → 0 candidatos
agora: sinais fortes → fallback/strict/revival → ranking → selecionados
```

A próxima mudança deve ser guiada pelo log real dessa execução.
