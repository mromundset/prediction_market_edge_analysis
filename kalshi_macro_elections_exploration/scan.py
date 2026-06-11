#!/usr/bin/env python3
"""
Kalshi macro + elections cross-venue scan (new angles beyond A2's FOMC focus).

Three hypotheses:
  C3a - Kalshi 2026 US election markets (Senate/House control, state races) vs PM:
        same election result, same resolution source → any price difference is arb.
  C3b - Kalshi commodity/rates daily markets (gold, oil, copper, 10Y yield) vs PM:
        same underlying asset, same date → any gap is arb.
  B5  - PM "How many Fed rate cuts in 2026?" compound distribution vs
        Kalshi KXFEDDECISION per-meeting path probabilities: does the joint distribution
        implied by meeting-level prices match PM's aggregate?
"""

import json, re, sys, io, time
import urllib.request, urllib.parse

# ── helpers ────────────────────────────────────────────────────────────────

def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "research/1"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def safe(fn, default=None):
    try: return fn()
    except: return default

def kalshi_fee(p):
    return 0.07 * p * (1 - p)

def pm_fee_from_tags(tags, p):
    slugs = set(tags)
    if "geopolitics" in slugs: rate = 0.0
    elif slugs & {"crypto","cryptocurrency"}: rate = 0.07
    elif slugs & {"economics","weather","culture","entertainment","music","science"}: rate = 0.05
    else: rate = 0.04  # finance/politics/tech default
    return rate * p * (1 - p), rate

def days_from_now(date_str):
    if not date_str: return 180
    from datetime import date, datetime
    try:
        if "T" in date_str:
            ed = datetime.fromisoformat(date_str.rstrip("Z")).date()
        else:
            ed = date.fromisoformat(date_str[:10])
        return max((ed - date.today()).days, 1)
    except:
        return 180

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PM_GAMMA    = "https://gamma-api.polymarket.com"
PM_HDRS     = {"User-Agent": "research/1"}

# ── Kalshi fetch ────────────────────────────────────────────────────────────

def fetch_kalshi_markets(series, limit=500):
    url = f"{KALSHI_BASE}/markets?series_ticker={series}&status=open&limit={limit}"
    data = safe(lambda: fetch_json(url), {})
    return data.get("markets", [])

def kalshi_mid(m):
    """Return (bid, ask, mid) or None if illiquid."""
    bid = float(m.get("yes_bid") or m.get("yes_bid_dollars") or 0)
    ask = float(m.get("yes_ask") or m.get("yes_ask_dollars") or 0)
    if bid > 1: bid /= 100
    if ask > 1: ask /= 100
    if bid > 0 and ask > 0 and 0 < bid < 1 and 0 < ask <= 1:
        return bid, ask, round((bid + ask) / 2, 4)
    return None

# ── PM fetch ────────────────────────────────────────────────────────────────

def pm_search(keyword, limit=100):
    enc = urllib.parse.quote(keyword)
    url = f"{PM_GAMMA}/events?active=true&closed=false&limit={limit}&keyword={enc}"
    return safe(lambda: fetch_json(url, PM_HDRS), []) or []

def pm_market_prices(m):
    """Return (bid, ask, mid, liq, spread)."""
    try:
        op  = json.loads(m.get("outcomePrices","[]"))
        mid = float(op[0]) if op else None
    except:
        mid = None
    bid    = safe(lambda: float(m.get("bestBid") or 0), 0)
    ask    = safe(lambda: float(m.get("bestAsk") or 1), 1)
    liq    = safe(lambda: float(m.get("liquidityNum") or 0), 0)
    spread = safe(lambda: float(m.get("spread") or 1), 1)
    return bid, ask, mid, liq, spread

def pm_fetch_event(event_id):
    url = f"{PM_GAMMA}/events/{event_id}"
    return safe(lambda: fetch_json(url, PM_HDRS))

# ── Cross-venue arb calculator ──────────────────────────────────────────────

