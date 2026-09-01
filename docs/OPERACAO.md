# Operação — K4binho Promo Bot

Atualizado em **2026-09-01**.

## Inicialização

1. Mantenha `.env` somente no computador de operação.
2. Instale dependências com `pip install -r requirements.txt`.
3. Faça login do Mercado Livre com `python login_ml.py` quando a sessão expirar.
4. Rode `python -m pytest -q` antes de colocar uma atualização importante em produção.
5. Inicie pelo script operacional já usado no Windows (`reiniciar_bot.bat`/`run_bot.bat`) ou diretamente com Python.

## Promotion Engine V1.1

Configurações principais:

```env
ML_COUPON_DISCOVERY_ENABLED=true
ML_COUPON_SCAN_ITEMS=16
ML_COUPON_CACHE_HOURS=6
ML_COUPON_POSITIVE_CACHE_HOURS=2
ML_PROMO_REVIVAL_COOLDOWN_HOURS=6
ML_PROMO_REVIVAL_MIN_DROP_PERCENT=5
ML_PROMO_REVIVAL_MIN_DROP_AMOUNT=20
```

Os valores acima possuem defaults no código. O `.env` antigo continua funcionando sem obrigação de adicionar essas linhas imediatamente.

### Scanner ML

O scanner prioriza anúncios com sinais comerciais e tenta expandir elementos relacionados a cupom, benefício, desconto ou resgate. Ele não deve clicar em comprar, carrinho, checkout ou pagamento.

Itens já vistos podem ser reescaneados depois que o cache expira. Isso não significa republicação automática: para voltar ao canal por promoção, é necessária uma nova assinatura de benefício, queda relevante no preço efetivo e respeito ao cooldown.

## Como ler o log do ML

Resumo esperado:

```text
[ML] Encontrados: ...
Preco OK: ...
Historico pronto: ...
Sinal comercial forte: ...
Ja vistos: ...
Promocao: ...
Codigos: ...
Promo scan elegiveis: ...
Promo cache: ...
Scaneados: ...
Promo encontradas: ...
Vistos reescaneados: ...
Aprovados estritos: ...
Fallback comercial: ...
Reativados por promocao: ...
Candidatos: ...
Selecionados: ...
```

Diagnóstico por item:

```text
[ML][promo-scan]
[ML][promo-revival]
[ML][fallback-comercial]
[ML][cupom...]
[ML][price-drop]
```

Se `Promo scan elegiveis` for alto e `Scaneados` ficar no limite configurado, o motor está respeitando o orçamento de navegação. Não aumente o limite sem observar o tempo do Chrome.

## Fallback comercial

O fallback V1.1 não exige histórico incompleto. Ele precisa de:

- evidência real de preço;
- sinais comerciais suficientes;
- qualidade mínima;
- conversão mínima;
- confiança mínima;
- produto ainda não publicado, salvo lógica separada de price-drop/revival.

Isso evita o comportamento antigo em que quase todo o catálogo tinha histórico pronto e, por isso, o fallback nunca funcionava.

## Histórico e promoção

`price_history.json` continua recebendo o preço público listado. Cupons temporários não alteram a série histórica base.

`deal_store.json` registra o preço efetivo usado na última publicação e, quando houver, uma assinatura da promoção garantida para detectar oportunidades futuras.

## Validação após atualização

A suíte automatizada atual possui:

```text
114 passed
```

Além da suíte anterior, há testes para fallback, sinais, cache positivo, revival e segurança do scanner interativo.

## Segurança

Nunca envie ao GitHub ou compartilhe publicamente:

- `.env`;
- `ml_token.json`;
- `ml_profile/`;
- `bot.log` bruto;
- tokens/chaves de API;
- arquivos de estado operacional.

Use `export_project.py` para criar export sanitizado. Se uma credencial aparecer em log compartilhado, considere-a exposta e rotacione-a.

## Click tracking

O tracking permanece desabilitado por padrão. `CLICK_BASE_URL=http://localhost:8321` serve apenas para teste local; usuários do Telegram precisam de endpoint HTTPS público para o redirect funcionar fora do computador do bot.
