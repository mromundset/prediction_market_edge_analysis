#!/usr/bin/env python3
"""
B6 v2: Deep cross-market consistency scan — non-sports only

Four detectors hunt for pairs (HARD, EASY) where HARD⊆EASY logically
(HARD happening implies EASY happening) but P(HARD) > P(EASY) at the mid.
That's a probability-axiom violation: sell HARD at bid, buy EASY at ask,
collect net credit with guaranteed non-negative payoffs in every state.

  Payoffs (sell HARD bid, buy EASY ask, net credit = bid_H - ask_E):
    HARD=YES (→ EASY=YES by assumption):   -1 + 1  = 0       → P&L = credit
    HARD=NO,  EASY=YES:                     0 + 1  = +1       → P&L = credit + 1
    HARD=NO,  EASY=NO:                      0 + 0  = 0        → P&L = credit
  Worst case = credit. Risk-free iff credit > fees.

Detectors
  T  Threshold chains      P(X > K_lo) ≥ P(X > K_hi)  for K_lo < K_hi
  H  Time-horizon chains   P(event by T1) ≤ P(event by T2) for T1 < T2
  E  Election/nom chains   P(win election) ≤ P(win nomination)
  N  Count chains          P(≥ N+1 occurrences) ≤ P(≥ N)

Geopolitics markets are fee-free (feeRate=0) → even 0.5pp gross is +EV.
"""
import sys, re, json, time
from collections import defaultdict
import requests

sys.stdout.reconfigure(encoding="utf-8")

# ── Config ───────────────────────────────────────────────────────────────────
GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"
HDRS  = {"User-Agent": "pm-b6v2/1"}

SPORTS_SLUGS = {
    "sports","soccer","nfl","nba","mlb","nhl","ufc","tennis","golf",
    "cricket","f1","nascar","mma","boxing","esports","basketball",
    "football","baseball","hockey","rugby","olympics","cycling",
    "wrestling","swimming","athletics","volleyball","handball",
    "pickleball","lacrosse","skiing","snowboarding","track",
}

# ── Fee helpers ───────────────────────────────────────────────────────────────
def taker_fee(p, rate):
    return rate * p * (1.0 - p)

def cat_fee_rate(tags):
    """Taker fee rate for a market given its event tags."""
    slugs = {(t.get("slug") or "").lower() for t in (tags or [])}
    if "geopolitics" in slugs:
        return 0.0
    if slugs & {"crypto", "cryptocurrency"}:
        return 0.07
    if slugs & {"economics", "weather", "culture", "entertainment", "music", "science"}:
        return 0.05
    return 0.04   # finance / politics / tech default

# ── Data fetching ─────────────────────────────────────────────────────────────
def fetch_events(max_events=9000):
    out = []
    off = 0
    while len(out) < max_events:
        try:
            batch = requests.get(
                f"{GAMMA}/events",
                params={"active": "true", "closed": "false",
                        "limit": 100, "offset": off},
                headers=HDRS, timeout=30,
            ).json()
        except Exception as ex:
            print(f"  [fetch error off={off}] {ex}")
            break
        if not batch:
            break
        out.extend(batch)
        off += 100
        if len(batch) < 100:
            break
        time.sleep(0.05)
    return out

def is_sports(event):
    return any(
        (t.get("slug") or "").lower() in SPORTS_SLUGS
        for t in (event.get("tags") or [])
    )

def parse_markets(event):
    """Return one dict per binary YES/NO market within *event*."""
    fee_rate = cat_fee_rate(event.get("tags"))
    tag_slugs = [(t.get("slug") or "").lower() for t in (event.get("tags") or [])]
    out = []
    for m in (event.get("markets") or []):
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices   = json.loads(m.get("outcomePrices") or "[]")
            toks     = json.loads(m.get("clobTokenIds") or "[]")
        except Exception:
            continue
        # Binary YES/NO only
        if len(outcomes) != 2:
            continue
        if (outcomes[0] or "").strip().lower() != "yes":
            continue
        if not prices or not toks:
            continue
        try:
            mid = float(prices[0])
        except Exception:
            continue
        if not (0.0 < mid < 1.0):
            continue
        out.append({
            "event_slug":  event.get("slug", ""),
            "event_title": event.get("title", ""),
            "question":    (m.get("question") or "").strip(),
            "mid":         mid,
            "liq":         float(m.get("liquidityNum") or 0),
            "tok":         toks[0],
            "fee_rate":    fee_rate,
            "tags":        tag_slugs,
        })
    return out

