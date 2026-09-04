# Roadmap — K4binho Promo Bot

Atualizado em **2026-09-03**.

## Status atual

O projeto está na fase de **curadoria comercial + inteligência promocional + distribuição por tópicos**.

### ✅ Consolidado

- Mercado Livre com scraper, highlights, trending e best seller.
- Links afiliados ML via sessão persistente do Chrome.
- AliExpress via API afiliada.
- Steam com reviews oficiais, ITAD, waitlist, historical low e bundles/packages.
- Nuuvem como conteúdo editorial; GMG como fonte com comissão via impact.com.
- Distribuição por tópicos do fórum (`domain/topics.py`) com prioridade de lojas por tópico.
- Vitrine "Melhores do Dia" sem coleta própria (cópias das melhores publicações).
- Ciclos Shopee (GraphQL afiliados) e KaBuM (Awin) ligados ao bot, gated por credenciais.
- Código reorganizado no pacote `k4promo` (`src/`), com `bot.py` reduzido a lançador.
- Modelo único de oferta (`domain/models.py` + `providers/adapters.py`) usado por todos os ciclos.
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

## Distribuição por tópicos (2026-09-03)

### ✅ Implementado e coberto por testes

- sete tópicos com IDs configuráveis (`TELEGRAM_TOPIC_*`), defaults do grupo;
- `STORE_TOPIC_PRIORITY` igual ao mapeamento acordado;
- classificador de título por palavras-chave ponderadas;
- lojas de jogos só em Jogos; lojas físicas nunca em Jogos; loja fora da lista cai em Achadinhos;
- vitrine Melhores do Dia com critérios, prioridade de loja, limites por ciclo/dia e memória de 7 dias;
- Shopee e KaBuM com roteamento por tópico e link afiliado obrigatório;
- GMG identificado internamente como Impact (`providers/gmg.py`), `CJ_*` como alias.

### 🧪 Aguardando validação ao vivo

- resposta real da `productOfferV2` (Shopee) e do link builder Awin (KaBuM);
- taxa de produtos que caem em Achadinhos por falta de palavra-chave;
- volume de cópias da vitrine por dia (evitar duplicar o canal inteiro).

## Próximas prioridades

### P0 — validar tópicos, Shopee e KaBuM ao vivo

Rodar `python bot.py --dry-run --once`, conferir `[Shopee]`, `[Kabum]`, `[Vitrine]` e o tópico impresso por oferta. Depois um ciclo real e checar se cada publicação caiu no tópico certo.

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

### P1 — afinar palavras-chave dos tópicos

Observar títulos que caírem em Achadinhos sem motivo e ampliar `services/categorizer.py`. Ampliar `ALIEXPRESS_SEARCHES` para Casa/Moda quando a Shopee não cobrir sozinha.

### P2 — SQLite

Migrar gradualmente estados JSON depois de estabilizar a lógica comercial. Agora a troca acontece atrás de `storage/`, sem tocar nos ciclos.

### P2 — health check real

Evoluir `/status` para incluir último ciclo por fonte, erros recentes, sessão ML, último cupom e saúde do redirect.

## Regras de produto

- ML/Shopee/Ali/KaBuM/GMG são fontes com comissão e merecem prioridade de conversão.
- Steam/Nuuvem continuam como PLUS/editorial e só entram na vitrine com forte valor editorial.
- Melhores do Dia nunca coleta; só copia o que já foi publicado em outro tópico.
- Cupom só altera score garantido quando a condição é confiável.
- Benefício condicionado a app, moedas ou usuários selecionados não deve ser anunciado como universal.
- Produto visto pode voltar apenas diante de nova oportunidade relevante, respeitando cooldown.
- Não aumentar volume só para preencher canal.
- Não automatizar pesos de scoring sem dados reais de comportamento/conversão.

## Estado dos testes

```text
195 passed
```

A validação automatizada cobre a suíte anterior, os guardrails da V1.1 e a distribuição por tópicos (classificador, roteamento, vitrine, Shopee, KaBuM, config).

## Segurança

Nunca versionar ou compartilhar `.env`, `ml_token.json`, `ml_profile/`, logs com credenciais ou estados operacionais. O `.gitignore` e o exporter sanitizado devem continuar sendo usados.
