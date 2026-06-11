"""PoC: Deribit options-implied P(BTC>K) vs Polymarket daily BTC digitals.
Demonstrates the flagship 'crypto vs options-implied' channel on a live market."""
import json, urllib.request, re, math, datetime as DT
from scipy.stats import norm

def get(u, t=45):
    req = urllib.request.Request(u, headers={"Accept":"application/json","User-Agent":"research/1.0"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)

# --- Polymarket ---
e = get("https://gamma-api.polymarket.com/events/slug/bitcoin-above-on-june-11-2026")
e = e[0] if isinstance(e, list) else e
res_iso = e["markets"][0].get("endDate")            # 2026-06-11T16:00:00Z (Binance 12:00 ET close)
pm = []
for m in e["markets"]:
    pr = json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"]
    mk = re.search(r"\$([\d,]+)", m["question"])
    if not mk:
        continue
    strike = float(mk.group(1).replace(",", ""))
    pm.append((strike, float(pr[0]), m.get("bestAsk"), m.get("bestBid")))
pm.sort()

# --- Deribit ---
idx = get("https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd")["result"]["index_price"]
bs = get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option")["result"]
call_iv = {}
for o in bs:
    p = o["instrument_name"].split("-")
    if len(p) == 4 and p[1] == "11JUN26" and p[3] == "C" and o.get("mark_iv"):
        call_iv[float(p[2])] = o["mark_iv"] / 100.0

now = DT.datetime.now(DT.timezone.utc)
res_dt = DT.datetime.strptime(res_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=DT.timezone.utc)
T = (res_dt - now).total_seconds() / (365 * 86400)   # year-fraction to PM resolution
print(f"BTC index = ${idx:,.0f} | T to PM resolution = {T*365:.2f} days | {len(call_iv)} call IVs (11JUN26)")
print(f"PM resolves: {res_iso} (Binance BTC/USDT 12:00 ET close)\n")

def iv_at(K):
    return call_iv[min(call_iv, key=lambda k: abs(k - K))]

print(f"{'strike':>8} {'PM_yes':>7} {'PM_ask':>7} {'Deribit_N(d2)':>13} {'edge PM-Der':>12}")
edges = []
for strike, yes, ask, bid in pm:
    iv = iv_at(strike)
    d2 = (math.log(idx/strike) - 0.5*iv*iv*T) / (iv*math.sqrt(T))
    p = norm.cdf(d2)
    edges.append((strike, yes, p))
    print(f"{strike:8,.0f} {yes:7.1%} {str(ask):>7} {p:13.1%} {yes-p:+11.1%}")

gaps = [abs(y-p) for _,y,p in edges]
print(f"\nmean |PM - Deribit| = {sum(gaps)/len(gaps):.1%}  (near-the-money strikes most comparable)")
