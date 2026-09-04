"""Classificação automática de categoria/hashtag para produtos do canal.

Implementa a taxonomia definida no guia de organização do canal:
Tecnologia, Casa, Cozinha, Ferramentas, Moda, Beleza, Automotivo, Games,
Brinquedos, Pets, Bebes, Papelaria — com fallback seguro para uma
hashtag genérica quando a confiança na classificação for baixa.

Não inventa categoria: quando nenhuma palavra-chave bate com confiança
suficiente, cai no genérico (#OfertaDoDia) em vez de arriscar um chute.
"""

import unicodedata

# Ordem importa: categorias mais específicas primeiro, para que um termo
# ambíguo (ex: "kit ferramentas para bebe") caia na mais específica.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Bebes": [
        "fralda", "mamadeira", "chupeta", "carrinho de bebe", "bebe conforto",
        "cadeirinha infantil", "berco", "trocador", "banheira infantil",
        "termometro infantil", "babá eletronica", "baba eletronica",
        "kit enxoval", "roupinha de bebe",
    ],
    "Pets": [
        "racao", "coleira", "guia para cachorro", "arranhador", "areia sanitaria",
        "casinha de cachorro", "caminha para pet", "aquario", "petisco",
        "brinquedo para cachorro", "brinquedo para gato", "comedouro",
        "bebedouro pet", "roupinha para cachorro", "shampoo pet",
    ],
    "Papelaria": [
        "caderno", "caneta", "lapis", "mochila escolar", "estojo escolar",
        "marca texto", "cola escolar", "planner", "agenda", "apontador",
        "borracha escolar", "fichario", "papel sulfite", "giz de cera",
    ],
    "Beleza": [
        "batom", "maquiagem", "base facial", "perfume", "hidratante",
        "protetor solar", "shampoo", "condicionador", "escova de cabelo",
        "secador de cabelo", "chapinha", "creme facial", "esmalte",
        "delineador", "paleta de sombra", "kit skincare",
    ],
    "Moda": [
        "camiseta", "camisa social", "calca jeans", "vestido", "jaqueta",
        "tenis casual", "sapato social", "bolsa feminina", "relogio de pulso",
        "oculos de sol", "sunga", "biquini", "cueca", "sutia", "meia",
        "cinto de couro", "jaqueta jeans",
    ],
    "Automotivo": [
        "pneu", "oleo de motor", "bateria automotiva", "som automotivo",
        "capa de banco", "tapete automotivo", "farol de led", "palheta limpador",
        "car play", "carplay", "suporte veicular", "aromatizante automotivo",
        "kit ferramentas automotivo", "cera automotiva",
    ],
    "Ferramentas": [
        "furadeira", "parafusadeira", "serra", "esmerilhadeira", "chave de impacto",
        "lixadeira", "trena", "alicate", "jogo de soquete", "jogo de chaves",
        "morsa", "policorte", "solda", "nivel a laser", "martelo", "marreta",
        "kit ferramentas",
    ],
    "Cozinha": [
        "panela", "airfryer", "fritadeira eletrica", "liquidificador",
        "cafeteira", "faqueiro", "jogo de panelas", "forma de bolo",
        "processador de alimentos", "batedeira", "sanduicheira", "grill eletrico",
        "conjunto de talheres", "potes hermeticos",
    ],
    "Casa": [
        "aspirador de po", "roupa de cama", "jogo de lencol", "toalha de banho",
        "cortina", "tapete para sala", "luminaria", "organizador",
        "prateleira", "armario", "cabide", "varal", "climatizador",
        "ventilador de teto", "purificador de ar", "colchao",
    ],
    "Brinquedos": [
        "boneca", "boneco de acao", "lego", "quebra-cabeca", "carrinho de brinquedo",
        "pelucia", "jogo de tabuleiro", "brinquedo educativo", "patinete infantil",
        "bicicleta infantil", "playmobil", "hot wheels",
    ],
    "Games": [
        "playstation", "ps5", "ps4", "xbox series", "xbox one", "nintendo switch",
        "controle dualsense", "controle xbox", "cartao psn", "gift card steam",
        "volante gamer", "joystick", "vr headset", "cadeira gamer", "headset gamer",
    ],
    "Tecnologia": [
        "notebook", "laptop", "computador", "pc gamer", "smartphone", "celular",
        "iphone", "galaxy s", "galaxy a", "xiaomi", "redmi", "smartwatch",
        "fone bluetooth", "fone de ouvido", "airpods", "caixa de som",
        "carregador turbo", "power bank", "cabo usb-c", "cabo usb c",
        "monitor gamer", "teclado mecanico", "mouse gamer", "ssd", "hd externo",
        "placa de video", "roteador", "camera wifi", "lampada inteligente",
        "alexa", "echo dot", "tomada inteligente", "pendrive", "webcam",
        "impressora", "tablet", "drone",
    ],
}

CATEGORY_TO_HASHTAG = {cat: f"#{cat}" for cat in CATEGORY_KEYWORDS}
GENERIC_HASHTAG = "#OfertaDoDia"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def classify_category(title: str, description: str = "", source_category: str = "") -> str:
    """Retorna o nome da categoria (ex: 'Tecnologia') ou '' se baixa confiança."""
    haystack = _normalize(f"{title} {description} {source_category}")
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in haystack:
                return category
    return ""


def classify_hashtag(title: str, description: str = "", source_category: str = "") -> str:
    """Retorna a hashtag pronta para uso no anúncio (ex: '#Tecnologia').

    Cai no genérico #OfertaDoDia quando não há confiança suficiente —
    nunca inventa uma categoria a partir de sinais fracos.
    """
    category = classify_category(title, description, source_category)
    return CATEGORY_TO_HASHTAG.get(category, GENERIC_HASHTAG)
