"""Conversão do dataclass de cada loja para o ``Offer`` padronizado.

Este é o único lugar que sabe que o Mercado Livre chama de ``item_id`` o que o
AliExpress chama de ``product_id`` e a Steam de ``game_id``, ou que a imagem é
``thumbnail`` num, ``header_image`` noutro e ``image_url`` nos demais.

Cada função recebe o objeto cru do provider e devolve um ``Offer``, guardando o
original em ``offer.raw`` para o que ainda for específico da loja.
"""

from __future__ import annotations

from k4promo.domain.models import Offer


def from_mercadolivre(deal) -> Offer:
    return Offer(
        source="ml",
        offer_id=deal.item_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=getattr(deal, "thumbnail", "") or "",
        discount_percent=deal.discount_percent,
        sales_count=deal.sales_count,
        rating=deal.rating,
        official_store=deal.official_store,
        free_shipping=bool(getattr(deal, "free_shipping", False)),
        offer_label=deal.offer_label,
        coupon_amount=deal.coupon_amount,
        raw=deal,
    )


def from_aliexpress(deal) -> Offer:
    return Offer(
        source="aliexpress",
        offer_id=deal.product_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.image_url,
        discount_percent=deal.discount_percent,
        sales_count=deal.sales_count,
        commission_rate=deal.commission_rate,
        raw=deal,
    )


def from_shopee(deal) -> Offer:
    return Offer(
        source="shopee",
        offer_id=deal.item_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.image_url,
        discount_percent=deal.discount_percent,
        sales_count=deal.sales_count,
        rating=deal.rating,
        commission_rate=deal.commission_rate,
        raw=deal,
    )


def from_kabum(deal) -> Offer:
    return Offer(
        source="kabum",
        offer_id=deal.product_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.image_url,
        discount_percent=deal.discount_percent,
        rating=getattr(deal, "rating", None),
        free_shipping=bool(getattr(deal, "free_shipping", False)),
        offer_label=getattr(deal, "offer_name", "") or "",
        raw=deal,
    )


def from_gmg(deal) -> Offer:
    return Offer(
        source="gmg",
        offer_id=deal.item_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.image_url,
        discount_percent=int(deal.discount_percent),
        promo_code=deal.promo_code or "",
        promo_description=deal.promo_description or "",
        raw=deal,
    )


def from_steam(deal) -> Offer:
    return Offer(
        source="steam",
        offer_id=deal.game_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.header_image,
        discount_percent=deal.discount_percent,
        lowest_price=deal.lowest_price,
        review_score=deal.review_score,
        review_count=deal.review_count,
        waitlisted=deal.waitlisted,
        store_type=deal.store_type,
        raw=deal,
    )


def from_nuuvem(deal) -> Offer:
    coupon = getattr(deal, "coupon", None)
    return Offer(
        source="nuuvem",
        offer_id=deal.game_id,
        title=deal.title,
        price=deal.price,
        permalink=deal.permalink,
        original_price=deal.original_price,
        image_url=deal.image_url,
        discount_percent=deal.discount_percent,
        lowest_price=deal.lowest_price,
        review_score=deal.review_score,
        review_count=deal.review_count,
        waitlisted=deal.waitlisted,
        promo_code=coupon.code if coupon else "",
        promo_description=coupon.discount if coupon else "",
        raw=deal,
    )
