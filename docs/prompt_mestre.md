# Prompt Mestre — K4binho Promo Bot

Atualizado em **2026-09-01**.

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

- Mercado Livre: comercial e prioridade alta.
- AliExpress: comercial.
- Steam/Nuuvem/GMG: PLUS/editorial.
- Shopee: integração real ainda pendente; não fingir suporte completo.

Não remova PLUS só porque não monetiza diretamente.

## Arquitetura

```text
Sources
→ Normalização
→ Price History
→ Promotion Engine
→ Scoring multidimensional
→ Ranking/diversidade
→ Scheduler
→ Telegram
→ Tracking
→ Analytics
```

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
- CI e suíte completa: 114 testes passando.

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
- Não adicionar lojas antes de estabilizar medição de cliques/conversões.
- Mudança nova precisa de teste de regressão.
- Atualize `README.md`, `ROADMAP.md`, `OPERACAO.md` e `ProximosPasso.md` quando o estado real mudar.

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

1. validar ML V1.1 ao vivo;
2. melhorar descoberta global de campanhas quando houver dados;
3. publicar click tracking em HTTPS;
4. medir cliques por fonte/categoria/promoção;
5. só então ajustar scoring com comportamento real;
6. SQLite depois da estabilização comercial;
7. Shopee quando houver integração verdadeira.
