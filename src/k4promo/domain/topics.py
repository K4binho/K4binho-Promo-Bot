"""Constantes de domínio: tópicos do fórum e lojas.

Sem lógica de classificação (ver ``services/categorizer.py``) e sem decisão de
roteamento (ver ``services/router.py``). Este módulo só descreve *o que existe*:
quais tópicos, quais lojas e qual a prioridade de cada loja em cada tópico.

Regras de produto que estas estruturas codificam:

- Lojas de jogos (GMG, Steam, Nuuvem) só publicam em "Jogos em Promoção".
- Lojas físicas (ML, Shopee, AliExpress, KaBuM) nunca publicam em "Jogos".
- "Melhores do Dia" não tem coleta própria: é vitrine alimentada por cópias.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tópicos
# ---------------------------------------------------------------------------

MELHORES_DO_DIA = "melhores_do_dia"
JOGOS = "jogos"
TECNOLOGIA = "tecnologia"
CASA_COZINHA = "casa_cozinha"
MODA_BELEZA = "moda_beleza"
FERRAMENTAS_AUTO = "ferramentas_auto"
ACHADINHOS = "achadinhos"

ALL_TOPICS = (
    MELHORES_DO_DIA, JOGOS, TECNOLOGIA, CASA_COZINHA,
    MODA_BELEZA, FERRAMENTAS_AUTO, ACHADINHOS,
)

# IDs dos tópicos do grupo. Podem ser sobrescritos por TELEGRAM_TOPIC_<NOME>.
DEFAULT_TOPIC_IDS: dict[str, int] = {
    MELHORES_DO_DIA: 2194,
    JOGOS: 2195,
    TECNOLOGIA: 2197,
    CASA_COZINHA: 2198,
    MODA_BELEZA: 2201,
    FERRAMENTAS_AUTO: 2202,
    ACHADINHOS: 2205,
}

TOPIC_LABELS: dict[str, str] = {
    MELHORES_DO_DIA: "🔥 Melhores do Dia",
    JOGOS: "🎮 Jogos em Promoção",
    TECNOLOGIA: "📱 Tecnologia",
    CASA_COZINHA: "🏠 Casa & Cozinha",
    MODA_BELEZA: "👗 Moda & Beleza",
    FERRAMENTAS_AUTO: "🔧 Ferramentas & Auto",
    ACHADINHOS: "🎁 Achadinhos",
}

# ---------------------------------------------------------------------------
# Lojas
# ---------------------------------------------------------------------------

MERCADO_LIVRE = "mercado_livre"
SHOPEE = "shopee"
ALIEXPRESS = "aliexpress"
KABUM = "kabum"
GREEN_MAN_GAMING = "green_man_gaming"
STEAM = "steam"
NUUVEM = "nuuvem"

GAME_STORES = frozenset({GREEN_MAN_GAMING, STEAM, NUUVEM})
PHYSICAL_STORES = frozenset({MERCADO_LIVRE, SHOPEE, ALIEXPRESS, KABUM})

STORE_LABELS: dict[str, str] = {
    MERCADO_LIVRE: "Mercado Livre",
    SHOPEE: "Shopee",
    ALIEXPRESS: "AliExpress",
    KABUM: "KaBuM!",
    GREEN_MAN_GAMING: "Green Man Gaming",
    STEAM: "Steam",
    NUUVEM: "Nuuvem",
}

# Nome usado internamente pelo bot/analytics (``source``) -> chave de loja.
STORE_BY_SOURCE: dict[str, str] = {
    "ml": MERCADO_LIVRE,
    "mercadolivre": MERCADO_LIVRE,
    "mercado_livre": MERCADO_LIVRE,
    "shopee": SHOPEE,
    "ali": ALIEXPRESS,
    "aliexpress": ALIEXPRESS,
    "kabum": KABUM,
    "gmg": GREEN_MAN_GAMING,
    "green_man_gaming": GREEN_MAN_GAMING,
    "steam": STEAM,
    "nuuvem": NUUVEM,
}

# Prioridade de lojas por tópico. A ordem importa: índice menor = prioridade
# maior. Lojas fora da lista não devem publicar no tópico (exceto o caso
# editorial de Steam/Nuuvem em "Melhores do Dia", tratado em
# ``showcase_eligible``).
STORE_TOPIC_PRIORITY: dict[str, list[str]] = {
    MELHORES_DO_DIA: [MERCADO_LIVRE, SHOPEE, ALIEXPRESS, KABUM, GREEN_MAN_GAMING],
    JOGOS: [GREEN_MAN_GAMING, STEAM, NUUVEM],
    TECNOLOGIA: [KABUM, MERCADO_LIVRE, ALIEXPRESS, SHOPEE],
    CASA_COZINHA: [SHOPEE, MERCADO_LIVRE, ALIEXPRESS, KABUM],
    MODA_BELEZA: [SHOPEE, ALIEXPRESS, MERCADO_LIVRE],
    FERRAMENTAS_AUTO: [MERCADO_LIVRE, ALIEXPRESS, SHOPEE, KABUM],
    ACHADINHOS: [SHOPEE, ALIEXPRESS, MERCADO_LIVRE, KABUM],
}

# Steam/Nuuvem só entram em "Melhores do Dia" com forte valor editorial.
SHOWCASE_EDITORIAL_STORES = frozenset({STEAM, NUUVEM})


def store_key(source: str) -> str:
    """Normaliza ``source`` do bot ("ml", "ali", "gmg"...) para a chave da loja."""
    raw = (source or "").strip().lower()
    return STORE_BY_SOURCE.get(raw, raw)


def store_label(source: str) -> str:
    key = store_key(source)
    return STORE_LABELS.get(key, source)


def topic_label(topic: str) -> str:
    return TOPIC_LABELS.get(topic, topic)


def store_allowed(topic: str, source: str) -> bool:
    return store_key(source) in STORE_TOPIC_PRIORITY.get(topic, [])


def store_rank(topic: str, source: str) -> int:
    """Posição da loja na prioridade do tópico (0 = máxima). Lojas fora da
    lista recebem um valor alto para ficarem por último."""
    key = store_key(source)
    order = STORE_TOPIC_PRIORITY.get(topic, [])
    try:
        return order.index(key)
    except ValueError:
        return len(order) + 10
