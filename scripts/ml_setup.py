"""Troca o code do OAuth do Mercado Livre por um token e salva ml_token.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from k4promo.config import Config  # noqa: E402
from k4promo.providers.mercadolivre.oauth import exchange_code  # noqa: E402

REDIRECT_URI = "https://httpbin.org/get"


def main() -> None:
    cfg = Config()
    if not cfg.ml_client_id or not cfg.ml_client_secret:
        print("Preencha ML_CLIENT_ID e ML_CLIENT_SECRET no .env primeiro.")
        print("Crie a app em: https://developers.mercadolivre.com.br/")
        print(f"Use este Redirect URI na app: {REDIRECT_URI}")
        sys.exit(1)

    auth_url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={cfg.ml_client_id}"
        f"&redirect_uri={REDIRECT_URI}"
    )
    print("1. Abra este link no navegador (logado na sua conta ML):")
    print(f"\n   {auth_url}\n")
    print("2. Autorize. Voce sera redirecionado para uma URL que contem ?code=...")
    print("3. Copie o valor do 'code' da URL e cole abaixo.\n")

    code = input("Cole o code aqui: ").strip()
    if not code:
        print("Nenhum code informado. Abortado.")
        sys.exit(1)

    data = exchange_code(cfg.ml_client_id, cfg.ml_client_secret, code, REDIRECT_URI)
    print("\nToken salvo em ml_token.json.")
    print(f"access_token expira em {data.get('expires_in')}s (refresh automatico ativo).")
    print("Agora rode: python bot.py --once")


if __name__ == "__main__":
    main()
