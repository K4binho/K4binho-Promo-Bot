========== PROJECT CHECKPOINT ==========
Projeto: K4binho-Promo-Bot
Tarefa: Evolução Operacional v1.3 (feat/operational-hardening-v1-3)

STATUS: [x] Em andamento (Fases 1-6 concluídas, Fases 7-9 pendentes)

CONCLUÍDO:
- Fase 1 (bf2a798): orchestrator.py, ctx.lock, 7 fontes concorrentes.
- Fase 2 (e71e75f): telegram/client.py resiliente, fix HTML injection.
- Fase 3 (39fc1bc): listener.py (long polling), commands/hunt.py (/buscar).
- Fase 4 (3d1a11b): deal_store + should_republish() nas 6 fontes não-ML.
- Fase 5 (8c68387): storage/atomic.py — escrita atômica em todo JSON
  operacional, K4PROMO_DATA_DIR auto-criado, checagem de permissão no boot.
- Fase 6 (c5d8304): services/link_validation.py — só bloqueia link
  CONFIRMADO morto (404/410); timeout/DNS/5xx são inconclusivos e NÃO
  bloqueiam (a rede é instável, prefere publicar a perder oferta boa por
  falha passageira). 405 no HEAD tenta GET antes de decidir. Cache de 5min
  (configurável) evita revalidar o mesmo link no mesmo ciclo. Integrado em
  Publisher.publish() — vale pra TODAS as fontes (6 cycles + ML) automati-
  camente, sem precisar tocar em cada cycle (diferente da Fase 4). Rodado
  DE PROPÓSITO fora do ctx.lock (é rede, não pode travar as outras fontes
  esperando resposta). Imagem quebrada não ganhou checagem própria — o
  fallback de foto->texto do cliente Telegram (Fase 2) já cobre isso.
  Criado tests/conftest.py com fixture autouse que mocka httpx.head globa-
  lmente (2xx) pra suíte inteira não depender de rede real por causa dessa
  integração nova — testes de link_validation sobrescrevem localmente.
  13 testes novos. Suíte: 298/298. compileall/ruff limpos.
  .env.example: LINK_VALIDATION_TIMEOUT_SECONDS, LINK_VALIDATION_CACHE_TTL_SECONDS.

PRÓXIMA AÇÃO (Fase 7 — Digest e analytics, seções 21-23):
- Corrigir links vazios no digest (hoje "link": "" nalguns itens) — usar o
  link de tracking/afiliado final.
- APP_TIMEZONE=America/Manaus via zoneinfo.ZoneInfo: analytics continua em
  UTC, digest/status/vitrine convertem pro fuso configurado na exibição.
  Não comparar data local direto com prefixo de timestamp UTC.
  digest.run() já recebe `last_digest_date` em main.py — conferir se a
  comparação de "virou o dia" já usa timezone-aware corretamente ou se
  precisa da correção aqui.
- Analytics: adicionar tópico, categoria, link de tracking, message_id
  (disponível desde a Fase 2), preço listado/efetivo/original, desconto,
  cupom, score final, motivo de publicação/republicação (disponível desde
  a Fase 4 como "action" em analytics_kwargs — conferir se já está sendo
  gravado ou só passado e descartado), comissão, horário, resultado do
  envio.
- Digest deve priorizar final_score, usando quality_score só como critério
  secundário — conferir services/digest.py atual.

ARQUIVOS (Fase 6, novos/modificados):
- Novos: src/k4promo/services/link_validation.py, tests/test_link_validation.py,
  tests/conftest.py
- Modificados: src/k4promo/services/publisher.py, .env.example
(lista completa das Fases 1-5 nos commits/mensagens anteriores)

GIT: branch feat/operational-hardening-v1-3, 7 commits locais (bf2a798,
e71e75f, 39fc1bc, 3d1a11b, 4c5ae53, 8c68387, 05e7801 [checkpoint], c5d8304),
base main@df1fcc3. Não enviada ao GitHub (sem credenciais de push).

TESTES: 298/298 passando. compileall OK. ruff OK (só o BLE001 intencional
de sempre em publisher.py).

PROBLEMAS: nenhum bloqueio técnico.

DECISÕES (Fase 6):
- Validação roda fora do ctx.lock — decisão importante de performance:
  dentro do lock, uma checagem de rede lenta travaria TODAS as fontes
  concorrentes (Fase 1) esperando ela terminar. Só a decisão "publica ou
  não" acontece antes do lock; nada de rede acontece DENTRO da seção
  protegida.
- Não criei checagem separada pra imagem — spec pede isso explicitamente
  ("deixar o cliente Telegram fazer a tentativa e usar o fallback"), então
  o comportamento já existente da Fase 2 é o comportamento correto, não um
  atalho.
- tests/conftest.py foi necessário porque a integração em Publisher.publish()
  passou a chamar link_validation em TODO publish(), incluindo dezenas de
  testes já existentes (Fases 1-5) que não mockavam httpx.head — em vez de
  editar cada um, um fixture autouse global resolve pra suíte inteira de
  uma vez.

CONTEXTO CRÍTICO:
- Ambiente efêmero: /home/claude/repo não persiste entre conversas. Ao
  retomar: re-clonar o repo, `git log` pra achar os 7-8 commits locais (se
  sumiram, os zips já entregues ao usuário são a fonte da verdade) e seguir
  da Fase 7.
- Usuário pede continuação direta a cada fase ("Continuar"), sem revisão
  intermediária.
- Zip de entrega deve ser cumulativo único (git diff --name-only df1fcc3
  HEAD), não um por fase.
==========================================