# ── Shared helpers ────────────────────────────────────────────────────────────
_YEAR_RE  = re.compile(r"\b20\d\d\b")
_MONTH_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
    r"q1|q2|q3|q4)\b", re.I,
)
_STOP_RE  = re.compile(
    r"\b(will|the|a|an|is|be|to|in|of|at|on|for|by|end|year|this|that|"
    r"us|u\.s\.|american|ever|any|some|least|most|more|less|"
    r"time|times|ever|never|all|no)\b",
    re.I,
)

# Known financial / macro variable normalizations
# Map lower-case patterns → canonical key
KNOWN_VARS = [
    (re.compile(r"\bs&p\s*500\b|\bspx\b",     re.I), "sp500"),
    (re.compile(r"\bnasdaq\s*100\b|\bndx\b",   re.I), "nasdaq100"),
    (re.compile(r"\bnasdaq\b",                 re.I), "nasdaq"),
    (re.compile(r"\bdow\s*jones\b|\bdjia\b",   re.I), "djia"),
    (re.compile(r"\brussell\s*2000\b",         re.I), "russell2000"),
    (re.compile(r"\bbitcoin\b|\bbtc\b",        re.I), "btc"),
    (re.compile(r"\bethereum\b|\beth\b",       re.I), "eth"),
    (re.compile(r"\bgold\b|\bxau\b",           re.I), "gold"),
    (re.compile(r"\bcrude\s*oil\b|\bwti\b|\bbrent\b", re.I), "crude_oil"),
    (re.compile(r"\bnatural\s*gas\b",          re.I), "natgas"),
    (re.compile(r"\bcpi\b|\bconsumer\s*price\b|\binflation\b", re.I), "cpi"),
    (re.compile(r"\bunemployment\b|\bjobless\b", re.I), "unemployment"),
    (re.compile(r"\bfed\s*funds?\s*rate\b|\bffr\b", re.I), "fed_rate"),
    (re.compile(r"\b10.year\s*treasury\b|\b10yr\b|\btenor\b", re.I), "t10y"),
    (re.compile(r"\bgdp\b|\beconomic\s*growth\b", re.I), "gdp"),
    (re.compile(r"\bvix\b|\bvolatility\s*index\b", re.I), "vix"),
    (re.compile(r"\bpopular\s*vote\b",         re.I), "popular_vote"),
    (re.compile(r"\bapproval\s*rating\b|\bapproval\b", re.I), "approval"),
    (re.compile(r"\bpoll(?:ing)?\b",           re.I), "polling"),
    (re.compile(r"\btreasury\b",               re.I), "treasury"),
    (re.compile(r"\bsilver\b",                 re.I), "silver"),
    (re.compile(r"\bcopper\b",                 re.I), "copper"),
]

def canonical_var(text):
    for pat, key in KNOWN_VARS:
        if pat.search(text):
            return key
    # Generic fallback: bag of key tokens
    t = _YEAR_RE.sub("", text.lower())
    t = _MONTH_RE.sub("", t)
    t = _STOP_RE.sub(" ", t)
    t = re.sub(r"[^a-z0-9 &%]", " ", t)
    tokens = sorted({w for w in t.split() if len(w) > 1})
    return " ".join(tokens[:6])

def time_bucket(question):
    """Year[-month/quarter] from question, e.g. '2026' or '2026-q4'."""
    yr_m = _YEAR_RE.search(question)
    yr   = yr_m.group() if yr_m else ""
    qm_m = _MONTH_RE.search(question)
    qm   = qm_m.group(1).lower()[:3] if qm_m else ""
    return f"{yr}-{qm}".rstrip("-")

