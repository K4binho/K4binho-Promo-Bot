"""Classificação de título de produto físico em tópico.

A pontuação de um tópico é a soma do tamanho das palavras-chave encontradas,
então palavras mais longas (mais específicas) vencem as genéricas: "relógio
inteligente" vai para Tecnologia e "relógio masculino" para Moda & Beleza;
"câmera veicular" vai para Ferramentas & Auto e "câmera Wi-Fi" para Tecnologia.

O casamento é por palavra inteira (com plural simples), para "bone" não casar
com "boneca" nem "pet" com "tapete".
"""

from __future__ import annotations

import re
import unicodedata

from k4promo.domain.topics import (
    ACHADINHOS, CASA_COZINHA, FERRAMENTAS_AUTO, MODA_BELEZA, TECNOLOGIA,
)


# Palavras-chave por tópico. A pontuação de um tópico é a soma do tamanho das
# palavras-chave encontradas; palavras mais longas (mais específicas) pesam
# mais, o que resolve conflitos como "relogio inteligente" (Tecnologia)
# versus "relogio" (Moda & Beleza) ou "camera veicular" (Ferramentas & Auto)
# versus "camera" (Tecnologia).
TOPIC_KEYWORDS: dict[str, list[str]] = {
    TECNOLOGIA: [
        # celulares
        "smartphone", "celular", "iphone", "galaxy s", "galaxy a", "galaxy z",
        "galaxy m", "xiaomi", "redmi", "poco x", "poco f", "poco m", "moto g",
        "moto e", "moto edge", "motorola", "realme", "capinha", "capa celular",
        "pelicula", "smartwatch", "relogio inteligente", "smart watch", "mi band",
        "smartband", "galaxy watch", "apple watch", "tablet", "ipad", "kindle",
        # informática
        "notebook", "laptop", "computador", "pc gamer", "desktop", "all in one",
        "ssd", "nvme", "hd externo", "hd interno", "monitor", "ultrawide",
        "teclado", "mouse", "mousepad", "roteador", "repetidor wifi", "modem",
        "placa de video", "placa video", "rtx", "gtx", "radeon", "gpu",
        "memoria ram", "ddr4", "ddr5", "processador", "ryzen", "intel core",
        "core i3", "core i5", "core i7", "core i9", "cpu", "cooler",
        "water cooler", "ventoinha", "placa mae", "placa-mae", "gabinete",
        "fonte atx", "fonte 600w", "fonte 500w", "fonte 750w", "webcam", "nobreak",
        "impressora", "pendrive", "cartao de memoria", "micro sd", "microsd",
        "cadeira gamer", "microfone", "capturadora", "pasta termica",
        "hub usb", "adaptador usb", "dock station", "switch de rede",
        # áudio
        "fone", "fones", "fone de ouvido", "fones de ouvido", "tws", "bluetooth",
        "earbud", "airpods", "headset", "headphone", "caixa de som",
        "soundbar", "sound bar", "jbl", "microfone", "amplificador",
        # games físicos -> Tecnologia (nunca em Jogos)
        "playstation", "ps5", "ps4", "xbox", "nintendo switch", "console",
        "controle sem fio", "controle xbox", "controle ps5", "controle ps4",
        "controle dualsense", "dualsense", "gamepad", "joystick", "volante gamer",
        "oculos vr", "vr headset", "meta quest",
        # carregadores / cabos
        "carregador", "power bank", "powerbank", "cabo usb", "cabo tipo c",
        "cabo lightning", "cabo hdmi", "fonte carregador", "estacao de carregamento",
        "carregador sem fio",
        # câmeras e automação residencial
        "camera de seguranca", "camera wifi", "camera ip", "camera full hd",
        "camera 4k", "alexa", "echo dot", "echo show", "google nest",
        "chromecast", "fire tv", "tv box", "smart tv", "televisao", "projetor",
        "fechadura digital", "fechadura eletronica", "campainha inteligente",
        "sensor de presenca", "drone", "gopro", "action cam",
        "rastreador", "airtag", "smart tag", "localizador gps", "gps",
        "adaptador", "adaptador de tomada", "adaptador universal",
    ],
    CASA_COZINHA: [
        "panela", "frigideira", "jogo de panelas", "utensilio", "utensilios",
        "faca", "jogo de facas", "talher", "talheres", "prato", "copo", "taca",
        "garrafa termica", "pote", "potes", "marmita", "tabua de corte",
        "organizador", "organizadora", "cabide", "cabides", "prateleira",
        "caixa organizadora", "cesto", "lixeira", "varal", "escorredor",
        "limpeza", "esfregao", "mop", "rodo", "vassoura", "aspirador",
        "robo aspirador", "lavadora", "lava e seca", "lava-loucas",
        "lencol", "jogo de cama", "edredom", "cobertor", "travesseiro",
        "toalha", "toalhas", "colcha", "cortina", "tapete", "almofada",
        "decoracao", "quadro decorativo", "luminaria", "abajur", "vaso",
        "air fryer", "airfryer", "fritadeira", "cafeteira", "cafeteira expresso",
        "nespresso", "dolce gusto", "liquidificador", "batedeira", "mixer",
        "processador de alimentos", "sanduicheira", "grill", "torradeira",
        "chaleira", "panela eletrica", "panela de pressao", "micro-ondas",
        "microondas", "forno eletrico", "fogao", "cooktop", "geladeira",
        "freezer", "purificador", "filtro de agua", "bebedouro",
        "ventilador", "climatizador", "ar condicionado", "ar-condicionado",
        "aquecedor", "umidificador", "ferro de passar", "ferro a vapor",
        "maquina de lavar", "secadora", "cozinha", "banheiro", "quarto",
        "lampada", "lampada inteligente", "lampada led", "fita led",
        "tomada inteligente", "interruptor inteligente", "casa inteligente",
        "smart home", "sonoff", "tuya", "iluminacao", "lustre", "pendente",
        "churrasqueira", "espremedor", "cafeteira italiana", "moedor",
        "balanca de cozinha", "forma de bolo", "forma de silicone", "assadeira",
        "gancho", "gancho adesivo", "suporte de parede", "porta shampoo",
        "sapateira", "porta ovos", "cozedor", "lavanderia",
    ],
    MODA_BELEZA: [
        "camiseta", "camisa", "blusa", "vestido", "calca", "bermuda", "shorts",
        "saia", "jaqueta", "casaco", "moletom", "legging", "pijama", "cueca",
        "calcinha", "sutia", "meia", "meias", "biquini", "maio", "roupa",
        "tenis", "sapato", "sandalia", "chinelo", "bota", "sapatilha",
        "bolsa", "mochila feminina", "carteira", "necessaire", "cinto",
        "relogio", "relogio masculino", "relogio feminino", "pulseira",
        "colar", "brinco", "anel", "oculos de sol", "oculos", "bone", "chapeu",
        "maquiagem", "batom", "base liquida", "corretivo", "rimel", "mascara de cilios",
        "paleta de sombras", "blush", "iluminador", "primer", "pincel de maquiagem",
        "perfume", "colonia", "eau de parfum", "eau de toilette", "body splash",
        "cuidados pessoais", "barbeador", "aparador", "depilador", "escova de dente",
        "escova eletrica", "hidratante", "protetor solar", "desodorante",
        "shampoo", "condicionador", "mascara capilar", "secador de cabelo",
        "secador", "chapinha", "prancha de cabelo", "prancha alisadora", "babyliss",
        "modelador", "cabelo", "cilios", "sobrancelha", "delineador", "gloss",
        "acne", "espinha", "facial", "rosto", "mochila",
        "skincare", "serum", "vitamina c", "acido hialuronico", "esfoliante",
        "tonico facial", "sabonete facial", "creme facial", "anti-idade",
        "esmalte", "unha", "kit manicure", "lingerie", "moda",
    ],
    FERRAMENTAS_AUTO: [
        "alicate", "alicates", "furadeira", "parafusadeira", "furadeira parafusadeira",
        "kit de ferramentas", "jogo de ferramentas", "maleta de ferramentas",
        "caixa de ferramentas", "jogo de chaves", "chave de fenda", "chave phillips",
        "chave combinada", "chave inglesa", "jogo de soquete", "soquete",
        "medidor", "multimetro", "trena", "trena laser", "nivel a laser",
        "nivel laser", "paquimetro", "detector de tensao",
        "serra", "serra tico-tico", "serra circular", "esmerilhadeira",
        "lixadeira", "chave de impacto", "makita", "dewalt", "bosch", "stanley",
        "tramontina", "vonder", "wap", "policorte", "plaina", "tupia",
        "ferro de solda", "estacao de solda", "solda", "pistola de cola",
        "compressor", "compressor de ar", "lavadora de alta pressao",
        "soprador", "rocadeira", "cortador de grama", "motosserra",
        "equipamento eletrico", "disjuntor", "extensao eletrica", "fita isolante",
        "carro", "automotivo", "veicular", "moto", "motocicleta", "capacete",
        "suporte veicular", "suporte para celular carro", "suporte de celular",
        "camera veicular", "dashcam", "camera de re", "central multimidia",
        "carregador veicular", "aspirador automotivo", "calibrador", "macaco hidraulico",
        "cabo de bateria", "bateria automotiva", "pneu", "oleo de motor",
        "limpa para-brisa", "cera automotiva", "capa de volante", "tapete automotivo",
        "oficina", "morsa", "bancada", "esmeril", "torno", "escada", "carrinho de carga",
        "epi", "luva de seguranca", "oculos de protecao", "lanterna", "lanterna tatica",
    ],
    ACHADINHOS: [
        "brinquedo", "brinquedos", "boneca", "boneco", "lego", "quebra-cabeca",
        "jogo de tabuleiro", "carrinho de brinquedo", "pelucia", "infantil",
        "bebe", "mamadeira", "fralda", "carrinho de bebe", "cadeirinha",
        "pet", "cachorro", "gato", "racao", "coleira", "brinquedo para pet",
        "caminha pet", "arranhador", "aquario",
        "academia", "halter", "halteres", "kettlebell", "elastico de exercicio",
        "tapete de yoga", "bicicleta", "ciclismo", "bola de futebol", "futebol",
        "natacao", "camping", "barraca",
        "papelaria", "caneta", "canetas", "caderno", "planner", "marcador",
        "adesivo", "adesivos", "post-it", "estojo", "lapis", "pasta sanfonada",
        "prancheta", "fichario",
        "criativo", "diy", "artesanato", "miniatura", "colecionavel", "action figure",
        "funko", "sazonal", "natal", "pascoa", "halloween", "festa", "presente",
        "kit presente", "gadget", "curioso", "engracado", "viral",
    ],
}

