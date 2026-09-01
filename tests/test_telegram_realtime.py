from unittest.mock import Mock, patch

import bot_commands


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
