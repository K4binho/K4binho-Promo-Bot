# K4binho Promo Bot

Motor de curadoria de ofertas para Telegram. Coleta de sete lojas, pontua cada
oferta, escolhe o tópico do fórum e publica com link de afiliado.

## Rodar

```bash
python bot.py --dry-run --once
```

`--dry-run` mostra o funil sem publicar nada. `--once` roda um ciclo e sai. Sem
os dois, o bot fica em laço no intervalo de `POLL_INTERVAL_SECONDS`.

No Windows, `run_bot.bat` inicia em segundo plano e `reiniciar_bot.bat` reinicia.

## Configurar

Copie `.env.example` para `.env` e preencha. O `.env` real nunca vai para o
repositório.

## Testar

```bash
python -m pytest -q
```

## Estrutura

O código é o pacote `k4promo`, em `src/`. O `bot.py` da raiz é só um lançador.

| Pasta | Responsabilidade |
|---|---|
| `src/k4promo/providers/` | Acesso a cada loja |
| `src/k4promo/services/` | Score, roteamento, publicação, duplicação, vitrine |
| `src/k4promo/domain/` | Tópicos, lojas e modelo de oferta |
| `src/k4promo/telegram/` | Envio e formato das mensagens |
| `src/k4promo/storage/` | Estado persistente |
| `scripts/` | Login do Mercado Livre, setup do OAuth, export sanitizado |

## Documentação

- [`docs/README.md`](docs/README.md) — visão geral do produto
- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — como o código é organizado
- [`docs/TOPICOS.md`](docs/TOPICOS.md) — distribuição por tópico do Telegram
- [`docs/OPERACAO.md`](docs/OPERACAO.md) — operação do dia a dia
- [`docs/ROADMAP.md`](docs/ROADMAP.md) e [`docs/ProximosPasso.md`](docs/ProximosPasso.md) — o que vem a seguir
