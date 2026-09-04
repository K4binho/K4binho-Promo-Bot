"""Apaga mensagens antigas do bot nos topicos do canal.

Limite da Bot API: so da pra apagar mensagem com menos de 48h. Mensagens mais
antigas devolvem "message can't be deleted" e sao puladas.

Modos:
  --only-bot (padrao)  Antes de apagar, confirma a autoria via
                       editMessageReplyMarkup sem markup, que nao altera nada
                       visivel: mensagem do proprio bot responde
                       "message is not modified", de terceiro responde
                       "message can't be edited". Mensagem de humano fica.
  --all                Apaga a faixa inteira em lote (deleteMessages, 100 por
                       chamada). Muito mais rapido, mas apaga TAMBEM mensagem
                       de humano, porque o bot tem can_delete_messages.

Uso:
  python purge_topics.py --dry-run
  python purge_topics.py --only-bot --yes
  python purge_topics.py --all --yes
"""

import argparse
import os
import sys
import time

import httpx
from dotenv import load_dotenv

API = "https://api.telegram.org/bot{token}/{method}"


def call(token: str, method: str, payload: dict) -> tuple[bool, object, str]:
    """Retorna (ok, result, description). Trata 429 com o retry_after da API."""
    for _ in range(6):
        try:
            resp = httpx.post(API.format(token=token, method=method), json=payload, timeout=30)
        except httpx.HTTPError as exc:
            return False, None, f"http: {exc}"
        try:
            data = resp.json()
        except ValueError:
            return False, None, f"resposta invalida ({resp.status_code})"
        if data.get("ok"):
            return True, data.get("result"), ""
        desc = str(data.get("description", ""))
        if resp.status_code == 429:
            wait = int((data.get("parameters") or {}).get("retry_after", 5))
            time.sleep(wait + 1)
            continue
        return False, None, desc
    return False, None, "429 persistente"


def current_max_id(token: str, chat_id: str, thread_id: int | None) -> int:
    payload = {"chat_id": chat_id, "text": "."}
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    ok, result, desc = call(token, "sendMessage", payload)
    if not ok:
        sys.exit(f"nao deu pra descobrir o message_id atual: {desc}")
    mid = int(result["message_id"])
    call(token, "deleteMessage", {"chat_id": chat_id, "message_id": mid})
    return mid


def is_bot_message(token: str, chat_id: str, mid: int) -> bool:
    ok, _result, desc = call(
        token, "editMessageReplyMarkup", {"chat_id": chat_id, "message_id": mid}
    )
    if ok:
        return True
    return "not modified" in desc


def purge_only_bot(token: str, chat_id: str, start: int, end: int, dry_run: bool, pace: float) -> None:
    deleted = skipped_foreign = skipped_old = missing = 0
    for mid in range(start, end + 1):
        if not is_bot_message(token, chat_id, mid):
            skipped_foreign += 1
            time.sleep(pace)
            continue
        if dry_run:
            deleted += 1
            time.sleep(pace)
            continue
        ok, _result, desc = call(
            token, "deleteMessage", {"chat_id": chat_id, "message_id": mid}
        )
        if ok:
            deleted += 1
        elif "can't be deleted" in desc:
            skipped_old += 1
        else:
            missing += 1
        time.sleep(pace)
        if (mid - start) % 50 == 0:
            print(f"  ... {mid}/{end} | apagadas {deleted}", flush=True)
    verbo = "apagaria" if dry_run else "apagadas"
    print(f"{verbo}: {deleted} | de terceiros (mantidas): {skipped_foreign} "
          f"| >48h: {skipped_old} | inexistentes: {missing}")


def purge_all(token: str, chat_id: str, start: int, end: int, dry_run: bool) -> None:
    """Apaga em lote de 100, caindo pra 1-a-1 quando o lote e recusado.

    deleteMessages e tudo-ou-nada: um unico id nao-apagavel (>48h ou
    inexistente) faz o lote inteiro falhar sem apagar nada. Nesse caso o
    fallback individual salva os ids que ainda dao.
    """
    deleted = skipped = 0
    for base in range(start, end + 1, 100):
        batch = list(range(base, min(base + 100, end + 1)))
        if dry_run:
            deleted += len(batch)
            continue
        ok, _result, _desc = call(
            token, "deleteMessages", {"chat_id": chat_id, "message_ids": batch}
        )
        if ok:
            deleted += len(batch)
            print(f"  lote {batch[0]}..{batch[-1]}: {len(batch)} apagada(s)", flush=True)
            time.sleep(1.0)
            continue
        for mid in batch:
            ok, _result, _desc = call(
                token, "deleteMessage", {"chat_id": chat_id, "message_id": mid}
            )
            if ok:
                deleted += 1
            else:
                skipped += 1
            time.sleep(0.35)
        print(f"  lote {batch[0]}..{batch[-1]} recusado; 1-a-1: "
              f"{deleted} apagada(s) no total", flush=True)
    verbo = "apagaria" if dry_run else "apagadas"
    print(f"{verbo}: {deleted} | puladas (>48h ou inexistentes): {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=1400)
    parser.add_argument("--to", dest="end", type=int, default=0, help="0 = detecta o topo agora")
    parser.add_argument("--only-bot", action="store_true", default=True)
    parser.add_argument("--all", dest="all_msgs", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="obrigatorio pra apagar de verdade")
    parser.add_argument("--pace", type=float, default=1.2, help="segundos entre chamadas no modo only-bot")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHANNEL_ID", "")
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID ausentes no .env")

    thread_raw = os.getenv("TELEGRAM_THREAD_ID", "")
    thread_id = int(thread_raw) if thread_raw.strip().isdigit() else None
    end = args.end or current_max_id(token, chat_id, thread_id)

    if not args.dry_run and not args.yes:
        sys.exit("faltou --yes. Rode com --dry-run primeiro.")

    modo = "TODAS as mensagens (inclui humanos)" if args.all_msgs else "so mensagens do bot"
    print(f"chat {chat_id} | faixa {args.start}..{end} | modo: {modo} | dry-run: {args.dry_run}")
    if args.all_msgs:
        purge_all(token, chat_id, args.start, end, args.dry_run)
    else:
        purge_only_bot(token, chat_id, args.start, end, args.dry_run, args.pace)


if __name__ == "__main__":
    main()
