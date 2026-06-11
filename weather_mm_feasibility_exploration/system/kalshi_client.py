"""
kalshi_client.py — thin READ-ONLY Kalshi market-data client (no auth).

Shared by the Phase-0 recorder and the Phase-1 simulator. Wraps the public endpoints
with correct parsing of the quirks we discovered:
  - live book is GET /markets/{t}/orderbook -> {"orderbook_fp": {"yes_dollars":[[px,sz]],
    "no_dollars":[[px,sz]]}}.  best YES bid = max(yes_dollars px);
    best YES ask = 1 - max(no_dollars px).
  - market-object yes_bid/volume/open_interest read null -> never use them.
  - trades: count_fp, yes_price_dollars, taker_side ('yes' => taker bought YES),
    created_time, trade_id.
All prices returned as floats in [0,1]; sizes as float contracts.
"""
import json, time
import urllib.request, urllib.error

BASE = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "research/1"}


def _get(path, tries=4):
    url = BASE + path
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503):
                time.sleep(1.0 + i * 1.5)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1.0 + i)
    raise last


def open_markets(series_ticker):
    """Open markets for a series. Returns list of normalized dicts."""
    out, cursor = [], ""
    for _ in range(10):
        path = f"/markets?series_ticker={series_ticker}&status=open&limit=200"
        if cursor:
            path += f"&cursor={cursor}"
        d = _get(path)
        for m in d.get("markets", []):
            out.append(_norm_market(m))
        cursor = d.get("cursor", "")
        if not cursor:
            break
        time.sleep(0.05)
    return out


def market(ticker):
    d = _get(f"/markets/{ticker}")
    return _norm_market(d.get("market", d))


def _norm_market(m):
    return {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "floor": m.get("floor_strike"),
        "cap": m.get("cap_strike"),
        "subtitle": m.get("subtitle") or m.get("yes_sub_title") or "",
        "close_time": m.get("close_time"),
        "status": m.get("status"),
        "result": m.get("result"),
    }


def orderbook(ticker, depth=20):
    """Return normalized book: {ts, yes:[[px,sz]], no:[[px,sz]], yes_bid, yes_ask}.
    yes/no are buy-side resting interest in YES / NO (Kalshi's two-sided book)."""
    d = _get(f"/markets/{ticker}/orderbook?depth={depth}")
    ob = d.get("orderbook_fp") or {}
    yes = [[float(p), float(s)] for p, s in (ob.get("yes_dollars") or [])]
    no = [[float(p), float(s)] for p, s in (ob.get("no_dollars") or [])]
    yes_bid = max((p for p, _ in yes), default=None)        # best bid to BUY yes
    yes_ask = (1.0 - max((p for p, _ in no))) if no else None  # best ask to SELL yes
    return {"ts": time.time(), "yes": yes, "no": no,
            "yes_bid": yes_bid, "yes_ask": yes_ask}


def trades_since(ticker, seen_ids, max_pages=20):
    """Return new trades (not in seen_ids), newest-first paging stopped at first seen.
    Each: {id, t(unix), p(yes_price), c(count), ty(1=taker bought yes)}."""
    out, cursor = [], ""
    for _ in range(max_pages):
        path = f"/markets/trades?ticker={ticker}&limit=1000"
        if cursor:
            path += f"&cursor={cursor}"
        d = _get(path)
        tr = d.get("trades", [])
        hit_seen = False
        for t in tr:
            tid = t.get("trade_id")
            if tid in seen_ids:
                hit_seen = True
                continue
            out.append({
                "id": tid,
                "t": _iso_to_unix(t.get("created_time", "")),
                "p": float(t.get("yes_price_dollars") or 0),
                "c": float(t.get("count_fp") or 0),
                "ty": 1 if t.get("taker_side") == "yes" else 0,
            })
        cursor = d.get("cursor", "")
        if hit_seen or not cursor or not tr:
            break
        time.sleep(0.02)
    return out


def _iso_to_unix(s):
    import datetime as DT
    try:
        return DT.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0
