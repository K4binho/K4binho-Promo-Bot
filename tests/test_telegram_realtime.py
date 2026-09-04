from unittest.mock import MagicMock, Mock, patch

import bot_commands
import telegram_listener


def _update(text="/start", *, thread_id=10, user_id=123):
    return {
        "update_id": 1,
        "message": {
            "text": text,
            "chat": {"id": -1001},
            "from": {"id": user_id},
            "message_thread_id": thread_id,
        },
    }


def test_topic_command_is_blocked_for_non_admin():
    alerts = {}
    with patch.object(bot_commands, "_is_admin", return_value=False), patch.object(bot_commands.telegram, "send_message") as send:
        bot_commands.handle_update("token", _update(), alerts)
    send.assert_not_called()


def test_topic_command_is_allowed_for_admin():
    alerts = {}
    with patch.object(bot_commands, "_is_admin", return_value=True), patch.object(bot_commands.telegram, "send_message") as send:
        bot_commands.handle_update("token", _update(), alerts)
    send.assert_called_once()
    assert send.call_args.kwargs["thread_id"] == 10


def test_poll_commands_starts_single_realtime_listener():
    old = bot_commands._realtime_listener
    bot_commands._realtime_listener = None
    try:
        fake = Mock()
        with patch.object(bot_commands.telegram_listener, "TelegramRealtimeListener", return_value=fake) as cls:
            assert bot_commands.poll_commands("token", {}, 0, "42") == 0
            assert bot_commands.poll_commands("token", {}, 0, "42") == 0
        cls.assert_called_once()
        fake.start.assert_called_once()
    finally:
        bot_commands._realtime_listener = old


def test_listener_serializes_allowed_updates_and_advances_offset():
    handled = []
    listener = None

    def handler(update):
        handled.append(update)
        listener._stop.set()

    listener = telegram_listener.TelegramRealtimeListener("token", handler, initial_offset=3)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"ok": True, "result": [{"update_id": 7, "message": {"text": "/start"}}]}
    client = Mock()
    client.get.return_value = response
    client_context = MagicMock()
    client_context.__enter__.return_value = client

    with patch.object(telegram_listener.httpx, "Client", return_value=client_context):
        listener._run()

    assert handled == [{"update_id": 7, "message": {"text": "/start"}}]
    assert listener._offset == 8
    params = client.get.call_args.kwargs["params"]
    assert params["offset"] == 3
    assert params["allowed_updates"] == '["message", "callback_query"]'


def test_listener_can_restart_after_stop():
    listener = telegram_listener.TelegramRealtimeListener("token", lambda update: None)
    listener._stop.set()

    with patch.object(listener, "_run") as run:
        listener.start()
        if listener._thread:
            listener._thread.join(timeout=1)

    assert not listener._stop.is_set()
    run.assert_called_once()