def arb_pair(k_bid, k_ask, pm_bid, pm_ask, pm_tags, days):
    """
    Test both directions. Returns best net arb and annualised return.
      Dir A: sell Kalshi YES at k_bid, buy PM YES at pm_ask
      Dir B: sell PM YES at pm_bid, buy Kalshi YES at k_ask
    """
    _, pm_rate = pm_fee_from_tags(pm_tags, 0.5)  # use rate; recalc per price

    # Dir A: Kalshi YES cheaper → short Kalshi, long PM
    gross_a = k_bid - pm_ask
    net_a   = gross_a - kalshi_fee(k_bid) - pm_rate * pm_ask * (1 - pm_ask)

    # Dir B: PM YES cheaper → short PM, long Kalshi
    gross_b = pm_bid - k_ask
    net_b   = gross_b - pm_rate * pm_bid * (1 - pm_bid) - kalshi_fee(k_ask)

    best    = max(net_a, net_b)
    dir_lbl = "Kalshi→PM" if net_a >= net_b else "PM→Kalshi"
    ann     = best * 365 / max(days, 1)
    return {
        "net_a": round(net_a, 5),
        "net_b": round(net_b, 5),
        "best_net": round(best, 5),
        "direction": dir_lbl,
        "annualized": round(ann, 4),
        "mid_gap": round(abs((k_bid+k_ask)/2 - (pm_bid+pm_ask)/2) if pm_bid and pm_ask else 0, 4),
    }

# ── Section C3a: US elections ────────────────────────────────────────────────

