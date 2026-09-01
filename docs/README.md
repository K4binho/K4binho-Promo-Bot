# K4binho Promo Bot

Bot de curadoria de ofertas para Telegram com fontes comerciais e conteúdo PLUS/editorial.

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
114 passed
```

O GitHub Actions executa validação de sintaxe e a suíte completa em pushes/PRs.

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

- `ROADMAP.md`
- `ProximosPasso.md`
- `OPERACAO.md`
- `prompt_mestre.md`
