# Roadmap — K4binho Promo Bot

Atualizado em **2026-09-01**.

## Status atual

O projeto está na fase de **curadoria comercial + inteligência promocional**.

### ✅ Consolidado

- Mercado Livre com scraper, highlights, trending e best seller.
- Links afiliados ML via sessão persistente do Chrome.
- AliExpress via API afiliada.
- Steam com reviews oficiais, ITAD, waitlist, historical low e bundles/packages.
- Nuuvem e GMG como conteúdo PLUS/editorial.
- Histórico de preço, scoring multidimensional e diversidade por categoria.
- Alertas, digest diário, analytics e click tracking opcional.
- Promotion Engine com preço listado, preço garantido e preço potencial.
- Export sanitizado e proteção de segredos em logs.
- CI com suíte completa de testes.

## Promotion Engine V1.1

### ✅ Implementado e coberto por testes

- fallback comercial ML não depende mais de histórico incompleto;
- fallback usa sinais independentes e guardrails mínimos de qualidade, conversão e confiança;
- rating alto isolado não é suficiente para classificar um produto como forte;
- scanner de cupons abre controles promocionais de forma defensiva;
- scanner bloqueia ações de compra, carrinho, checkout e pagamento;
- produtos já vistos voltam a ser escaneados quando o cache expira;
- cache positivo de promoção pode expirar antes do cache vazio;
- promoção nova pode reativar item já publicado quando produz queda real de preço efetivo;
- revival possui cooldown e limite mínimo de ganho;
- histórico continua registrando o preço público listado, não o preço temporário de cupom;
- diagnóstico ML agora separa elegíveis, cache, scans, promoções encontradas e revivals.

### 🧪 Aguardando validação ao vivo

O código e a suíte automatizada estão verdes, mas a descoberta real depende da interface e da sessão atual do Mercado Livre. Precisamos observar ciclos reais e confirmar:

- taxa de acerto do scanner interativo;
- códigos como `VANTAGEMJA`/`OPORTUNIDADE` quando realmente visíveis;
- impacto do aumento de 8 para 16 scans prioritários por ciclo;
- quantidade e qualidade das ofertas liberadas pelo fallback;
- quantidade de revivals por promoção sem gerar spam.

## Próximas prioridades

### P0 — validar ML V1.1 em produção local

Observar no log:

```text
[ML][promo-scan]
[ML][promo-revival]
[ML][fallback-comercial]
[ML][cupom...]
```

E o resumo:

```text
Promo scan elegiveis
Promo cache
Scaneados
Promo encontradas
Vistos reescaneados
Fallback comercial
Reativados por promocao
Selecionados
```

### P1 — AliExpress Campaign Discovery

O motor já aceita catálogo de cupons e escolhe a melhor regra aplicável. Falta uma fonte confiável/operacional para atualizar campanhas automaticamente.

### P1 — click tracking público

O redirect existe, mas `localhost` não serve usuários do Telegram. Publicar endpoint HTTPS antes de usar cliques como sinal de otimização.

### P1 — Shopee

Estrutura promocional preparada, mas integração comercial real continua pendente de fonte/API/credenciais adequadas.

### P2 — SQLite

Migrar gradualmente estados JSON depois de estabilizar a lógica comercial.

### P2 — health check real

Evoluir `/status` para incluir último ciclo por fonte, erros recentes, sessão ML, último cupom e saúde do redirect.

## Regras de produto

- ML/Ali são fontes comerciais e merecem prioridade de conversão.
- Steam/Nuuvem/GMG continuam como PLUS/editorial.
- Cupom só altera score garantido quando a condição é confiável.
- Benefício condicionado a app, moedas ou usuários selecionados não deve ser anunciado como universal.
- Produto visto pode voltar apenas diante de nova oportunidade relevante, respeitando cooldown.
- Não aumentar volume só para preencher canal.
- Não automatizar pesos de scoring sem dados reais de comportamento/conversão.

## Estado dos testes

```text
114 passed
```

A validação automatizada cobre a suíte anterior e os guardrails novos da V1.1.

## Segurança

Nunca versionar ou compartilhar `.env`, `ml_token.json`, `ml_profile/`, logs com credenciais ou estados operacionais. O `.gitignore` e o exporter sanitizado devem continuar sendo usados.