def run_elections():
    print("\n" + "=" * 70)
    print("C3a: US 2026 ELECTION MARKETS")
    print("=" * 70)

    # Kalshi election series
    ELECTION_SERIES = {
        "CONTROLS":   "US Senate control 2026",
        "CONTROLH":   "US House control 2026",
        "GOVPARTYCA": "California governor 2026",
        "GOVPARTYFL": "Florida governor 2026",
        "GOVPARTYTX": "Texas governor 2026",
        "SENATEGA":   "Georgia Senate 2026",
        "SENATEME":   "Maine Senate 2026",
        "SENATEMN":   "Minnesota Senate 2026",
        "SENATENM":   "New Mexico Senate 2026",
        "SENATECT":   "Connecticut Senate 2026",
    }

    print("\n-- Kalshi liquid election markets --")
    kalshi_elections = {}
    for series, desc in ELECTION_SERIES.items():
        markets = fetch_kalshi_markets(series)
        time.sleep(0.15)
        for m in markets:
            prices = kalshi_mid(m)
            if not prices: continue
            ticker = m.get("ticker","")
            kalshi_elections[ticker] = {
                "series": series,
                "desc":   desc,
                "title":  m.get("title",""),
                "bid":    prices[0],
                "ask":    prices[1],
                "mid":    prices[2],
            }
            print(f"  {ticker:<40s}  bid={prices[0]:.3f} ask={prices[1]:.3f}  {m.get('title','')[:60]}")

    # PM election searches
    PM_ELECTION_QUERIES = [
        "Republicans Senate 2026",
        "Democrats Senate 2026",
        "Republicans House 2026",
        "Democrats House 2026",
        "Senate majority 2026",
        "House majority 2026",
        "Senate control 2026",
        "House control 2026",
        "California governor",
        "Florida governor 2026",
        "Texas governor 2026",
        "Georgia Senate 2026",
        "Maine Senate 2026",
        "Minnesota Senate 2026",
        "midterm 2026",
    ]
    print("\n-- PM election markets found --")
    pm_elec_markets = {}
    seen_events = set()
    for q in PM_ELECTION_QUERIES:
        events = pm_search(q, limit=50)
        for ev in events:
            slug = ev.get("slug","")
            if slug in seen_events: continue
            seen_events.add(slug)
            tags = [t.get("slug","") for t in ev.get("tags",[])]
            for m in ev.get("markets",[]):
                cid = m.get("conditionId") or m.get("id","")
                if not cid or cid in pm_elec_markets: continue
                m["_event_slug"]  = slug
                m["_event_title"] = ev.get("title","")
                m["_tags"] = tags
                pm_elec_markets[cid] = m
        time.sleep(0.1)

    for cid, m in sorted(pm_elec_markets.items(),
                         key=lambda x: -(x[1].get("liquidityNum") or 0))[:30]:
        bid, ask, mid, liq, _ = pm_market_prices(m)
        q = m.get("question") or m.get("title","")
        print(f"  mid={mid:.3f}  bid={bid:.3f}  ask={ask:.3f}  liq=${liq:.0f}  | {q[:80]}")

    # Manual matching: Kalshi ↔ PM for US congressional control
    print("\n-- C3a Manual match: Congressional control --")
    MANUAL_MATCHES = [
        # (label, kalshi_ticker, pm_search_term, pm_yes_means)
        ("Senate-R-2026", "CONTROLS-2026-R", "Republicans control Senate 2026", "YES=R"),
        ("House-R-2026",  "CONTROLH-2026-R", "Republicans win House 2026",      "YES=R"),
        ("Senate-D-2026", "CONTROLS-2026-D", "Democrats control Senate 2026",   "YES=D"),
        ("House-D-2026",  "CONTROLH-2026-D", "Democrats win House 2026",         "YES=D"),
    ]

    results = []
    for label, k_ticker, pm_q, note in MANUAL_MATCHES:
        k_data = kalshi_elections.get(k_ticker)
        if not k_data:
            print(f"  {label}: Kalshi market not found")
            continue

        pm_events = pm_search(pm_q, limit=50)
        time.sleep(0.1)
        best_pm = None
        best_pm_q = ""
        best_liq  = 0
        for ev in pm_events:
            for m in ev.get("markets",[]):
                bid, ask, mid, liq, _ = pm_market_prices(m)
                q = (m.get("question") or m.get("title","")).lower()
                if not mid or not bid: continue
                # Must mention both key terms
                key = pm_q.lower()
                if liq > best_liq and any(kw in q for kw in ["senate","house"]) \
                   and any(kw in q for kw in ["republican","democrat","2026"]):
                    best_liq = liq
                    best_pm  = m
                    best_pm_q = m.get("question") or m.get("title","")

        if best_pm is None:
            print(f"  {label}: no matching PM market found (searched: '{pm_q}')")
            continue

        pm_bid, pm_ask, pm_mid, pm_liq, _ = pm_market_prices(best_pm)
        tags  = best_pm.get("_tags",[])
        days  = days_from_now(best_pm.get("endDate") or best_pm.get("endDateIso",""))
        arb   = arb_pair(k_data["bid"], k_data["ask"], pm_bid, pm_ask, tags, days)

        print(f"\n  {label}:")
        print(f"    Kalshi {k_ticker}: bid={k_data['bid']:.3f} ask={k_data['ask']:.3f} mid={k_data['mid']:.3f}")
        print(f"    PM:    '{best_pm_q[:75]}'")
        print(f"           bid={pm_bid:.3f} ask={pm_ask:.3f} mid={pm_mid} liq=${pm_liq:.0f}")
        print(f"    mid_gap={arb['mid_gap']*100:.1f}pp  best_net={arb['best_net']*100:.2f}%  "
              f"({arb['annualized']*100:.1f}%/yr)  dir={arb['direction']}  days={days}")
        results.append({**arb, "label": label, "k_ticker": k_ticker,
                        "pm_question": best_pm_q, "days": days})

    return results

# ── Section C3b: Commodity + rates daily markets ─────────────────────────────

