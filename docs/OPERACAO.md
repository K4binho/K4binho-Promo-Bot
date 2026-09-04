# Operação — K4binho Promo Bot

Atualizado em **2026-09-03**.

## Tópicos e vitrine

Cada oferta é publicada no tópico do fórum decidido por `services/router.py` (ver `TOPICOS.md`). Variáveis:

```env
TELEGRAM_TOPIC_MELHORES_DO_DIA=2194
TELEGRAM_TOPIC_JOGOS=2195
TELEGRAM_TOPIC_TECNOLOGIA=2197
TELEGRAM_TOPIC_CASA_COZINHA=2198
TELEGRAM_TOPIC_MODA_BELEZA=2201
TELEGRAM_TOPIC_FERRAMENTAS_AUTO=2202
TELEGRAM_TOPIC_ACHADINHOS=2205
MELHORES_DO_DIA_MAX_PER_CYCLE=2
MELHORES_DO_DIA_MAX_PER_DAY=8
```

`TELEGRAM_STEAM_THREAD_ID`, `TELEGRAM_GMG_THREAD_ID`, `TELEGRAM_ALIEXPRESS_THREAD_ID` e `TELEGRAM_NUUVEM_THREAD_ID` não são mais lidos. Um tópico com valor `0` cai em `TELEGRAM_THREAD_ID`.

A vitrine grava `showcase_state.json` (não versionar). Para reiniciar a memória de cópias, apague o arquivo.

## Shopee, KaBuM e Impact

- Shopee precisa de `SHOPEE_APP_ID`/`SHOPEE_APP_SECRET` e `SHOPEE_SEARCHES`.
- KaBuM precisa de `KABUM_AWIN_TOKEN`/`KABUM_PUBLISHER_ID`; sem link afiliado a oferta não sai.
- GMG usa `IMPACT_ACCOUNT_SID`/`IMPACT_AUTH_TOKEN` (impact.com). `CJ_*` são aliases legados.
- Qualquer um sem credencial é pulado em silêncio.

## Inicialização

1. Mantenha `.env` somente no computador de operação.
2. Instale dependências com `pip install -r requirements.txt` (ou `pip install -e .` para desenvolvimento).
3. Faça login do Mercado Livre com `python scripts/login_ml.py` quando a sessão expirar.
4. Rode `python -m pytest -q` antes de colocar uma atualização importante em produção.
5. Inicie pelo script operacional já usado no Windows (`reiniciar_bot.bat`/`run_bot.bat`) ou diretamente com Python.

## Estrutura do código

O bot virou o pacote `k4promo` em `src/`. `python bot.py` continua funcionando
(o arquivo da raiz é um lançador), assim como `run_bot.bat` e `reiniciar_bot.bat`.
Os arquivos de estado seguem na raiz do projeto. Detalhes em `ARQUITETURA.md`.

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
195 passed
```

Além da suíte anterior, há testes para fallback, sinais, cache positivo, revival, segurança do scanner interativo, classificação por tópico, roteamento, vitrine, Shopee, KaBuM e aliases de config.

## Segurança

Nunca envie ao GitHub ou compartilhe publicamente:

- `.env`;
- `ml_token.json`;
- `ml_profile/`;
- `bot.log` bruto;
- tokens/chaves de API (Telegram, Impact, Shopee, Awin, AliExpress, ITAD);
- arquivos de estado operacional (`seen.json`, `showcase_state.json`, etc.).

Use `python scripts/export_project.py` para criar export sanitizado. Se uma credencial aparecer em log compartilhado, considere-a exposta e rotacione-a.

## Click tracking

O tracking permanece desabilitado por padrão. `CLICK_BASE_URL=http://localhost:8321` serve apenas para teste local; usuários do Telegram precisam de endpoint HTTPS público para o redirect funcionar fora do computador do bot.
