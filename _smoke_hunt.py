import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv()
import deal_hunter

CREDS = dict(
    aliexpress_app_key=os.getenv("ALIEXPRESS_APP_KEY", ""),
    aliexpress_app_secret=os.getenv("ALIEXPRESS_APP_SECRET", ""),
    aliexpress_tracking_id=os.getenv("ALIEXPRESS_TRACKING_ID", ""),
    shopee_app_id=os.getenv("SHOPEE_APP_ID", ""),
    shopee_app_secret=os.getenv("SHOPEE_APP_SECRET", ""),
)

for q, mp in [("red dead redemption", None), ("palworld", None), ("lego star wars", 100.0)]:
    r = deal_hunter.hunt(q, max_price=mp, **CREDS)
    print("==", q, len(r))
    for x in r[:4]:
        print("   rel=%.2f %-11s %8.2f %s" % (x.relevance, x.source, x.price, x.title[:46]))