def run_commodities():
    print("\n" + "=" * 70)
    print("C3b: COMMODITY + RATES MARKETS (KALSHI daily vs PM)")
    print("=" * 70)

    SERIES = {
        "KXBRENTD":  ("oil",   "Brent crude"),
        "KXCOPPERD": ("copper","Copper"),
        "KXGOLDD":   ("gold",  "Gold"),
        "KXNOTE10":  ("Treasury yield", "10-year Treasury"),
    }

    results = []
    for series, (kw, desc) in SERIES.items():
        k_markets = fetch_kalshi_markets(series)
        time.sleep(0.15)
        liquid = [(m, kalshi_mid(m)) for m in k_markets if kalshi_mid(m)]
        print(f"\n  {series}: {len(liquid)} liquid markets")
        if liquid:
            # Show a sample
            for m, prices in liquid[:3]:
                print(f"    {m.get('ticker',''):<50s}  bid={prices[0]:.3f} ask={prices[1]:.3f}  {m.get('title','')[:55]}")

        # Search PM for matching markets
        pm_events = pm_search(kw + " 2026", limit=100) + pm_search(desc, limit=50)
        time.sleep(0.2)
        pm_markets = []
        seen = set()
        for ev in pm_events:
            tags = [t.get("slug","") for t in ev.get("tags",[])]
            for m in ev.get("markets",[]):
                cid = m.get("conditionId","")
                if cid in seen: continue
                seen.add(cid)
                bid, ask, mid, liq, _ = pm_market_prices(m)
                if not mid or not bid: continue
                m["_tags"] = tags
                pm_markets.append(m)

        pm_markets.sort(key=lambda m: -(m.get("liquidityNum") or 0))
        if pm_markets:
            print(f"  PM {desc} markets found: {len(pm_markets)}")
            for m in pm_markets[:5]:
                bid, ask, mid, liq, _ = pm_market_prices(m)
                q = m.get("question") or m.get("title","")
                print(f"    mid={mid:.3f}  bid={bid:.3f}  ask={ask:.3f}  liq=${liq:.0f}  | {q[:70]}")
        else:
            print(f"  PM {desc} markets: NONE FOUND")

        # For 10Y Treasury: try to find exact resolution-date match
        if series == "KXNOTE10" and liquid and pm_markets:
            print(f"\n  -- KXNOTE10 specific pairs --")
            for km, kp in liquid[:5]:
                k_title = km.get("title","")
                k_num_match = re.search(r"([\d.]+)%?\s*$", k_title)
                if not k_num_match: continue
                k_thresh = float(k_num_match.group(1))
                for pm in pm_markets[:10]:
                    q = (pm.get("question") or pm.get("title","")).lower()
                    pm_nums = [float(x.replace(",","")) for x in re.findall(r"[\d.]+", q)
                               if 3 <= float(x.replace(",","")) <= 6]
                    if not pm_nums: continue
                    closest = min(pm_nums, key=lambda x: abs(x - k_thresh))
                    if abs(closest - k_thresh) < 0.1:  # within 0.1%
                        pb, pa, pm_mid, pl, _ = pm_market_prices(pm)
                        tags = pm.get("_tags",[])
                        days = days_from_now(pm.get("endDate") or pm.get("endDateIso",""))
                        arb  = arb_pair(kp[0], kp[1], pb, pa, tags, days)
                        print(f"  Kalshi: {k_title[:55]}  bid={kp[0]:.3f} ask={kp[1]:.3f}")
                        print(f"  PM:     {(pm.get('question') or pm.get('title',''))[:55]}")
                        print(f"          bid={pb:.3f} ask={pa:.3f} mid={pm_mid} liq=${pl:.0f}")
                        print(f"  mid_gap={arb['mid_gap']*100:.1f}pp  "
                              f"best_net={arb['best_net']*100:.2f}%  "
                              f"({arb['annualized']*100:.1f}%/yr)")
                        results.append({**arb, "label": f"{series}-{k_thresh}",
                                        "pm_question": pm.get("question","")})

    return results

# ── Section B5: Fed compound distribution ────────────────────────────────────