def _make_viol(det, hard, easy, gap_mid, **extra):
    is_geo = ("geopolitics" in hard.get("tags", [])
              or "geopolitics" in easy.get("tags", []))
    return {
        "detector":    det,
        "q_hard":      hard["question"],
        "q_easy":      easy["question"],
        "ev_hard":     hard["event_slug"],
        "ev_easy":     easy["event_slug"],
        "same_event":  hard["event_slug"] == easy["event_slug"],
        "is_geo":      is_geo,
        "mid_hard":    hard["mid"],
        "mid_easy":    easy["mid"],
        "gap_mid":     gap_mid,
        "tok_hard":    hard["tok"],
        "tok_easy":    easy["tok"],
        "fee_hard":    hard["fee_rate"],
        "fee_easy":    easy["fee_rate"],
        "liq_hard":    hard["liq"],
        "liq_easy":    easy["liq"],
        **extra,
    }

# ═══════════════════════════════════════════════════════════════════════
# DETECTOR T — THRESHOLD CHAINS
#
# "Will [X] be above/below [K]?"  Groups by (canonical_var, direction,
# time_bucket). Within each group checks monotone price ordering.
#
# HARD = higher threshold (for "above") = subset event
# EASY = lower  threshold (for "above") = superset event
#
# Arb: sell HARD at bid, buy EASY at ask.
# ═══════════════════════════════════════════════════════════════════════
_THR_RE = re.compile(
    r"^(.*?)\b"
    r"(above|below|over|under|exceed(?:s)?|at\s+least|at\s+most|"
    r"more\s+than|less\s+than|greater\s+than|lower\s+than|higher\s+than|"
    r"reach(?:es)?|hit(?:s)?|surpass(?:es)?|top[s]?|cross(?:es)?|"
    r"breach(?:es)?|breaks?)\s+"
    r"\$?([\d,]+(?:\.\d+)?)\s*(k|K|M|B|%)?"
    r"\b(.*?)$",
    re.I | re.DOTALL,
)
_BELOW_WORDS = {"below", "under", "less than", "lower than", "at most"}

def _thr_template(question, match):
    """
    Replace the matched threshold number+unit with '__' to form a group key.
    Everything else (variable name, resolution date, direction) stays intact.
    This avoids grouping completely different variables together.
    """
    num_start = match.start(3)
    unit_end  = match.end(4) if match.group(4) else match.end(3)
    template  = (question[:num_start].rstrip()
                 + " __ "
                 + question[unit_end:].lstrip())
    template  = re.sub(r"\s+", " ", template.lower().strip())
    # Strip trailing punctuation / question mark
    template  = template.rstrip("?").strip()
    return template

def detect_threshold_chains(markets):
    groups = defaultdict(list)
    for m in markets:
        match = _THR_RE.match(m["question"])
        if not match:
            continue
        pre, direction, num_str, unit, suf = match.groups()
        try:
            val = float(num_str.replace(",", ""))
        except ValueError:
            continue
        unit = (unit or "").strip()
        if unit in ("k", "K"):  val *= 1_000
        elif unit == "M":       val *= 1_000_000
        elif unit == "B":       val *= 1_000_000_000

        dir_norm = ("below"
                    if direction.lower().replace("  ", " ").rstrip("s") in _BELOW_WORDS
                    else "above")

        # KEY FIX: use the question-as-template as the group key instead of
        # canonical_var. This prevents grouping unrelated questions (e.g.
        # "ETH price above $X" and "ETH vol index hits Y") together.
        template = _thr_template(m["question"], match)
        if len(template) < 10:
            continue

        gk = (template, dir_norm)
        groups[gk].append({**m, "threshold": val, "dir": dir_norm})

    viols = []
    for gk, grp in groups.items():
        if len(grp) < 2:
            continue
        grp.sort(key=lambda x: x["threshold"])
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                lo, hi = grp[i], grp[j]   # lo.threshold < hi.threshold
                if gk[1] == "above":
                    # P(>lo) ≥ P(>hi) — violation: lo.mid < hi.mid
                    if lo["mid"] < hi["mid"] - 0.001:
                        viols.append(_make_viol("T", hi, lo,
                                                hi["mid"] - lo["mid"],
                                                thr_hard=hi["threshold"],
                                                thr_easy=lo["threshold"]))
                else:
                    # P(<hi) ≥ P(<lo) — violation: hi.mid < lo.mid
                    if hi["mid"] < lo["mid"] - 0.001:
                        viols.append(_make_viol("T", lo, hi,
                                                lo["mid"] - hi["mid"],
                                                thr_hard=lo["threshold"],
                                                thr_easy=hi["threshold"]))
    viols.sort(key=lambda x: -x["gap_mid"])
    return viols

