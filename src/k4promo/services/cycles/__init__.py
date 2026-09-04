"""Um ciclo por fonte.

Cada módulo aqui responde por uma pergunta só: *o que esta loja publica neste
ciclo?* A mecânica compartilhada (link, envio, seen, vitrine, analytics,
alertas) fica em ``services.publisher``; as regras de duplicação em
``services.dedup``; a escolha de tópico em ``services.router``.

O Mercado Livre é a exceção e vive em
``providers.mercadolivre.service``: ele tem histórico de preço, descoberta de
cupom por navegador, fallback comercial e revival por promoção, que não se
encaixam no formato das demais lojas.
"""
