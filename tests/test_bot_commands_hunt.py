from unittest import mock

import alert_store
import bot_commands
import config
import deal_hunter


def _cfg(**over):
    cfg = config.Config()
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def _update(text: str, chat_id: int = 42, thread_id: int | None = None) -> dict:
    msg = {"chat": {"id": chat_id}, "text": text, "from": {"id": 7}}
    if thread_id is not None:
        msg["message_thread_id"] = thread_id
    return {"message": msg}


def setup_function() -> None:
    bot_commands.configure(_cfg(hunt_enabled=True))
    bot_commands._hunt_in_flight.clear()


def test_command_rate_limit_blocks_flood_silently():
    bot_commands.configure(_cfg(command_rate_limit_per_minute=2))
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(bot_commands, "_hunt_async", return_value=False):
        for _ in range(5):
            bot_commands.handle_update("t", _update("/meusalertas"), {})
    assert send.call_count == 2


def test_rate_limit_is_per_chat():
    bot_commands.configure(_cfg(command_rate_limit_per_minute=1))
    with mock.patch.object(bot_commands, "_send") as send:
        bot_commands.handle_update("t", _update("/meusalertas", chat_id=1), {})
        bot_commands.handle_update("t", _update("/meusalertas", chat_id=1), {})
        bot_commands.handle_update("t", _update("/meusalertas", chat_id=2), {})
    assert send.call_count == 2


def test_non_command_text_is_not_rate_limited():
    bot_commands.configure(_cfg(command_rate_limit_per_minute=1))
    with mock.patch.object(bot_commands, "_send") as send:
        for _ in range(5):
            bot_commands.handle_update("t", _update("oi bot"), {})
    send.assert_not_called()


def test_cancel_alert_removes_and_names_it():
    alerts: dict = {}
    alert_store.add_alert(alerts, "42", "rtx 5070")
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(alert_store, "save_alerts"):
        bot_commands.handle_update("t", _update("/cancelar 1"), alerts)
    assert alerts == {}
    assert "rtx 5070" in send.call_args[0][2]


def test_cancel_invalid_index_keeps_alert():
    alerts: dict = {}
    alert_store.add_alert(alerts, "42", "rtx 5070")
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(alert_store, "save_alerts"):
        bot_commands.handle_update("t", _update("/cancelar 9"), alerts)
    assert len(alerts["42"]) == 1
    assert "inválido" in send.call_args[0][2]


def test_add_alert_triggers_immediate_hunt():
    alerts: dict = {}
    with mock.patch.object(bot_commands, "_send"), \
            mock.patch.object(alert_store, "save_alerts"), \
            mock.patch.object(bot_commands, "_hunt_async") as hunt:
        bot_commands.handle_update("t", _update("/alerta ssd abaixo de 500"), alerts)
    assert alerts["42"][0]["keywords"] == "ssd"
    assert alerts["42"][0]["max_price"] == 500.0
    assert hunt.call_args[0][2:4] == ("ssd", 500.0)


def test_add_alert_respects_configured_limit():
    bot_commands.configure(_cfg(max_alerts_per_chat=1, command_rate_limit_per_minute=99))
    alerts: dict = {}
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(alert_store, "save_alerts"), \
            mock.patch.object(bot_commands, "_hunt_async"):
        bot_commands.handle_update("t", _update("/alerta primeiro"), alerts)
        bot_commands.handle_update("t", _update("/alerta segundo"), alerts)
    assert len(alerts["42"]) == 1
    assert "Limite de 1 alertas" in send.call_args[0][2]


def test_hunt_async_rejects_second_concurrent_hunt_per_chat():
    started = []
    with mock.patch.object(bot_commands, "_send"), \
            mock.patch.object(bot_commands.threading, "Thread") as thread:
        thread.side_effect = lambda **kw: started.append(kw) or mock.Mock()
        assert bot_commands._hunt_async("t", "42", "ssd", None, None, "buscar") is True
        assert bot_commands._hunt_async("t", "42", "ssd", None, None, "buscar") is False
    assert len(started) == 1


def test_hunt_async_blocked_by_hourly_limit():
    bot_commands.configure(_cfg(hunt_rate_limit_per_hour=1))
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(bot_commands.threading, "Thread", return_value=mock.Mock()):
        assert bot_commands._hunt_async("t", "42", "ssd", None, None, "buscar") is True
        bot_commands._hunt_in_flight.clear()
        assert bot_commands._hunt_async("t", "42", "ssd", None, None, "buscar") is False
    assert "Muitas buscas" in send.call_args[0][2]


def test_hunt_async_blocked_by_global_limit():
    bot_commands.configure(_cfg(hunt_global_rate_limit_per_minute=1))
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(bot_commands.threading, "Thread", return_value=mock.Mock()):
        assert bot_commands._hunt_async("t", "1", "ssd", None, None, "buscar") is True
        assert bot_commands._hunt_async("t", "2", "ssd", None, None, "buscar") is False
    assert "Muita busca na fila" in send.call_args[0][2]


