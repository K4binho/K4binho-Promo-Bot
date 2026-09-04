import asyncio
import logging
import threading
from unittest.mock import Mock, patch

import bot
import telegram


def test_source_tasks_run_concurrently():
    barrier = threading.Barrier(2)

    def runner(value):
        barrier.wait(timeout=1)
        return value

    tasks = [
        bot.SourceTask("a", lambda: runner(2)),
        bot.SourceTask("b", lambda: runner(3)),
    ]

    results = asyncio.run(bot.run_source_tasks(tasks, max_concurrency=2))

    assert results == {"a": 2, "b": 3}


def test_source_failure_is_isolated(caplog):
    def broken():
        raise RuntimeError("API fora do ar")

    tasks = [
        bot.SourceTask("quebrada", broken),
        bot.SourceTask("saudavel", lambda: 4),
    ]

    with caplog.at_level(logging.ERROR, logger="k4binho"):
        results = asyncio.run(bot.run_source_tasks(tasks, max_concurrency=2))

    assert results == {"quebrada": 0, "saudavel": 4}
    assert "as demais fontes continuarao" in caplog.text


def test_source_concurrency_limit_is_respected():
    active = 0
    peak = 0
    lock = threading.Lock()

    def runner():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        threading.Event().wait(0.03)
        with lock:
            active -= 1
        return 1

    tasks = [bot.SourceTask(str(i), runner) for i in range(4)]
    results = asyncio.run(bot.run_source_tasks(tasks, max_concurrency=2))

    assert sum(results.values()) == 4
    assert peak == 2


def test_source_registry_contains_all_integrations():
    cfg = Mock()
    tasks = bot.build_source_tasks(cfg, {}, {}, {}, {}, False)
    assert [task.name for task in tasks] == [
        "Mercado Livre", "Steam", "GMG", "AliExpress", "Nuuvem", "Shopee", "Kabum"
    ]


def test_telegram_rate_limiter_spaces_messages_per_chat():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = telegram.TelegramRateLimiter(
        chat_interval_seconds=1.0,
        global_messages_per_second=30,
        clock=lambda: now[0],
        sleeper=sleep,
    )

    limiter.wait("chat")
    limiter.wait("chat")

    assert sleeps == [1.0]


def test_send_message_uses_central_rate_limiter():
    response = Mock()
    response.raise_for_status.return_value = None
    with patch.object(telegram._rate_limiter, "wait") as wait, patch.object(
        telegram._client, "post", return_value=response
    ):
        telegram.send_message("token", "-1001", "oferta")

    wait.assert_called_once_with("-1001")