# ═══════════════════════════════════════════════════════════════════════
# DETECTOR H — TIME-HORIZON CHAINS
#
# "Will X happen by 2026?" vs "Will X happen by 2027?"
# P(by T1) ≤ P(by T2) when T1 < T2 (by T1 ⊆ by T2 in event-space).
# Requires "by" or "before" — NOT "in YYYY" (which means that year only).
#
# HARD = earlier deadline   EASY = later deadline
# ═══════════════════════════════════════════════════════════════════════
_BY_DATE_RE = re.compile(
    r"\b(?:by(?:\s+(?:end(?:\s+of)?|december(?:\s+31)?)?)\s*|"
    r"before\s+(?:end\s+of\s+)?)"
    r"(?:(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2},?\s*)?"
    r"(20\d\d)\b",
    re.I,
)

_MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

_NEGATION_RE = re.compile(
    r"\b(not|won\'t|fail(?:s)?(?:\s+to)?|never|no\s|don\'t|cannot|can\'t|"
    r"without|unable|unlikely)\b",
    re.I,
)

def strip_by_date(question):
    """
    Return (q_key, yyyymm_int, is_negated) or (None, None, None).

    KEY FIXES vs v1:
    1. Extract YYYYMM (not just YYYY) so same-year different-month questions
       are correctly ordered within a group.
    2. Detect negated questions ("not IPO by T") — for these, the ordering
       is REVERSED: P(NOT-X by T1) ≥ P(NOT-X by T2) for T1 < T2 is CORRECT.
       Only flag as violation when the negated question with the LATER deadline
       has a HIGHER mid than the one with the earlier deadline.
    """
    m = _BY_DATE_RE.search(question)
    if not m:
        return None, None, None
    month_str = (m.group(1) or "").lower()
    year      = int(m.group(2))
    month     = _MONTH_MAP.get(month_str, 12)   # default Dec = end-of-year
    yyyymm    = year * 100 + month

    if not (202501 <= yyyymm <= 203212):
        return None, None, None

    is_negated = bool(_NEGATION_RE.search(question))

    # Build group key: replace the full "by [date]" phrase with placeholder
    q_key = _BY_DATE_RE.sub("by_DATE", question, count=1)
    q_key = re.sub(r"[^a-z0-9_ ]", " ", q_key.lower())
    q_key = re.sub(r"\s+", " ", q_key).strip().rstrip("?").strip()
    # Include negation polarity in the key so negated/positive questions
    # don't get grouped together (they have opposite orderings)
    polarity = "neg" if is_negated else "pos"
    q_key = f"{polarity}_{q_key}"
    return q_key, yyyymm, is_negated

def detect_time_horizon_chains(markets):
    groups = defaultdict(list)
    for m in markets:
        q_key, yyyymm, is_negated = strip_by_date(m["question"])
        if q_key is None:
            continue
        groups[q_key].append({**m, "yyyymm": yyyymm, "negated": is_negated})

    viols = []
    for key, grp in groups.items():
        if len(grp) < 2:
            continue
        grp.sort(key=lambda x: x["yyyymm"])
        is_neg = grp[0]["negated"]
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                early, late = grp[i], grp[j]
                if early["yyyymm"] == late["yyyymm"]:
                    continue   # same date → no ordering to check
                if not is_neg:
                    # Positive event: P(by early) ≤ P(by late)
                    # Violation: P(early) > P(late)
                    if early["mid"] > late["mid"] + 0.001:
                        viols.append(_make_viol("H", early, late,
                                                early["mid"] - late["mid"],
                                                yyyymm_hard=early["yyyymm"],
                                                yyyymm_easy=late["yyyymm"]))
                else:
                    # Negated event: P(NOT-X by early) ≥ P(NOT-X by late) is CORRECT.
                    # Violation: P(NOT-X by early) < P(NOT-X by late)
                    # i.e. the later-deadline NOT question is priced HIGHER
                    if late["mid"] > early["mid"] + 0.001:
                        viols.append(_make_viol("H", late, early,
                                                late["mid"] - early["mid"],
                                                yyyymm_hard=late["yyyymm"],
                                                yyyymm_easy=early["yyyymm"]))
    viols.sort(key=lambda x: -x["gap_mid"])
    return viols