def run_b5_fed():
    print("\n" + "=" * 70)
    print("B5: FED COMPOUND DISTRIBUTION (Kalshi path vs PM aggregate)")
    print("=" * 70)

    # Get all Kalshi KXFEDDECISION markets
    all_fed = fetch_kalshi_markets("KXFEDDECISION", limit=500)
    time.sleep(0.2)

    # Parse by meeting date and action type
    MEETING_RE = re.compile(r"KXFEDDECISION-(\d{2}[A-Z]{3})-([A-Z0-9]+)")
    MONTH_ORDER = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
                   "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}

    meetings = {}
    for m in all_fed:
        ticker = m.get("ticker","")
        match  = MEETING_RE.match(ticker)
        if not match: continue
        date_code = match.group(1)  # e.g. "26JUN"
        action    = match.group(2)  # e.g. "C25", "H0", "H25"
        year_short = int(date_code[:2])
        mon_str    = date_code[2:]
        year = 2000 + year_short
        mon  = MONTH_ORDER.get(mon_str, 0)
        yyyymm = year * 100 + mon

        prices = kalshi_mid(m)
        if not prices: continue

        if yyyymm not in meetings:
            meetings[yyyymm] = {}
        meetings[yyyymm][action] = {
            "ticker": ticker,
            "title":  m.get("title",""),
            "bid":    prices[0],
            "ask":    prices[1],
            "mid":    prices[2],
        }

    print(f"\n  KXFEDDECISION meetings with liquid markets: {len(meetings)}")
    print(f"  Dates: {sorted(meetings.keys())}")

    # Filter to 2026 remaining meetings (today = Jun 11, 2026 → include Jun 2026 onward)
    future_2026 = {k: v for k, v in meetings.items() if 202606 <= k <= 202612}
    all_2026    = {k: v for k, v in meetings.items() if 202600 <= k <= 202699}

    print(f"\n  2026 meetings (all):    {sorted(all_2026.keys())}")
    print(f"  2026 meetings (future): {sorted(future_2026.keys())}")

    print("\n  -- Per-meeting action breakdown (2026) --")
    for yyyymm in sorted(all_2026.keys()):
        actions = all_2026[yyyymm]
        label = f"{yyyymm//100}-{yyyymm%100:02d}"
        cut25 = actions.get("C25", {}).get("mid", 0)
        cut26 = actions.get("C26", {}).get("mid", 0)
        hike25= actions.get("H25", {}).get("mid", 0)
        hike26= actions.get("H26", {}).get("mid", 0)
        hold  = actions.get("H0",  {}).get("mid", 0)
        p_cut = cut25 + cut26
        p_hike= hike25 + hike26
        p_hold_implied = 1 - p_cut - p_hike  # implied from others
        print(f"  {label}: P(cut)={p_cut:.3f}  P(hold)={hold:.3f}  P(hike)={p_hike:.3f}  "
              f"(sum={p_cut+hold+p_hike:.3f})")

    # Independence model for future 2026 meetings
    print("\n  -- Independence model: P(k total cuts, Jun-Dec 2026) --")
    cut_probs = []
    for yyyymm in sorted(future_2026.keys()):
        actions = future_2026[yyyymm]
        p_cut = (actions.get("C25",{}).get("mid",0) +
                 actions.get("C26",{}).get("mid",0))
        cut_probs.append((yyyymm, p_cut))
        print(f"    {yyyymm}: P(cut)={p_cut:.3f}")

    if cut_probs:
        probs = [p for _, p in cut_probs]
        n = len(probs)
        dp = [0.0] * (n + 1)
        dp[0] = 1.0
        for p in probs:
            new_dp = [0.0] * (n + 1)
            for k in range(n + 1):
                if dp[k] == 0: continue
                if k < n: new_dp[k + 1] += dp[k] * p
                new_dp[k] += dp[k] * (1 - p)
            dp = new_dp
        print(f"\n  Kalshi-path-implied P(k cuts remaining in 2026):")
        for k in range(min(7, n + 1)):
            print(f"    P({k}) = {dp[k]:.4f}")

        # Context: how many cuts already in 2026?
        # Jan/Mar/May meetings should have resolved.
        past_2026 = sorted(k for k in all_2026 if k < 202606)
        print(f"\n  Already-resolved 2026 meetings: {past_2026}")
        print("  (We don't have the resolution outcome from the Kalshi API directly;")
        print("   assuming Fed held rates at all past 2026 meetings based on market context.)")

    # Get PM's "How many cuts in 2026?" event
    print("\n  -- PM compound Fed-cuts market --")
    pm_fed_event = pm_fetch_event(51456)  # known event ID from prior scan
    if not pm_fed_event:
        pm_fed_events = pm_search("rate cuts 2026", limit=30)
        pm_fed_event  = next((e for e in pm_fed_events
                              if "cut" in (e.get("title","")).lower() and "2026" in (e.get("title",""))),
                             None)
    if pm_fed_event:
        print(f"  Event: {pm_fed_event.get('title','')}")
        pm_dist = {}
        for m in pm_fed_event.get("markets",[]):
            q   = m.get("question") or m.get("title","")
            bid, ask, mid, liq, _ = pm_market_prices(m)
            if mid is None: continue
            # Extract the cut count from the question
            match = re.search(r"(\d+)\s+(?:or more\s+)?Fed rate cut", q, re.I)
            if not match:
                match = re.search(r"(?:no|zero|0)\s+Fed rate cut", q, re.I)
                if match:
                    k = 0
                else:
                    k = -1
            else:
                k = int(match.group(1))
            print(f"  k={k:2d}  mid={mid:.4f}  bid={bid:.4f}  ask={ask:.4f}  liq=${liq:.0f}  | {q[:60]}")
            pm_dist[k] = {"mid": mid, "bid": bid, "ask": ask, "liq": liq}

        # B5 comparison: PM vs Kalshi-implied
        if cut_probs and pm_dist:
            print("\n  -- B5 Comparison (PM vs Kalshi-path-implied, REMAINING meetings) --")
            print("  NOTE: PM distribution is 'cuts in full 2026'. Kalshi gives remaining")
            print("        (Jun-Dec) cut probabilities. If Fed held at Jan/Mar/May,")
            print("        Kalshi-path-implied and PM distributions should match.\n")
            for k in sorted(pm_dist.keys()):
                if k < 0: continue
                pm_mid = pm_dist[k]["mid"]
                k_implied = dp[k] if k < len(dp) else sum(dp[k:])
                gap = pm_mid - k_implied
                print(f"  k={k:2d}: PM_mid={pm_mid:.4f}  Kalshi_implied={k_implied:.4f}  "
                      f"gap={gap:+.4f} ({gap*100:+.1f}pp)")

            # Key metric: PM P(0 cuts) vs Kalshi P(0 cuts remaining)
            pm_p0  = pm_dist.get(0, {}).get("mid", None)
            k_p0   = dp[0] if dp else None
            if pm_p0 and k_p0:
                gap = pm_p0 - k_p0
                print(f"\n  KEY: PM P(0 cuts in 2026) = {pm_p0:.4f}")
                print(f"       Kalshi path P(0 cuts remaining) = {k_p0:.4f}")
                print(f"       Gap = {gap*100:+.1f}pp")
                if abs(gap) > 0.05:
                    print("  *** LARGE GAP — potential B5 opportunity, verify resolution definitions ***")
                else:
                    print("  Gap within 5pp — consistent (no edge)")
    else:
        print("  PM cuts-in-2026 event: not found")

    return {}