# Achadinhos é o fallback genérico: só vence um tópico específico quando a
# evidência for claramente maior.
_ACHADINHOS_WEIGHT = 0.6

_COMPILED_KEYWORDS: dict[str, list[tuple[str, re.Pattern]]] | None = None


def _normalize(text: str) -> str:
    raw = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in raw if not unicodedata.combining(c))


def _compile(keyword: str) -> re.Pattern:
    # Casa palavra/frase inteira (com plural simples "s"/"es"), evitando que
    # "bone" case com "boneca" ou "pet" com "tapete".
    return re.compile(
        r"(?<![a-z0-9])" + re.escape(keyword) + r"(?:s|es)?(?![a-z0-9])"
    )


def _keywords() -> dict[str, list[tuple[str, re.Pattern]]]:
    global _COMPILED_KEYWORDS
    if _COMPILED_KEYWORDS is None:
        _COMPILED_KEYWORDS = {
            topic: [
                (kw, _compile(kw))
                for kw in sorted({_normalize(k) for k in kws if k}, key=len, reverse=True)
            ]
            for topic, kws in TOPIC_KEYWORDS.items()
        }
    return _COMPILED_KEYWORDS


# Ordem de desempate: tópicos com sinal mais específico primeiro.
_TIE_ORDER = (FERRAMENTAS_AUTO, TECNOLOGIA, CASA_COZINHA, MODA_BELEZA, ACHADINHOS)


def topic_scores(title: str) -> dict[str, int]:
    """Pontua cada tópico físico para o título informado."""
    norm = _normalize(title)
    scores: dict[str, int] = {}
    for topic, kws in _keywords().items():
        total = 0
        for kw, pattern in kws:
            if pattern.search(norm):
                total += len(kw)
        if total:
            if topic == ACHADINHOS:
                total = int(round(total * _ACHADINHOS_WEIGHT))
            scores[topic] = max(1, total)
    return scores


def classify_title(title: str) -> str:
    """Retorna o tópico físico mais provável para o título. Se nada casar,
    retorna ``""`` (o chamador decide o fallback, normalmente Achadinhos)."""
    scores = topic_scores(title)
    if not scores:
        return ""
    best = max(scores.values())
    for topic in _TIE_ORDER:
        if scores.get(topic) == best:
            return topic
    return ""