# ═══════════════════════════════════════════════════════════════════════
# DETECTOR E — ELECTION / NOMINATION CHAINS
#
# Win-nomination is a necessary condition for win-election in two-party
# systems, so P(win election) ≤ P(win nomination).
#
# HARD = win the general election     EASY = win the nomination/primary
# ═══════════════════════════════════════════════════════════════════════
_NOM_RE = re.compile(
    r"\b(be\s+(?:the\s+)?(?:\w+\s+)?(?:presidential|senate|house|"
    r"gubernatorial|mayoral|congressional|democratic|republican|gop|"
    r"labour|conservative|liberal|green)?\s*(?:nominee|candidate)|"
    r"win\s+(?:the\s+)?(?:\w+\s+)?(?:primary|caucus|nomination)|"
    r"secure\s+(?:the\s+)?nomination)\b",
    re.I,
)
_WIN_OFFICE_RE = re.compile(
    r"\b(win\s+(?:the\s+)?(?:20\d\d\s+)?(?:presidential|senate|house|"
    r"congressional|gubernatorial|mayoral|general)?\s*election|"
    r"(?:win|become|be\s+elected|be\s+(?:the\s+)?next)\s+"
    r"(?:us\s+|u\.s\.\s+)?(?:president|senator|governor|mayor|"
    r"representative|congressman|congresswoman|prime\s+minister|"
    r"chancellor|secretary(?:\s+of\s+state)?))\b",
    re.I,
)

def extract_name_key(question):
    """
    Extract the person's name from "Will [Name] ..." questions.
    Returns the last capitalized token (surname) as the key, lowercased.
    """
    m = re.match(r"[Ww]ill\s+((?:[A-Z][a-zA-Z'\-]+\s*){1,3})", question)
    if not m:
        return None
    name = m.group(1).strip()
    parts = name.split()
    # Reject if the first word looks like a common non-name word
    stop = {"The", "A", "An", "US", "Any", "There", "It", "This",
            "His", "Her", "Their", "My", "Your"}
    if not parts or parts[0] in stop:
        return None
    # Use the FULL name lowercased as the key (most reliable)
    return name.lower()

def detect_election_chains(markets):
    nominees = defaultdict(list)
    wins     = defaultdict(list)
    for m in markets:
        name = extract_name_key(m["question"])
        if not name:
            continue
        if _NOM_RE.search(m["question"]):
            nominees[name].append(m)
        elif _WIN_OFFICE_RE.search(m["question"]):
            wins[name].append(m)

    viols = []
    for person in set(nominees) & set(wins):
        for nom_m in nominees[person]:
            for win_m in wins[person]:
                # P(win office) ≤ P(be nominated) — violation: win > nom
                if win_m["mid"] > nom_m["mid"] + 0.001:
                    viols.append(_make_viol("E", win_m, nom_m,
                                            win_m["mid"] - nom_m["mid"],
                                            person=person))
    viols.sort(key=lambda x: -x["gap_mid"])
    return viols

# ═══════════════════════════════════════════════════════════════════════
# DETECTOR N — COUNT / FREQUENCY CHAINS
#
# "at least N [events/cuts/hikes/attacks/…]" →
#   P(≥ N) ≥ P(≥ N+1) ≥ P(≥ N+2) …
#
# HARD = higher count (≥ N+k)    EASY = lower count (≥ N)
# ═══════════════════════════════════════════════════════════════════════
_COUNT_RE = re.compile(
    r"\bat\s+least\s+(\d+)\b"
    r"|\b(\d+)\s+or\s+more\b"
    r"|\bmore\s+than\s+(\d+)\b"
    r"|\b(\d+)\+\s*(?:times?|cuts?|hikes?|rate\s+cuts?|"
    r"increases?|decreases?|instances?|attacks?|sanctions?|"
    r"rate\s+hikes?|rate\s+increases?)\b",
    re.I,
)

