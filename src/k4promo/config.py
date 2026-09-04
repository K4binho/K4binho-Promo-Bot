import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

from k4promo.domain import topics

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_alias(primary: str, *aliases: str) -> str:
    """Lê `primary`; se vazio, tenta os aliases legados na ordem."""
    value = _get(primary)
    if value:
        return value
    for name in aliases:
        value = _get(name)
        if value:
            return value
    return ""


def _topic_ids() -> dict[str, int | None]:
    """IDs dos tópicos do fórum. Default = IDs conhecidos do grupo; cada um pode
    ser sobrescrito por TELEGRAM_TOPIC_<NOME>. Valor 0 desativa o tópico e a
    publicação cai no TELEGRAM_THREAD_ID geral (ou raiz do canal)."""
    result: dict[str, int | None] = {}
    for topic, default in topics.DEFAULT_TOPIC_IDS.items():
        value = _get_int(f"TELEGRAM_TOPIC_{topic.upper()}", default)
        result[topic] = value or None
    return result


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_searches(name: str) -> list[tuple[str, str]]:
    raw = os.getenv(name, "")
    result = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            kw, cat = entry.rsplit(":", 1)
            result.append((kw.strip(), cat.strip()))
        else:
            result.append((entry, ""))
    return result


@dataclass
class Config:
    telegram_bot_token: str = field(default_factory=lambda: _get("TELEGRAM_BOT_TOKEN"))
    telegram_channel_id: str = field(default_factory=lambda: _get("TELEGRAM_CHANNEL_ID"))
    telegram_thread_id: int | None = field(
        default_factory=lambda: _get_int("TELEGRAM_THREAD_ID", 0) or None
    )
    telegram_topic_ids: dict[str, int | None] = field(default_factory=_topic_ids)
    showcase_enabled: bool = field(
        default_factory=lambda: _get_bool("MELHORES_DO_DIA_ENABLED", True)
    )
    showcase_max_per_cycle: int = field(
        default_factory=lambda: _get_int("MELHORES_DO_DIA_MAX_PER_CYCLE", 2)
    )
    showcase_max_per_day: int = field(
        default_factory=lambda: _get_int("MELHORES_DO_DIA_MAX_PER_DAY", 8)
    )
    showcase_min_physical_discount: int = field(
        default_factory=lambda: _get_int("MELHORES_DO_DIA_MIN_DISCOUNT", 40)
    )
    showcase_min_game_discount: int = field(
        default_factory=lambda: _get_int("MELHORES_DO_DIA_MIN_GAME_DISCOUNT", 70)
    )
    ml_client_id: str = field(default_factory=lambda: _get("ML_CLIENT_ID"))
    ml_client_secret: str = field(default_factory=lambda: _get("ML_CLIENT_SECRET"))
    ml_affiliate_tag: str = field(default_factory=lambda: _get("ML_AFFILIATE_TAG"))
    ml_site: str = field(default_factory=lambda: _get("ML_SITE") or "MLB")
    score_min: int = field(default_factory=lambda: _get_int("SCORE_MIN", 70))
    launch_score: int = field(default_factory=lambda: _get_int("LAUNCH_SCORE", 95))
    price_min: int = field(default_factory=lambda: _get_int("PRICE_MIN", 30))
    min_history_observations: int = field(
        default_factory=lambda: _get_int("MIN_HISTORY_OBS", 4)
    )
    price_history_days: int = field(
        default_factory=lambda: _get_int("PRICE_HISTORY_DAYS", 30)
    )
    ml_highlight_category_ids: list[str] = field(
        default_factory=lambda: _get_list("ML_HIGHLIGHT_CATEGORY_IDS")
    )
    promotions_file: str = field(default_factory=lambda: _get("PROMOTIONS_FILE") or "promotions.json")
    ml_coupon_discovery_enabled: bool = field(
        default_factory=lambda: _get_bool("ML_COUPON_DISCOVERY_ENABLED", True)
    )
    ml_coupon_scan_items: int = field(
        default_factory=lambda: _get_int("ML_COUPON_SCAN_ITEMS", 16)
    )
    ml_coupon_cache_hours: int = field(
        default_factory=lambda: _get_int("ML_COUPON_CACHE_HOURS", 6)
    )
    ml_coupon_positive_cache_hours: int = field(
        default_factory=lambda: _get_int("ML_COUPON_POSITIVE_CACHE_HOURS", 2)
    )
    ml_promo_revival_cooldown_hours: int = field(
        default_factory=lambda: _get_int("ML_PROMO_REVIVAL_COOLDOWN_HOURS", 6)
    )
    ml_promo_revival_min_drop_percent: int = field(
        default_factory=lambda: _get_int("ML_PROMO_REVIVAL_MIN_DROP_PERCENT", 5)
    )
    ml_promo_revival_min_drop_amount: int = field(
        default_factory=lambda: _get_int("ML_PROMO_REVIVAL_MIN_DROP_AMOUNT", 20)
    )
    promotion_campaign_notices_enabled: bool = field(
        default_factory=lambda: _get_bool("PROMOTION_CAMPAIGN_NOTICES_ENABLED", True)
    )
    poll_interval_seconds: int = field(default_factory=lambda: _get_int("POLL_INTERVAL_SECONDS", 1800))
    max_posts_per_cycle: int = field(default_factory=lambda: _get_int("MAX_POSTS_PER_CYCLE", 3))
    steam_min_discount_percent: int = field(
        default_factory=lambda: _get_int("STEAM_MIN_DISCOUNT_PERCENT", 20)
    )
    steam_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("STEAM_MAX_POSTS_PER_CYCLE", 3)
    )
    steam_bundle_scan_apps: int = field(
        default_factory=lambda: _get_int("STEAM_BUNDLE_SCAN_APPS", 24)
    )
    itad_api_key: str = field(default_factory=lambda: _get("ITAD_API_KEY"))
    steam_min_review_score: int = field(
        default_factory=lambda: _get_int("STEAM_MIN_REVIEW_SCORE", 80)
    )
    steam_min_review_count: int = field(
        default_factory=lambda: _get_int("STEAM_MIN_REVIEW_COUNT", 500)
    )
    steam_min_waitlisted: int = field(
        default_factory=lambda: _get_int("STEAM_MIN_WAITLISTED", 1000)
    )
    # Green Man Gaming via impact.com (não é CJ Affiliate). CJ_* são aliases
    # legados aceitos por compatibilidade.
    impact_account_sid: str = field(
        default_factory=lambda: _get_alias("IMPACT_ACCOUNT_SID", "CJ_ACCOUNT_SID")
    )
    impact_auth_token: str = field(
        default_factory=lambda: _get_alias("IMPACT_AUTH_TOKEN", "CJ_AUTH_TOKEN")
    )
    gmg_program_id: str = field(default_factory=lambda: _get("GMG_PROGRAM_ID"))
    gmg_catalog_id: str = field(default_factory=lambda: _get("GMG_CATALOG_ID"))
    gmg_catalog_currency: str = field(default_factory=lambda: _get("GMG_CATALOG_CURRENCY"))
    gmg_catalog_page_size: int = field(
        default_factory=lambda: _get_int("GMG_CATALOG_PAGE_SIZE", 1000)
    )
    gmg_catalog_max_pages: int = field(
        default_factory=lambda: _get_int("GMG_CATALOG_MAX_PAGES", 10)
    )
    gmg_min_discount_percent: int = field(
        default_factory=lambda: _get_int("GMG_MIN_DISCOUNT_PERCENT", 30)
    )
    gmg_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("GMG_MAX_POSTS_PER_CYCLE", 3)
    )
    aliexpress_app_key: str = field(default_factory=lambda: _get("ALIEXPRESS_APP_KEY"))
    aliexpress_app_secret: str = field(default_factory=lambda: _get("ALIEXPRESS_APP_SECRET"))
    aliexpress_tracking_id: str = field(
        default_factory=lambda: _get("ALIEXPRESS_TRACKING_ID") or "default"
    )
    aliexpress_min_discount_percent: int = field(
        default_factory=lambda: _get_int("ALIEXPRESS_MIN_DISCOUNT_PERCENT", 30)
    )
    aliexpress_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("ALIEXPRESS_MAX_POSTS_PER_CYCLE", 3)
    )
    aliexpress_searches: list[tuple[str, str]] = field(
        default_factory=lambda: _parse_searches("ALIEXPRESS_SEARCHES")
    )
    # Shopee Afiliados (Open API GraphQL)
    shopee_app_id: str = field(default_factory=lambda: _get("SHOPEE_APP_ID"))
    shopee_app_secret: str = field(default_factory=lambda: _get("SHOPEE_APP_SECRET"))
    shopee_searches: list[str] = field(default_factory=lambda: _get_list("SHOPEE_SEARCHES"))
    shopee_min_discount_percent: int = field(
        default_factory=lambda: _get_int("SHOPEE_MIN_DISCOUNT_PERCENT", 30)
    )
    shopee_min_sales: int = field(default_factory=lambda: _get_int("SHOPEE_MIN_SALES", 20))
    shopee_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("SHOPEE_MAX_POSTS_PER_CYCLE", 3)
    )
    # KaBuM! via Awin
    kabum_awin_token: str = field(
        default_factory=lambda: _get_alias("KABUM_AWIN_TOKEN", "AWIN_API_TOKEN")
    )
    kabum_publisher_id: int = field(
        default_factory=lambda: _get_int("KABUM_PUBLISHER_ID", 0) or _get_int("AWIN_PUBLISHER_ID", 0)
    )
    kabum_min_discount_percent: int = field(
        default_factory=lambda: _get_int("KABUM_MIN_DISCOUNT_PERCENT", 20)
    )
    kabum_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("KABUM_MAX_POSTS_PER_CYCLE", 3)
    )
    nuuvem_min_discount_percent: int = field(
        default_factory=lambda: _get_int("NUUVEM_MIN_DISCOUNT_PERCENT", 20)
    )
    nuuvem_max_posts_per_cycle: int = field(
        default_factory=lambda: _get_int("NUUVEM_MAX_POSTS_PER_CYCLE", 3)
    )
    nuuvem_min_waitlisted: int = field(
        default_factory=lambda: _get_int("NUUVEM_MIN_WAITLISTED", 300)
    )
    plus_editorial_min_score: int = field(
        default_factory=lambda: _get_int("PLUS_EDITORIAL_MIN_SCORE", 25)
    )
    plus_editorial_hours_without: int = field(
        default_factory=lambda: _get_int("PLUS_EDITORIAL_HOURS_WITHOUT", 24)
    )
    telegram_admin_chat_id: str = field(default_factory=lambda: _get("TELEGRAM_ADMIN_CHAT_ID"))
    digest_enabled: bool = field(
        default_factory=lambda: _get("DIGEST_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    digest_hour: int = field(default_factory=lambda: _get_int("DIGEST_HOUR", 21))
    digest_max_items: int = field(default_factory=lambda: _get_int("DIGEST_MAX_ITEMS", 5))
    click_tracking_enabled: bool = field(
        default_factory=lambda: _get("CLICK_TRACKING_ENABLED", "false").lower() in ("1", "true", "yes")
    )
    click_server_port: int = field(default_factory=lambda: _get_int("CLICK_SERVER_PORT", 8321))
    click_base_url: str = field(default_factory=lambda: _get("CLICK_BASE_URL", "http://localhost:8321"))

    # Aliases legados (CJ) — a integração é impact.com.
    @property
    def cj_account_sid(self) -> str:
        return self.impact_account_sid

    @property
    def cj_auth_token(self) -> str:
        return self.impact_auth_token

    def topic_thread_id(self, topic: str) -> int | None:
        """Thread do tópico; se desativado (0), usa o thread geral."""
        value = self.telegram_topic_ids.get(topic)
        return value if value is not None else self.telegram_thread_id

    def validate(self) -> list[str]:
        errors = []
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN vazio")
        if not self.telegram_channel_id:
            errors.append("TELEGRAM_CHANNEL_ID vazio")
        return errors
