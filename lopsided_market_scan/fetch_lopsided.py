"""
fetch_lopsided.py — enumerate ALL active non-sports binary Polymarket markets and
rank them by how lopsided the price is (distance of YES from 0.50).

Strategy context: hunting "impossible meme events" that are not fully priced out, so
the NO side can be bought cheap relative to true (~0) probability. We therefore record
the NO-bet economics (cost, profit-if-NO, gross return) alongside the raw lopsidedness.

Single-source design: one paginated scan of /events (tags + markets embedded inline),
no per-event follow-up requests. Outputs a CSV sorted most-lopsided first.

Run: python3 fetch_lopsided.py
"""
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"

# Tags that mark an event as sports (any one present => excluded).
SPORTS_TAGS = {
    "sports", "soccer", "nfl", "nba", "mlb", "nhl", "epl", "ufc", "mma",
    "boxing", "tennis", "golf", "cricket", "f1", "formula-1", "motorsports",
    "esports", "cfb", "college-football", "college-basketball", "ncaa",
    "fifa-world-cup", "2026-fifa-world-cup", "champions-league", "la-liga",
    "serie-a", "bundesliga", "ligue-1", "olympics", "rugby", "cycling",
    "baseball", "basketball", "football", "hockey", "games",
}

# Keep markets with at least this much lifetime volume (USD) to drop dead/empty ones.
MIN_VOLUME = 500.0


def get(url, timeout=45, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": "research/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    raise last


def prices(market):
    pr = market.get("outcomePrices")
    if not pr:
        return None
    try:
        vals = json.loads(pr) if isinstance(pr, str) else pr
        return [float(x) for x in vals]
    except Exception:  # noqa: BLE001
        return None


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def days_until(iso):
    if not iso:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.strptime(iso, fmt).replace(tzinfo=timezone.utc)
            return round((dt - datetime.now(timezone.utc)).total_seconds() / 86400, 1)
        except ValueError:
            continue
    return None


def scan_events(hard_stop=12000):
    """Paginate every active, open event. Tags + markets are embedded inline."""
    out, off = [], 0
    while off <= hard_stop:
        batch = get(
            f"{GAMMA}/events?limit=100&offset={off}&active=true&closed=false"
            f"&order=volume24hr&ascending=false"
        )
        if not batch:
            break
        out += batch
        off += 100
        print(f"  fetched {len(out)} events (offset {off})...", end="\r")
    print()
    return out


def main():
    print("Scanning all active Polymarket events...")
    events = scan_events()
    print(f"Total events: {len(events)}")

    rows = []
    seen_condition = set()
    for ev in events:
        tag_slugs = {t.get("slug", "").lower() for t in (ev.get("tags") or [])}
        is_sports = bool(tag_slugs & SPORTS_TAGS)
        if is_sports:
            continue
        ev_title = ev.get("title", "")
        ev_slug = ev.get("slug", "")
        tag_str = ",".join(sorted(tag_slugs - {"all"}))

        for m in ev.get("markets") or []:
            # Binary Yes/No only.
            outs = m.get("outcomes")
            if isinstance(outs, str):
                try:
                    outs = json.loads(outs)
                except Exception:  # noqa: BLE001
                    outs = None
            if not outs or [str(o).lower() for o in outs] != ["yes", "no"]:
                continue
            if m.get("closed") or not m.get("active"):
                continue
            cid = m.get("conditionId")
            if cid in seen_condition:
                continue

            pr = prices(m)
            if not pr or len(pr) < 2:
                continue
            yes, no = pr[0], pr[1]

            vol = fnum(m.get("volumeNum")) or fnum(m.get("volume")) or 0.0
            if vol < MIN_VOLUME:
                continue

            seen_condition.add(cid)
            lop = abs(yes - 0.5) * 2.0          # 0 (50/50) .. 1 (fully lopsided)
            heavy = "NO" if yes < 0.5 else "YES"  # which side the crowd is on
            # NO-bet economics: pay `no` per share, collect 1 if it resolves NO.
            no_cost = no
            profit_if_no = round(1.0 - no, 4)
            gross_ret = round((1.0 - no) / no, 4) if no > 0 else None

            best_ask = fnum(m.get("bestAsk"))   # YES-token ask
            best_bid = fnum(m.get("bestBid"))
            # Real cost to BUY NO ~= 1 - bestBid(YES). Real proceeds to short. Approx.
            no_ask = round(1.0 - best_bid, 4) if best_bid is not None else None

            rows.append({
                "lopsided": round(lop, 4),
                "heavy_side": heavy,
                "yes_price": yes,
                "no_price": no,
                "no_cost_mid": round(no_cost, 4),
                "no_cost_ask": no_ask,          # what you'd realistically pay for NO
                "profit_if_no": profit_if_no,
                "gross_return_no": gross_ret,   # profit / cost
                "spread": fnum(m.get("spread")),
                "volume_usd": round(vol, 2),
                "volume_24h": round(fnum(m.get("volume24hr")) or 0.0, 2),
                "liquidity_usd": round(fnum(m.get("liquidityNum")) or 0.0, 2),
                "end_date": m.get("endDateIso") or m.get("endDate"),
                "days_to_resolve": days_until(m.get("endDate")),
                "question": m.get("question", ""),
                "event_title": ev_title,
                "tags": tag_str,
                "event_slug": ev_slug,
                "url": f"https://polymarket.com/event/{ev_slug}",
            })

    # Sort most lopsided first; tie-break on volume (liquid = more actionable).
    rows.sort(key=lambda r: (r["lopsided"], r["volume_usd"]), reverse=True)

    cols = list(rows[0].keys()) if rows else []
    out_path = "lopsided_markets.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} non-sports binary markets to {out_path}")
    print("\nTop 15 most lopsided (toward NO = potential 'impossible event' shorts):")
    no_heavy = [r for r in rows if r["heavy_side"] == "NO"][:15]
    for r in no_heavy:
        print(f"  YES={r['yes_price']:.3f}  ret(NO)={r['gross_return_no']:.1%}  "
              f"vol=${r['volume_usd']:>12,.0f}  {r['question'][:60]}")


if __name__ == "__main__":
    main()