def detect_count_chains(markets):
    groups = defaultdict(list)
    for m in markets:
        match = _COUNT_RE.search(m["question"])
        if not match:
            continue
        n_str = next((g for g in match.groups() if g is not None), None)
        if n_str is None:
            continue
        try:
            n = int(n_str)
        except ValueError:
            continue

        # Build group key: replace count with placeholder, strip year + month
        q_key = _COUNT_RE.sub("_N_", m["question"], count=1)
        q_key = _YEAR_RE.sub("", q_key)
        q_key = re.sub(r"[^a-z0-9_ ]", " ", q_key.lower())
        q_key = re.sub(r"\s+", " ", q_key).strip()
        groups[q_key].append({**m, "count": n})

    viols = []
    for key, grp in groups.items():
        if len(grp) < 2:
            continue
        grp.sort(key=lambda x: x["count"])
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                lo, hi = grp[i], grp[j]   # lo.count < hi.count
                # P(≥lo) ≥ P(≥hi) — violation: lo.mid < hi.mid
                if lo["mid"] < hi["mid"] - 0.001:
                    viols.append(_make_viol("N", hi, lo,
                                            hi["mid"] - lo["mid"],
                                            count_hard=hi["count"],
                                            count_easy=lo["count"]))
    viols.sort(key=lambda x: -x["gap_mid"])
    return viols

# ═══════════════════════════════════════════════════════════════════════
# DETECTOR G — GEOGRAPHIC / SCOPE CONTAINMENT (heuristic)
#
# If question A mentions a specific sub-scope (a city, a country, one
# named actor) and question B mentions the containing scope (a region,
# "any", "at least one"), and the questions are otherwise identical,
# P(A) ≤ P(B).
#
# We implement two concrete sub-cases:
#   G1: "in [country/city]" vs "anywhere" / "in any country" for same event
#   G2: "named person X" vs "any [role]" for same event type
# These are heuristic — check same-event only for reliability.
# ═══════════════════════════════════════════════════════════════════════
_GEO_SPECIFIC_RE = re.compile(
    r"\b(?:in|by|from|within)\s+[A-Z][a-zA-Z]+\b")
_GEO_GENERAL_RE  = re.compile(
    r"\b(?:anywhere|any\s+country|any\s+nation|any\s+state|globally)\b",
    re.I)

def detect_geo_scope_chains(markets):
    """
    Same event, one question has specific geographic scope, another has
    broader "any" or "anywhere" scope.
    """
    by_event = defaultdict(list)
    for m in markets:
        by_event[m["event_slug"]].append(m)

    viols = []
    for slug, grp in by_event.items():
        if len(grp) < 2:
            continue
        specifics = [m for m in grp if _GEO_SPECIFIC_RE.search(m["question"])]
        generals  = [m for m in grp if _GEO_GENERAL_RE.search(m["question"])]
        for spec in specifics:
            for gen in generals:
                if spec["tok"] == gen["tok"]:
                    continue
                # P(specific) ≤ P(general) — violation: spec.mid > gen.mid
                if spec["mid"] > gen["mid"] + 0.001:
                    viols.append(_make_viol("G", spec, gen,
                                            spec["mid"] - gen["mid"]))
    viols.sort(key=lambda x: -x["gap_mid"])
    return viols

