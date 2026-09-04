# Próximos Passos — K4binho Promo Bot

Atualizado em **2026-09-03**.

## Onde estamos

O código foi reorganizado no pacote `k4promo` (`src/`), com um ciclo por arquivo
e a mecânica de publicação compartilhada. Ver `ARQUITETURA.md`.

O canal virou um fórum com sete tópicos e o bot passou a distribuir cada oferta pelo tópico certo, com uma vitrine "Melhores do Dia" alimentada por cópias. Shopee e KaBuM entraram como fontes com comissão. Detalhes em `TOPICOS.md`.

## Prioridade 0 — validar a distribuição ao vivo

1. `python bot.py --dry-run --once` e conferir `[Shopee]`, `[Kabum]`, `[GMG]`, `[Vitrine]`.
2. Um ciclo real com `--once` e checar no Telegram se cada publicação caiu no tópico esperado.
3. Anotar títulos que caíram em Achadinhos indevidamente e ampliar `services/categorizer.py`.
4. Confirmar que a vitrine não passou de `MELHORES_DO_DIA_MAX_PER_DAY`.

## Prioridade 1 (ML) — fazer o Mercado Livre converter melhor sem perder qualidade

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
- suíte completa: **181 testes passando**.

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

## Prioridade 4 — Shopee e KaBuM em regime

Os ciclos existem e são gated por credenciais. Validar contra a resposta real da API antes de subir `SHOPEE_MAX_POSTS_PER_CYCLE`/`KABUM_MAX_POSTS_PER_CYCLE`.

## Prioridade 5 — SQLite

Depois que ML V1.1 estiver estável, migrar estados persistentes de JSON para SQLite: seen, histórico, deals publicados, promo cache/state, analytics, alertas, cliques e vitrine.

## O que NÃO fazer agora

- não adicionar lojas além das sete já mapeadas nos tópicos;
- não dar coleta própria ao tópico Melhores do Dia;
- não publicar produto físico em Jogos nem jogo fora de Jogos;
- não reduzir `SCORE_MIN` no escuro;
- não remover guardrails do fallback;
- não tratar desconto condicional como garantido;
- não raspar centenas de páginas ML a cada ciclo;
- não deixar produto já visto ser republicado só porque o texto do cupom mudou;
- não versionar segredos, perfil do Chrome ou logs operacionais;
- não voltar a concentrar ciclos, publicação e duplicação em um arquivo só.

## Próximo checkpoint

Depois da primeira rodada real com V1.1, comparar o novo funil ML com o antigo:

```text
antes: muitos produtos fortes → 0 candidatos
agora: sinais fortes → fallback/strict/revival → ranking → selecionados
```

A próxima mudança deve ser guiada pelo log real dessa execução.