# ── Section: Kalshi election races detailed ──────────────────────────────────

def run_individual_races():
    print("\n" + "=" * 70)
    print("C3a (detail): INDIVIDUAL SENATE/GOV RACES")
    print("=" * 70)

    RACES = [
        ("SENATEGA",  "2026", "Georgia Senate 2026 Democrats"),
        ("SENATEME",  "2026", "Maine Senate 2026"),
        ("SENATEMN",  "2026", "Minnesota Senate 2026"),
        ("SENATENM",  "2026", "New Mexico Senate 2026"),
        ("GOVPARTYCA","2026", "California governor 2026"),
        ("GOVPARTYFL","2026", "Florida governor 2026"),
        ("GOVPARTYTX","2026", "Texas governor 2026"),
    ]

    results = []
    for series, year_filter, pm_query in RACES:
        k_markets = fetch_kalshi_markets(series)
        time.sleep(0.15)
        liquid = [(m, kalshi_mid(m)) for m in k_markets
                  if kalshi_mid(m) and year_filter in m.get("ticker","")]
        if not liquid:
            print(f"\n  {series}: no liquid markets for {year_filter}")
            continue

        pm_events = pm_search(pm_query, limit=50)
        time.sleep(0.1)
        pm_best = None
        pm_best_liq = 0
        for ev in pm_events:
            tags = [t.get("slug","") for t in ev.get("tags",[])]
            for m in ev.get("markets",[]):
                bid, ask, mid, liq, _ = pm_market_prices(m)
                if liq > pm_best_liq and mid:
                    pm_best = m
                    pm_best["_tags"] = tags
                    pm_best_liq = liq

        print(f"\n  {series} ({year_filter}):")
        for km, kp in liquid:
            print(f"    Kalshi: {km.get('ticker',''):<40s} bid={kp[0]:.3f} ask={kp[1]:.3f}  "
                  f"{km.get('title','')[:50]}")

        if pm_best:
            pb, pa, pm_mid, pl, _ = pm_market_prices(pm_best)
            tags  = pm_best.get("_tags",[])
            days  = days_from_now(pm_best.get("endDate") or pm_best.get("endDateIso",""))
            print(f"    PM:    '{(pm_best.get('question') or pm_best.get('title',''))[:70]}'")
            print(f"           bid={pb:.3f} ask={pa:.3f} mid={pm_mid}  liq=${pl:.0f}  days={days}")

            # Only compare if Kalshi and PM markets seem to be the same direction (both YES=same party wins)
            for km, kp in liquid:
                arb = arb_pair(kp[0], kp[1], pb, pa, tags, days)
                print(f"    Arb ({km.get('ticker','')} vs PM):")
                print(f"      mid_gap={arb['mid_gap']*100:.1f}pp  "
                      f"net={arb['best_net']*100:.2f}%  "
                      f"({arb['annualized']*100:.1f}%/yr)  dir={arb['direction']}")
                results.append({**arb, "series": series, "k_ticker": km.get("ticker"),
                                "pm_q": pm_best.get("question",""), "days": days})
        else:
            print(f"    PM: no matching market found for '{pm_query}'")

    return results

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    election_results = run_elections()
    commodity_results = run_commodities()
    b5_results = run_b5_fed()
    race_results = run_individual_races()

    all_results = election_results + commodity_results + race_results
    all_results.sort(key=lambda r: r.get("best_net", r.get("annualized", -99)), reverse=True)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    positive = [r for r in all_results if r.get("best_net", 0) > 0]
    print(f"\n  Total pairs analysed: {len(all_results)}")
    print(f"  Positive net arb:     {len(positive)}")
    if positive:
        print("\n  *** POSITIVE NET ARBS ***")
        for r in positive:
            ann = r.get("annualized", 0)
            print(f"    {r.get('label', r.get('series', r.get('k_ticker','?'))[:30]):<35s}  "
                  f"net={r['best_net']*100:.2f}%  ({ann*100:.1f}%/yr)  dir={r.get('direction','')}  "
                  f"days={r.get('days',r.get('days_to_expiry','?'))}")
    else:
        print("\n  No positive net arbs found.")

    with open("results_c3.json", "w") as f:
        json.dump({"positive": positive, "all": all_results}, f, indent=2)
    print("\nSaved results_c3.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())
