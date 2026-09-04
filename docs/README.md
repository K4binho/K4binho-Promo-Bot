# K4binho Promo Bot

Bot de curadoria de ofertas para Telegram com fontes comerciais e conteúdo PLUS/editorial.

Este é o guia técnico. Para instalação rápida, comece pelo [`README.md` da raiz](../README.md).

## Objetivo

O sistema não busca apenas o maior percentual de desconto. Ele combina preço, histórico, qualidade, demanda, conversão, retenção e confiança para selecionar oportunidades úteis ao usuário e sustentáveis para o negócio.

Fluxo principal:

```text
fontes
→ normalização
→ histórico de preço
→ Promotion Engine
→ scoring multidimensional
→ ranking/diversidade
→ Telegram
→ tracking/analytics
```

## Fontes

### Comerciais

- Mercado Livre — prioridade comercial, links afiliados e descoberta de promoções.
- AliExpress — API afiliada e suporte a catálogo de campanhas/códigos.

### PLUS / editorial

- Steam
- Nuuvem
- Green Man Gaming

Essas fontes ajudam aquisição e retenção e não devem ser tratadas como equivalentes comerciais ao ML/Ali.

### Comerciais (novos)

- Shopee — API de Afiliados oficial (GraphQL), produtos + cupons de campanha + deeplink; participa do ciclo principal via `run_shopee_cycle` e valida o link antes de publicar.

### Integração ajustada

- Green Man Gaming (GMG) — cupons agora passam pelo motor unificado (`promotion_engine.py`), com escopo produto/loja/plataforma e filtro de confiança, igual às demais fontes.

### Preparada, mas não ativa

- Kabum possui scraper e geração de link, porém não é chamada pelo orquestrador atual.

## Componentes principais

| Componente | Responsabilidade |
| --- | --- |
| `bot.py` | Orquestra os ciclos, seleção, publicação, digest e persistência. |
| `config.py` | Carrega o `.env`, aplica defaults e valida Telegram. |
| `scoring.py` | Calcula qualidade, conversão, retenção, confiança e score final. |
| `promotion_engine.py` | Avalia cupons/campanhas, preço garantido ou potencial e caches. |
| `ml_playwright.py` | Mantém a sessão do ML, descobre promoções e gera links afiliados. Roda com Chrome "de verdade" mas fora da área visível do monitor (`offscreen`), evitando roubar foco e o throttling de aba em segundo plano. |
| `telegram.py` | Formata e envia mensagens. |
| `bot_commands.py` | Processa `/start`, alertas e `/status`; comandos administrativos são protegidos. |
| `*_store.py` e `price_history.py` | Persistem estado local em JSON/JSONL. |
| `click_server.py` e `click_tracker.py` | Redirect opcional e métricas de clique. |
| `link_validation.py` | Checagem de rede na hora de publicar (404/410 bloqueia; falha ambígua não bloqueia). |
| `migrate_promotion_cache.py` | Script de migração pontual do cache de promoções para o formato atual. |

O processo usa a porta local `47591` como trava de instância única. Uma segunda
execução encerra sem iniciar outro ciclo.

## Promotion Engine V1.1

O Mercado Livre agora possui:

- scanner promocional com interação defensiva em elementos de cupom/benefício;
- bloqueio explícito de ações de compra/carrinho/checkout;
- preço efetivo garantido separado de preço potencial/condicional;
- cache de scanner com TTL diferente para resultado positivo;
- reescaneamento de produtos já vistos quando o cache expira;
- revival de oferta quando surge promoção nova e queda real de preço efetivo;
- fallback comercial independente de histórico incompleto;
- guardrails de qualidade, conversão e confiança;
- diagnóstico detalhado no log.

O histórico de preço continua usando o preço público listado para não contaminar a série com cupons temporários.

## Testes

A suíte automatizada atual possui:

```text
188 passed
```

O GitHub Actions executa validação de sintaxe e a suíte completa em pushes/PRs.

Execução local recomendada:

```powershell
python -m pytest -q
python bot.py --dry-run  # um ciclo sem publicar
python bot.py --once     # um ciclo com publicação
python bot.py            # execução contínua
```

## Configuração

Copie `.env.example` para `.env` e preencha somente no ambiente local. O `.env` real nunca deve ser versionado.

Novos parâmetros da V1.1 possuem valores padrão no código, incluindo:

```env
ML_COUPON_SCAN_ITEMS=16
ML_COUPON_CACHE_HOURS=6
ML_COUPON_POSITIVE_CACHE_HOURS=2
ML_PROMO_REVIVAL_COOLDOWN_HOURS=6
ML_PROMO_REVIVAL_MIN_DROP_PERCENT=5
ML_PROMO_REVIVAL_MIN_DROP_AMOUNT=20
```

## Segurança

Não publique tokens, segredos, perfil persistente do Chrome, logs brutos nem arquivos de estado. Use `export_project.py` para exportar o projeto de forma sanitizada.

## Próximo passo

A V1.1 está implementada e testada, mas a interação com a interface real do Mercado Livre precisa de validação ao vivo. O próximo checkpoint é observar alguns ciclos e comparar `promo-scan`, fallback, revivals e selecionados com o funil anterior.

Consulte também:

- [Roadmap](ROADMAP.md)
- [Próximos passos](ProximosPasso.md)
- [Operação](OPERACAO.md)
- [Prompt mestre](prompt_mestre.md)
