# Prompt Mestre — K4binho Promo Bot

Atualizado em **2026-09-03**.

Use este documento para retomar o projeto sem depender do histórico de uma conversa.

## Regra principal

O código atual, os testes, os arquivos em `docs/` e o log real são a fonte de verdade. Antes de alterar comportamento, leia a implementação existente e preserve o que já funciona.

## Objetivo do produto

O K4binho Promo Bot é um motor de curadoria de ofertas para Telegram.

Objetivos:

1. encontrar oportunidades realmente boas;
2. manter confiança e retenção no canal;
3. priorizar fontes comerciais sem virar spam;
4. aumentar cliques/compras com dados reais;
5. aprender com analytics somente quando houver amostra suficiente.

## Prioridade das fontes

- Mercado Livre, Shopee, AliExpress, KaBuM: comerciais (comissão).
- Green Man Gaming: comercial via impact.com (não é CJ Affiliate; `providers/gmg.py`).
- Steam/Nuuvem: PLUS/editorial, fortalecem o tópico Jogos.

Não remova PLUS só porque não monetiza diretamente.

## Tópicos do Telegram

Sete tópicos do fórum, IDs em `TELEGRAM_TOPIC_*`, prioridade de lojas em `domain/topics.py` (ver `TOPICOS.md`). Regras fixas:

- lojas de jogos só em Jogos; lojas físicas nunca em Jogos;
- Melhores do Dia é vitrine: sem coleta própria, só cópias com critério;
- loja fora da lista do tópico cai em Achadinhos;
- KaBuM normalmente não publica em Moda & Beleza.

## Arquitetura

```text
Sources
→ Normalização
→ Price History
→ Promotion Engine
→ Scoring multidimensional
→ Ranking/diversidade
→ Router (tópico)
→ Publisher
→ Vitrine
→ Tracking
→ Analytics
```

O código é o pacote `k4promo` em `src/`; `bot.py` na raiz é só lançador.
A divisão por camadas e o que cada pasta responde estão em `ARQUITETURA.md`.
Não volte a concentrar ciclo, publicação e duplicação em um arquivo só.

## Estado atual — Promotion Engine V1.1

### ✅ Implementado

- preço listado separado de preço efetivo garantido/potencial;
- desconto condicional não entra no score como garantido;
- fallback ML não depende de histórico incompleto;
- fallback exige preço + sinais independentes + guardrails de qualidade/conversão/confiança;
- rating alto sozinho não classifica produto como forte;
- scanner ML expande elementos seguros relacionados a cupom/benefício/desconto;
- scanner não deve clicar em compra, carrinho, checkout ou pagamento;
- seen não impede reescaneamento após expiração do cache;
- cache positivo de promoção pode ter TTL menor;
- produto visto pode voltar por nova promoção + queda relevante + cooldown;
- histórico de preço armazena preço listado, não cupom temporário;
- logs do funil ML possuem diagnóstico de scan/cache/fallback/revival;
- distribuição por tópicos + vitrine + Shopee/KaBuM (2026-09-03);
- CI e suíte completa: 195 testes passando.

### 🧪 Precisa validação real

- taxa de descoberta de cupons na UI atual do Mercado Livre;
- códigos e valores reais exibidos para a conta logada;
- qualidade dos produtos liberados pelo fallback;
- comportamento do revival em ciclos reais;
- custo de abrir 16 anúncios prioritários por ciclo.

## Regras para futuras mudanças

- Não baixar filtros globalmente só para publicar mais.
- Não usar histórico como bloqueio absoluto de oportunidade comercial.
- Não republicar item visto apenas porque o texto da página mudou.
- Não contaminar histórico base com preço temporário de cupom.
- Não anunciar condição personalizada como preço universal.
- Não adicionar lojas além das sete mapeadas nos tópicos antes de estabilizar medição de cliques/conversões.
- Não dar coleta própria a Melhores do Dia nem publicar loja fora da prioridade do tópico.
- Mudança nova precisa de teste de regressão.
- Atualize `README.md`, `ROADMAP.md`, `OPERACAO.md`, `ProximosPasso.md`, `TOPICOS.md` e `ARQUITETURA.md` quando o estado real mudar.

## Diagnóstico esperado

Observe principalmente:

```text
[ML][promo-scan]
[ML][promo-revival]
[ML][fallback-comercial]
[ML][cupom...]
```

Resumo do ML deve permitir enxergar encontrados → preço OK → sinais → promo scan/cache → strict/fallback/revival → candidatos → selecionados.

## Segurança

Nunca exponha `.env`, token Telegram, chaves de API, `ml_token.json`, `ml_profile/` ou logs com credenciais. `httpx/httpcore` não devem imprimir URLs sensíveis em INFO. Use export sanitizado.

## Próximas prioridades

0. validar distribuição por tópicos, vitrine, Shopee e KaBuM ao vivo;
1. validar ML V1.1 ao vivo;
2. melhorar descoberta global de campanhas quando houver dados;
3. publicar click tracking em HTTPS;
4. medir cliques por fonte/categoria/promoção;
5. só então ajustar scoring com comportamento real;
6. SQLite depois da estabilização comercial;
7. Shopee quando houver integração verdadeira.
