from unittest import mock

import pytest

import bot_commands
import deal_hunter
import rate_limit


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_limiter_blocks_after_max_events():
    clock = FakeClock()
    limiter = rate_limit.SlidingWindowLimiter(3, 60.0, clock=clock)
    assert [limiter.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_in = limiter.check("a")
    assert allowed is False
    assert retry_in == pytest.approx(60.0)


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = rate_limit.SlidingWindowLimiter(2, 60.0, clock=clock)
    limiter.check("a")
    limiter.check("a")
    assert limiter.check("a")[0] is False
    clock.advance(60.1)
    assert limiter.check("a")[0] is True


def test_limiter_is_per_key():
    clock = FakeClock()
    limiter = rate_limit.SlidingWindowLimiter(1, 60.0, clock=clock)
    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is False
    assert limiter.check("b")[0] is True


def test_limiter_prunes_stale_keys():
    clock = FakeClock()
    limiter = rate_limit.SlidingWindowLimiter(1, 10.0, max_keys=2, clock=clock)
    limiter.check("a")
    limiter.check("b")
    clock.advance(11.0)
    limiter.check("c")
    assert set(limiter._hits) == {"c"}


def test_limiter_rejects_bad_config():
    with pytest.raises(ValueError):
        rate_limit.SlidingWindowLimiter(0, 60.0)
    with pytest.raises(ValueError):
        rate_limit.SlidingWindowLimiter(1, 0)


def _result(source: str, title: str, price: float, pid: str = "1") -> deal_hunter.HuntResult:
    return deal_hunter.HuntResult(
        source=source, product_id=pid, title=title, price=price,
        original_price=None, discount_percent=0, link="https://x.test/1",
    )


def test_hunt_requires_all_terms_in_title():
    with mock.patch.object(deal_hunter, "_hunt_steam", return_value=[
        _result("steam", "Palworld", 62.0, "p1"),
        _result("steam", "Outro Jogo", 10.0, "p2"),
    ]), mock.patch.object(deal_hunter, "_hunt_aliexpress", return_value=[]), \
            mock.patch.object(deal_hunter, "_hunt_shopee", return_value=[]):
        found = deal_hunter.hunt("palworld")
    assert [r.title for r in found] == ["Palworld"]


def test_hunt_ranks_relevance_before_price():
    """Chaveiro barato nao passa na frente do jogo — o pedido era o jogo."""
    with mock.patch.object(deal_hunter, "_hunt_steam", return_value=[
        _result("steam", "Palworld", 62.0, "p1"),
    ]), mock.patch.object(deal_hunter, "_hunt_aliexpress", return_value=[
        _result("aliexpress", "Chaveiro de Poke Ball do jogo Palworld pingente", 14.99, "a1"),
    ]), mock.patch.object(deal_hunter, "_hunt_shopee", return_value=[]):
        found = deal_hunter.hunt("palworld")
    assert [r.source for r in found] == ["steam", "aliexpress"]


def test_hunt_applies_max_price():
    with mock.patch.object(deal_hunter, "_hunt_steam", return_value=[
        _result("steam", "Palworld", 62.0, "p1"),
    ]), mock.patch.object(deal_hunter, "_hunt_aliexpress", return_value=[]), \
            mock.patch.object(deal_hunter, "_hunt_shopee", return_value=[]):
        assert deal_hunter.hunt("palworld", max_price=50.0) == []


def test_hunt_survives_one_failing_source():
    with mock.patch.object(deal_hunter, "_hunt_steam", side_effect=RuntimeError("api down")), \
            mock.patch.object(deal_hunter, "_hunt_shopee", return_value=[
                _result("shopee", "Palworld Figure", 40.0, "s1")
            ]), mock.patch.object(deal_hunter, "_hunt_aliexpress", return_value=[]):
        found = deal_hunter.hunt("palworld")
    assert [r.source for r in found] == ["shopee"]


def test_hunt_empty_keywords_does_no_network():
    with mock.patch.object(deal_hunter, "_hunt_steam") as steam_job:
        assert deal_hunter.hunt("   ") == []
    steam_job.assert_not_called()


def test_classify_kind_game_source_is_always_game():
    # Steam/Nuuvem/GMG so vendem jogo -- mesmo um titulo generico e jogo.
    assert deal_hunter._classify_kind("steam", "Skyrim") == deal_hunter.GAME_KIND
    assert deal_hunter._classify_kind("nuuvem", "Random Bundle") == deal_hunter.GAME_KIND
    assert deal_hunter._classify_kind("gmg", "Anything") == deal_hunter.GAME_KIND


def test_classify_kind_physical_store_is_item_by_default():
    assert deal_hunter._classify_kind("shopee", "Caneca Skyrim") == deal_hunter.ITEM_KIND
    assert deal_hunter._classify_kind("aliexpress", "Adesivo Zelda") == deal_hunter.ITEM_KIND


def test_classify_kind_key_or_giftcard_in_physical_store_is_game():
    # Loja fisica vendendo chave/gift card ainda e o jogo, nao bugiganga.
    assert deal_hunter._classify_kind("shopee", "Steam Key Palworld") == deal_hunter.GAME_KIND
    assert deal_hunter._classify_kind("aliexpress", "Gift Card Xbox R$100") == deal_hunter.GAME_KIND


def test_hunt_sets_kind_and_splits_mixed_results():
    game = _result("steam", "Skyrim", 50.0, "1")
    item = _result("shopee", "Caneca Skyrim", 20.0, "2")
    with mock.patch.object(deal_hunter, "_hunt_steam", return_value=[game]), \
            mock.patch.object(deal_hunter, "_hunt_aliexpress", return_value=[]), \
            mock.patch.object(deal_hunter, "_hunt_shopee", return_value=[item]):
        results = deal_hunter.hunt("skyrim")
    games, items = deal_hunter.split_kinds(results)
    assert [g.title for g in games] == ["Skyrim"]
    assert [i.title for i in items] == ["Caneca Skyrim"]


def test_split_kinds_preserves_relevance_order():
    a = _result("steam", "A", 1.0, "1")
    a.kind = deal_hunter.GAME_KIND
    a.relevance = 0.9
    b = _result("steam", "B", 1.0, "2")
    b.kind = deal_hunter.GAME_KIND
    b.relevance = 0.5
    games, items = deal_hunter.split_kinds([a, b])
    assert games == [a, b]
    assert items == []
