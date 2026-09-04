import sys, re, httpx
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
r = httpx.get("https://store.steampowered.com/search/results/",
    params={"term":"skyrim","start":0,"count":10,"cc":"br","infinite":1,"l":"brazilian"},
    headers={"Accept":"application/json"}, timeout=30)
html = r.json().get("results_html","")
rows = re.findall(r'<a([^>]*)>(.+?)</a>', html, re.DOTALL|re.IGNORECASE)
print("rows:", len(rows))
for attrs, row in rows[:4]:
    t = re.search(r'<span class="title">([^<]+)</span>', row)
    print("=== TITLE:", t.group(1) if t else None)
    prices = re.findall(r'class="([^"]*price[^"]*)"[^>]*>(.{0,120}?)</div>', row, re.DOTALL|re.IGNORECASE)
    for cls, val in prices:
        print("   cls=%r val=%r" % (cls, re.sub(r'\s+',' ',val)[:110]))