def test_hunt_disabled_short_circuits():
    bot_commands.configure(_cfg(hunt_enabled=False))
    with mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(bot_commands.threading, "Thread") as thread:
        bot_commands.handle_update("t", _update("/buscar ssd"), {})
    thread.assert_not_called()
    assert "desligada" in send.call_args[0][2]


def test_run_hunt_releases_in_flight_slot_on_failure():
    bot_commands._hunt_in_flight.add("42")
    with mock.patch.object(bot_commands.deal_hunter, "hunt", side_effect=bot_commands.httpx.ConnectError("x")), \
            mock.patch.object(bot_commands, "_send"):
        bot_commands._run_hunt("t", "42", "ssd", None, None, "buscar")
    assert "42" not in bot_commands._hunt_in_flight


def test_format_hunt_reply_empty_mentions_alert_still_active():
    text = bot_commands._format_hunt_reply("ssd", [], 500.0, 3)
    assert "Nada encontrado" in text
    assert "R$ 500,00" in text


def _game_result(price=100.0):
    return deal_hunter.HuntResult(
        source="steam", product_id="g1", title="Skyrim", price=price,
        original_price=200.0, discount_percent=50, link="https://steam.test/g1",
        kind=deal_hunter.GAME_KIND,
    )


def _item_result(price=30.0):
    return deal_hunter.HuntResult(
        source="shopee", product_id="i1", title="Caneca Skyrim", price=price,
        original_price=40.0, discount_percent=25, link="https://shopee.test/i1",
        kind=deal_hunter.ITEM_KIND,
    )


def test_run_hunt_asks_when_game_and_item_both_found():
    with mock.patch.object(bot_commands.deal_hunter, "hunt",
                            return_value=[_game_result(), _item_result()]), \
            mock.patch.object(bot_commands.telegram, "send_message") as send:
        bot_commands._run_hunt("t", "42", "skyrim", None, None, "buscar")
    send.assert_called_once()
    _token, _chat, text = send.call_args[0][:3]
    assert "O que você quer" in text
    assert "1 jogo" in text
    assert "1 produto" in text
    markup = send.call_args.kwargs["reply_markup"]
    buttons = markup["inline_keyboard"][0]
    assert buttons[0]["callback_data"].startswith("hunt:")
    assert buttons[0]["callback_data"].endswith(f":{deal_hunter.GAME_KIND}")
    assert buttons[1]["callback_data"].endswith(f":{deal_hunter.ITEM_KIND}")
    # o pendente fica guardado pro clique resolver sem refazer a busca
    nonce = buttons[0]["callback_data"].split(":")[1]
    assert nonce in bot_commands._hunt_pending
    assert bot_commands._hunt_pending[nonce]["chat_id"] == "42"


def test_run_hunt_skips_question_when_only_one_kind_found():
    with mock.patch.object(bot_commands.deal_hunter, "hunt", return_value=[_game_result()]), \
            mock.patch.object(bot_commands, "_send") as send, \
            mock.patch.object(bot_commands.telegram, "send_message") as send_markup:
        bot_commands._run_hunt("t", "42", "skyrim", None, None, "buscar")
    send_markup.assert_not_called()
    send.assert_called_once()
    assert "Skyrim" in send.call_args[0][2]


def test_hunt_callback_returns_chosen_kind_without_new_search():
    nonce = bot_commands._remember_hunt(
        "42", "skyrim", None, None, [_game_result(), _item_result()]
    )
    callback = {
        "id": "cb1",
        "data": f"hunt:{nonce}:{deal_hunter.GAME_KIND}",
        "message": {"chat": {"id": 42}},
    }
    with mock.patch.object(bot_commands.deal_hunter, "hunt") as hunt, \
            mock.patch.object(bot_commands.telegram, "answer_callback_query"), \
            mock.patch.object(bot_commands, "_send") as send:
        bot_commands._handle_hunt_callback("t", callback)
    hunt.assert_not_called()  # usa o resultado ja guardado, nao busca de novo
    assert "Skyrim" in send.call_args[0][2]
    assert "Caneca" not in send.call_args[0][2]


def test_hunt_callback_expired_nonce_asks_to_redo():
    callback = {
        "id": "cb1", "data": "hunt:naoexiste:jogo",
        "message": {"chat": {"id": 42}},
    }
    with mock.patch.object(bot_commands.telegram, "answer_callback_query"), \
            mock.patch.object(bot_commands, "_send") as send:
        bot_commands._handle_hunt_callback("t", callback)
    assert "expirou" in send.call_args[0][2]


def test_hunt_callback_rejects_nonce_from_a_different_chat():
    nonce = bot_commands._remember_hunt(
        "42", "skyrim", None, None, [_game_result(), _item_result()]
    )
    callback = {
        "id": "cb1", "data": f"hunt:{nonce}:{deal_hunter.GAME_KIND}",
        "message": {"chat": {"id": 999}},  # chat diferente de quem pediu
    }
    with mock.patch.object(bot_commands.telegram, "answer_callback_query"), \
            mock.patch.object(bot_commands, "_send") as send:
        bot_commands._handle_hunt_callback("t", callback)
    assert "expirou" in send.call_args[0][2]