# ═══════════════════════════════════════════════════════════════════════
# ORDER-BOOK VERIFICATION
# ═══════════════════════════════════════════════════════════════════════
def verify_at_book(candidates, max_cands=600):
    if not candidates:
        return []

    toks = list({t
                 for c in candidates[:max_cands]
                 for t in [c.get("tok_hard"), c.get("tok_easy")]
                 if t})

    books = {}
    BATCH = 50
    for i in range(0, len(toks), BATCH):
        bat = toks[i : i + BATCH]
        try:
            resp = requests.post(
                f"{CLOB}/books",
                json=[{"token_id": t} for t in bat],
                headers=HDRS, timeout=30,
            ).json()
            for tok, bk in zip(bat, resp):
                bids = bk.get("bids") or []
                asks = bk.get("asks") or []
                books[tok] = {
                    "bid":      float(bids[0]["price"]) if bids else None,
                    "ask":      float(asks[0]["price"]) if asks else None,
                    "bid_size": float(bids[0]["size"])  if bids else 0,
                    "ask_size": float(asks[0]["size"])  if asks else 0,
                }
        except Exception as ex:
            print(f"  [book error] {ex}")
        time.sleep(0.3)

    out = []
    for c in candidates[:max_cands]:
        th, te = c.get("tok_hard"), c.get("tok_easy")
        if not th or not te:
            continue
        bk_h = books.get(th, {})
        bk_e = books.get(te, {})
        bid_h = bk_h.get("bid")
        ask_e = bk_e.get("ask")
        if bid_h is None or ask_e is None:
            continue
        gross = bid_h - ask_e
        net   = (gross
                 - taker_fee(bid_h, c["fee_hard"])
                 - taker_fee(ask_e, c["fee_easy"]))
        out.append({
            **c,
            "bid_hard":      bid_h,
            "ask_easy":      ask_e,
            "bid_hard_size": bk_h.get("bid_size", 0),
            "ask_easy_size": bk_e.get("ask_size", 0),
            "gross":         gross,
            "net":           net,
        })
    return out

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    print("=" * 68)
    print("B6 v2 — Deep cross-market consistency scan (non-sports)")
    print("=" * 68)

    print("\nFetching events from Gamma API ...")
    events = fetch_events(max_events=9000)
    non_sports = [e for e in events if not is_sports(e)]
    print(f"  {len(events)} events fetched, {len(non_sports)} non-sports")

    print("\nParsing binary YES/NO markets ...")
    markets = []
    for e in non_sports:
        markets.extend(parse_markets(e))
    geo_count = sum(1 for m in markets if "geopolitics" in m["tags"])
    print(f"  {len(markets)} binary markets  ({geo_count} geopolitics, fee-free)")

    # ── Run detectors ────────────────────────────────────────────────
    print()
    all_viols = []
    det_results = {}

    detector_list = [
        ("T", "Threshold chains       (P(X>K_lo) ≥ P(X>K_hi))",
         detect_threshold_chains),
        ("H", "Time-horizon chains    (P(by T1) ≤ P(by T2))",
         detect_time_horizon_chains),
        ("E", "Election/nom chains    (P(win) ≤ P(nominated))",
         detect_election_chains),
        ("N", "Count chains           (P(≥N+1) ≤ P(≥N))",
         detect_count_chains),
        ("G", "Geo-scope chains       (P(specific) ≤ P(general))",
         detect_geo_scope_chains),
    ]

    for det, label, func in detector_list:
        viols = func(markets)
        det_results[det] = viols
        all_viols.extend(viols)
        cross = sum(1 for v in viols if not v["same_event"])
        geo   = sum(1 for v in viols if v["is_geo"])
        print(f"[{det}] {label}")
        print(f"     {len(viols):4d} mid-price violations "
              f"({cross} cross-event, {geo} geo/fee-free)")
        for v in viols[:3]:
            flag = " [X]" if not v["same_event"] else "    "
            gflag = "[G]" if v["is_geo"] else "   "
            print(f"     {flag}{gflag} gap={v['gap_mid']:.3f}  "
                  f"{v['q_hard'][:52]:<52}  |  {v['q_easy'][:52]}")
        print()

    # ── Deduplicate ───────────────────────────────────────────────────
    seen, unique = set(), []
    for v in sorted(all_viols, key=lambda x: -x["gap_mid"]):
        key = (v["tok_hard"], v["tok_easy"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)

    cross_unique = [v for v in unique if not v["same_event"]]
    geo_unique   = [v for v in unique if v["is_geo"]]
    print(f"Unique violations (deduped): {len(unique)}")
    print(f"  Cross-event: {len(cross_unique)}")
    print(f"  Geopolitics: {len(geo_unique)}")

    # ── Book verification — prioritize cross-event + geo, but always
    #    include ALL count-chain violations regardless of position ────
    n_viols_all = det_results.get("N", [])
    ordered = (
        sorted([v for v in unique if not v["same_event"] and v["is_geo"]],
               key=lambda x: -x["gap_mid"])
        + sorted([v for v in unique if not v["same_event"] and not v["is_geo"]],
                 key=lambda x: -x["gap_mid"])
        + sorted([v for v in unique if v["same_event"]],
                 key=lambda x: -x["gap_mid"])
    )
    # Ensure all N-detector violations are included (they're often same-event
    # and ranked low, but they're the most semantically genuine violations)
    n_keys = {(v["tok_hard"], v["tok_easy"]) for v in n_viols_all}
    forced = [v for v in n_viols_all
              if (v["tok_hard"], v["tok_easy"]) not in
              {(c["tok_hard"], c["tok_easy"]) for c in ordered[:600]}]
    candidates = ordered[:600] + forced
    print(f"\nFetching live order books for {len(candidates)} candidates ...")
    verified = verify_at_book(candidates)
    print(f"  {len(verified)} books fetched")

    positive    = sorted([v for v in verified if v["net"] > 0],
                          key=lambda x: -x["net"])
    gross_pos   = sorted([v for v in verified if v["gross"] > 0 >= v["net"]],
                          key=lambda x: -x["gross"])
    close       = sorted([v for v in verified if -0.005 < v["net"] <= 0],
                          key=lambda x: -x["net"])

    # ── Results output ────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(f"POSITIVE-NET executable arbs : {len(positive)}")
    print(f"Positive gross (eaten by fee): {len(gross_pos)}")
    print(f"Close misses   (net > -0.5%) : {len(close)}")
    print("=" * 68)

    if positive:
        print("\n─── EXECUTABLE ARBS (net > 0) ─────────────────────────────────")
        for v in positive[:40]:
            xflag = " [CROSS-EVENT]" if not v["same_event"] else ""
            gflag = " [GEO-FREE]"    if v["is_geo"]        else ""
            print(f"\n  [{v['detector']}]{xflag}{gflag}")
            print(f"  SELL(hard): {v['q_hard']}")
            print(f"  BUY(easy):  {v['q_easy']}")
            print(f"  bid(hard)={v['bid_hard']:.4f}  ask(easy)={v['ask_easy']:.4f}")
            print(f"  gross={v['gross']:+.4f}  net={v['net']:+.4f}  "
                  f"liq_hard=${v['liq_hard']:,.0f}  liq_easy=${v['liq_easy']:,.0f}")
            if not v["same_event"]:
                print(f"  events: {v['ev_hard']}  vs  {v['ev_easy']}")

    if gross_pos:
        print("\n─── POSITIVE GROSS (net negative after fees) ───────────────────")
        for v in gross_pos[:20]:
            xflag = " [X]" if not v["same_event"] else ""
            gflag = "[G]"  if v["is_geo"]        else "   "
            print(f"  [{v['detector']}]{xflag}{gflag} "
                  f"gross={v['gross']:+.4f} net={v['net']:+.4f}  "
                  f"{v['q_hard'][:50]}  |  {v['q_easy'][:50]}")

    if close:
        print("\n─── CLOSE MISSES (net in (-0.5%, 0]) ──────────────────────────")
        for v in close[:15]:
            xflag = " [X]" if not v["same_event"] else ""
            gflag = "[G]"  if v["is_geo"]        else "   "
            print(f"  [{v['detector']}]{xflag}{gflag} "
                  f"gross={v['gross']:+.4f} net={v['net']:+.4f}  "
                  f"{v['q_hard'][:50]}  |  {v['q_easy'][:50]}")

    # ── Per-detector top 15 (mid-price, for research) ─────────────────
    print("\n\n" + "=" * 68)
    print("TOP MID-PRICE VIOLATIONS BY DETECTOR (research view)")
    print("  [X]=cross-event  [G]=geopolitics  gap=mid_hard - mid_easy")
    print("=" * 68)
    for det, label, _ in detector_list:
        vs = det_results[det]
        print(f"\n[{det}] {label}  — {len(vs)} total")
        for v in vs[:15]:
            xf = "[X]" if not v["same_event"] else "   "
            gf = "[G]" if v["is_geo"]         else "   "
            print(f"  {xf}{gf} gap={v['gap_mid']:.3f}  "
                  f"{v['q_hard'][:55]:<55}  >  {v['q_easy'][:55]}")

    # ── Save ───────────────────────────────────────────────────────────
    output = {
        "positive_net":   positive,
        "positive_gross": gross_pos,
        "close_misses":   close,
        "all_unique_mid": [v for v in unique[:200]
                           if not v["same_event"]],  # cross-event only
    }
    with open("violations_v2.json", "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"\n\nSaved results to violations_v2.json")
    print(f"  positive_net:   {len(positive)}")
    print(f"  positive_gross: {len(gross_pos)}")
    print(f"  close_misses:   {len(close)}")
    print(f"  cross-event mid violations saved: "
          f"{len([v for v in unique[:200] if not v['same_event']])}")

if __name__ == "__main__":
    main()
