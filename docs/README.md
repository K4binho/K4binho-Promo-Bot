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

### Comerciais (com comissão)

- Mercado Livre — prioridade comercial, links afiliados e descoberta de promoções.
- Shopee — Open API GraphQL de afiliados (`providers/shopee.py`).
- AliExpress — API afiliada e suporte a catálogo de campanhas/códigos.
- KaBuM! — API pública de catálogo + link afiliado Awin (`providers/kabum.py`).
- Green Man Gaming — via **impact.com** (`providers/gmg.py`; não é CJ Affiliate).

### Editoriais (PLUS)

- Steam
- Nuuvem

Essas fontes ajudam aquisição e retenção e não devem ser tratadas como equivalentes comerciais.

## Tópicos do Telegram

As publicações são distribuídas em sete tópicos do fórum (Melhores do Dia, Jogos, Tecnologia, Casa & Cozinha, Moda & Beleza, Ferramentas & Auto, Achadinhos) segundo a prioridade de lojas definida em `domain/topics.py`. "Melhores do Dia" é uma vitrine sem coleta própria. Detalhes em `TOPICOS.md`.

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
195 passed
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

Não publique tokens, segredos, perfil persistente do Chrome, logs brutos nem arquivos de estado. Use `python scripts/export_project.py` para exportar o projeto de forma sanitizada.

## Próximo passo

A distribuição por tópicos, a vitrine e os ciclos Shopee/KaBuM estão implementados e cobertos por testes, mas precisam de validação ao vivo (respostas reais das APIs e acerto do classificador de título). A V1.1 do ML também segue aguardando observação de ciclos reais.

## Código

O bot é o pacote `k4promo`, em `src/`. O `bot.py` da raiz é só um lançador, para
os atalhos do Windows seguirem funcionando. A organização por camadas está em
`ARQUITETURA.md`.

Consulte também:

- `ARQUITETURA.md`
- `TOPICOS.md`
- `ROADMAP.md`
- `ProximosPasso.md`
- `OPERACAO.md`
- `prompt_mestre.md`
