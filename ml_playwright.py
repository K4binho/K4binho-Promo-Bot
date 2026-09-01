from pathlib import Path

from playwright.sync_api import sync_playwright

import promotion_engine

USER_DATA_DIR = Path(__file__).parent / "ml_profile"
LINKS_URL = "https://www.mercadolivre.com.br/affiliate-program/api/v2/stripe/user/links"
HOME_URL = "https://www.mercadolivre.com.br/"


class NotLoggedIn(Exception):
    pass


def _launch(p, headless: bool):
    return p.chromium.launch_persistent_context(
        str(USER_DATA_DIR), headless=headless, channel="chrome"
    )


def login() -> None:
    """Abre Chrome visivel. Voce loga na conta ML uma vez. Sessao fica salva em ml_profile/."""
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME_URL)
        print("Faca login na sua conta Mercado Livre na janela aberta.")
        print("Quando estiver logado, feche a janela do navegador.")
        page.wait_for_event("close", timeout=0)
        ctx.close()


def _cookie(ctx, name: str) -> str:
    for c in ctx.cookies():
        if c["name"] == name:
            return c["value"]
    return ""


def _image_from_page(page) -> str | None:
    return page.evaluate(
        """() => {
            const og = document.querySelector('meta[property="og:image"]');
            if (og && og.content) return og.content;
            const el = document.querySelector(
                '.ui-pdp-gallery__figure img, figure.ui-pdp-gallery__figure img, img.ui-pdp-image'
            );
            return el ? (el.src || el.getAttribute('data-src')) : null;
        }"""
    )



def _promotion_text_from_page(page) -> str:
    return page.evaluate(
        """() => {
            const root = document.querySelector('main') || document.body;
            return root ? (root.innerText || '') : '';
        }"""
    ) or ""


def discover_promotions(
    product_urls: list[str],
) -> dict[str, list[promotion_engine.Promotion]]:
    """Abre uma amostra de anúncios e detecta cupons visíveis no texto renderizado.

    Usa a mesma sessão persistente necessária para gerar os links de afiliado.
    Falha de um anúncio não interrompe os demais. O chamador decide cache/TTL.
    """
    if not product_urls:
        return {}
    if not USER_DATA_DIR.exists():
        raise NotLoggedIn("Sem sessao. Rode: python login_ml.py")

    results: dict[str, list[promotion_engine.Promotion]] = {}
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i, url in enumerate(product_urls):
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(2_500 if i == 0 else 1_200)

                    if i == 0 and not _cookie(ctx, "ssid"):
                        raise NotLoggedIn("Sessao expirou. Rode: python login_ml.py")

                    text = _promotion_text_from_page(page)
                    results[url] = promotion_engine.parse_mercadolivre_text(text)
                except NotLoggedIn:
                    raise
                except Exception:
                    results[url] = []
        finally:
            ctx.close()
    return results

def generate_links(
    product_urls: list[str], tag: str
) -> dict[str, tuple[str | None, str | None]]:
    """Retorna {url_produto: (short_url, image_url)}. Reusa a sessao persistente. Chrome visivel."""
    if not USER_DATA_DIR.exists():
        raise NotLoggedIn("Sem sessao. Rode: python login_ml.py")

    results: dict[str, tuple[str | None, str | None]] = {}
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for i, url in enumerate(product_urls):
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3_000 if i == 0 else 1_500)

                if i == 0 and not _cookie(ctx, "ssid"):
                    ctx.close()
                    raise NotLoggedIn("Sessao expirou. Rode: python login_ml.py")

                image = _image_from_page(page)
                csrf = _cookie(ctx, "_csrf")
                result = page.evaluate(
                    """async ({ endpoint, tag, url, csrf }) => {
                        const response = await fetch(endpoint, {
                            method: 'POST',
                            headers: {
                                'content-type': 'application/json',
                                'x-csrf-token': csrf,
                            },
                            body: JSON.stringify({ tag, url }),
                        });
                        return { status: response.status, body: await response.json() };
                    }""",
                    {"endpoint": LINKS_URL, "tag": tag, "url": url, "csrf": csrf},
                )
                if result["status"] in (401, 403):
                    raise NotLoggedIn(
                        f"Sessao invalida ({result['status']}). Rode: python login_ml.py"
                    )
                short = result["body"].get("short_url") if result["status"] == 200 else None
                results[url] = (short, image)
            except NotLoggedIn:
                ctx.close()
                raise
            except Exception as exc:
                print(f"[erro] link {url[:50]}: {exc}")
                results[url] = (None, None)
        ctx.close()
    return results
