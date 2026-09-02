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
            const selectors = [
                '[class*="coupon" i]',
                '[data-testid*="coupon" i]',
                '[aria-label*="cupom" i]'
            ];
            const texts = [];
            const seen = new Set();
            for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                    const text = (element.innerText || element.textContent ||
                        element.getAttribute('aria-label') || '').trim();
                    if (text && !seen.has(text)) {
                        seen.add(text);
                        texts.push(text);
                    }
                }
            }
            if (texts.length) return texts.join('\n');

            const root = document.querySelector('main') || document.body;
            const lines = root ? (root.innerText || '').split('\n') : [];
            const nearby = [];
            for (let i = 0; i < lines.length; i += 1) {
                if (/cupom|código|resgatar/i.test(lines[i])) {
                    nearby.push(...lines.slice(Math.max(0, i - 2), i + 3));
                }
            }
            return [...new Set(nearby.map(x => x.trim()).filter(Boolean))].join('\n');
        }"""
    ) or ""

_PROMO_TRIGGER_WORDS=("cupom","cupons","ver cupom","ver cupons","aplicar cupom","usar cupom","ativar cupom","resgatar cupom","resgatar cupons")
_BLOCKED_TRIGGER_WORDS=("comprar","finalizar","checkout","carrinho","pagar","adicionar ao carrinho")
def _is_safe_promo_trigger(text: str) -> bool:
    norm=" ".join((text or "").lower().split())
    return bool(norm and len(norm)<=180 and not any(w in norm for w in _BLOCKED_TRIGGER_WORDS) and any(w in norm for w in _PROMO_TRIGGER_WORDS))
def _expand_promotion_elements(page, max_clicks: int = 4) -> int:
    candidates=page.locator("button, a, [role='button'], summary")
    try: count=min(candidates.count(),100)
    except Exception: return 0
    clicked=0; seen=set()
    for idx in range(count):
        if clicked>=max_clicks: break
        item=candidates.nth(idx)
        try: text=(item.inner_text(timeout=350) or "").strip()
        except Exception: continue
        norm=" ".join(text.lower().split())
        if norm in seen or not _is_safe_promo_trigger(text): continue
        seen.add(norm)
        try:
            if not item.is_visible(timeout=250): continue
            item.click(timeout=900); page.wait_for_timeout(450); clicked += 1
        except Exception: continue
    return clicked
def discover_promotions(product_urls: list[str]) -> dict[str, list[promotion_engine.Promotion]]:
    if not product_urls: return {}
    if not USER_DATA_DIR.exists(): raise NotLoggedIn("Sem sessao. Rode: python login_ml.py")
    results={}
    with sync_playwright() as p:
        ctx=_launch(p,headless=False); page=ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i,url in enumerate(product_urls):
                try:
                    page.goto(url,wait_until="domcontentloaded"); page.wait_for_timeout(2300 if i==0 else 1000)
                    if i==0 and not _cookie(ctx,"ssid"): raise NotLoggedIn("Sessao expirou. Rode: python login_ml.py")
                    before=_promotion_text_from_page(page); _expand_promotion_elements(page); after=_promotion_text_from_page(page)
                    results[url]=promotion_engine.parse_mercadolivre_text(before if after==before else f"{before}\n{after}")
                except NotLoggedIn: raise
                except Exception: results[url]=[]
        finally: ctx.close()
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
