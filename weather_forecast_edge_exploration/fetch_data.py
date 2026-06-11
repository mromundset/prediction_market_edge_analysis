"""
fetch_data.py — Kalshi daily high-temperature markets vs Open-Meteo ensemble forecast.

Hypothesis (the last untested 'model beats crowd on objective resolution' corner):
Kalshi runs liquid daily city high-temp ladders (KXHIGHNY etc.), resolved on the
official NWS Climatological Report. Weather is the canonical domain where numerical
ensembles beat human intuition. If the Kalshi crowd misprices vs a calibrated
ensemble, that is a real, objective, daily-turnover edge.

This script, per city, per settled day:
  - pulls the MECE bucket ladder + realized bucket (Kalshi `result`)
  - pulls hourly candlesticks per bucket -> market YES bid/ask at a DECISION TIME
    (default: evening before, D-1 22:00 UTC, ~18-20h lead to the afternoon high)
  - pulls the Open-Meteo ensemble (31 GFS members) daily tmax for the date
  - pulls Open-Meteo archive realized tmax (gridded) as a cross-check
Caches everything to cache/.  Pure stdlib.

KEY RISK (the A1 lesson): Open-Meteo's gridded tmax != NWS station high. We store
the raw forecast here; bias-correction to the station happens in analyze.py.
"""
import json, os, time, datetime as DT
import urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

K = "https://api.elections.kalshi.com/trade-api/v2"
HDRS = {"User-Agent": "research/1"}

# city -> (kalshi series, lat, lon, NWS station note)
CITIES = {
    "NYC": ("KXHIGHNY", 40.7790, -73.9693, "Central Park / OKX"),
    "CHI": ("KXHIGHCHI", 41.9742, -87.9073, "O'Hare / LOT"),
    "MIA": ("KXHIGHMIA", 25.7906, -80.3164, "Miami Intl / MFL"),
    "LAX": ("KXHIGHLAX", 33.9416, -118.4085, "LAX / LOX"),
    "AUS": ("KXHIGHAUS", 30.1975, -97.6664, "Austin-Bergstrom / EWX"),
}

DECISION_HOUR_UTC = 22      # D-1 22:00 UTC ~ evening before (primary decision time)
N_DAYS = 60


def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.0 + i)


def cached(name, fn):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    val = fn()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(val, f)
    return val


def kalshi_settled(series):
    """All settled markets for a series (paged)."""
    out, cursor = [], ""
    for _ in range(20):
        url = f"{K}/markets?series_ticker={series}&status=settled&limit=200"
        if cursor:
            url += f"&cursor={cursor}"
        d = fetch(url)
        out += d.get("markets", [])
        cursor = d.get("cursor", "")
        if not cursor:
            break
        time.sleep(0.1)
    return out


def parse_bucket(m):
    """Return (kind, lo, hi) in F.  kind: 'below'(<hi), 'above'(>lo), 'between'[lo,hi]."""
    fl = m.get("floor_strike")
    cap = m.get("cap_strike")
    if fl is not None and cap is not None:
        return ("between", float(fl), float(cap))
    if cap is not None and fl is None:
        return ("below", None, float(cap))     # < cap (subtitle 'X or below')
    if fl is not None and cap is None:
        return ("above", float(fl), None)      # > fl  (subtitle 'X or above')
    return ("?", None, None)


def candle_price_at(series, ticker, dec_ts):
    """Hourly candlesticks; return yes_bid/ask/mid at the candle closing nearest
    (and <=) dec_ts, plus that hour's volume and the market's OI."""
    start = dec_ts - 36 * 3600
    end = dec_ts + 2 * 3600
    url = (f"{K}/series/{series}/markets/{ticker}/candlesticks"
           f"?start_ts={start}&end_ts={end}&period_interval=60")
    try:
        d = fetch(url)
    except Exception:
        return None
    cs = d.get("candlesticks", [])
    best = None
    for c in cs:
        ts = c.get("end_period_ts")
        if ts is None or ts > dec_ts + 3600:
            continue
        yb = (c.get("yes_bid") or {}).get("close_dollars")
        ya = (c.get("yes_ask") or {}).get("close_dollars")
        pr = (c.get("price") or {}).get("close_dollars")
        if yb is None and ya is None and pr is None:
            continue
        if best is None or ts > best["ts"]:
            best = dict(ts=ts, yes_bid=float(yb) if yb else None,
                        yes_ask=float(ya) if ya else None,
                        price=float(pr) if pr else None,
                        oi=float(c.get("open_interest_fp") or 0),
                        vol=float(c.get("volume_fp") or 0))
    return best


def openmeteo_ensemble(lat, lon, date):
    url = (f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max&models=gfs_seamless&temperature_unit=fahrenheit"
           f"&start_date={date}&end_date={date}&timezone=America/New_York")
    d = fetch(url)
    daily = d.get("daily", {})
    keys = [k for k in daily if k.startswith("temperature_2m_max")]
    members = [daily[k][0] for k in keys if daily[k] and daily[k][0] is not None]
    return members


def openmeteo_histforecast(lat, lon, date):
    url = (f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max&temperature_unit=fahrenheit"
           f"&start_date={date}&end_date={date}&timezone=America/New_York")
    d = fetch(url)
    v = d.get("daily", {}).get("temperature_2m_max", [None])
    return v[0] if v else None


def openmeteo_archive(lat, lon, date):
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           f"&daily=temperature_2m_max&temperature_unit=fahrenheit"
           f"&start_date={date}&end_date={date}&timezone=America/New_York")
    d = fetch(url)
    v = d.get("daily", {}).get("temperature_2m_max", [None])
    return v[0] if v else None


def build_city(city):
    series, lat, lon, station = CITIES[city]
    print(f"\n=== {city} ({series}, {station}) ===")
    markets = cached(f"kalshi_settled_{series}.json", lambda: kalshi_settled(series))
    print(f"  {len(markets)} settled markets")

    # group by event date (the measured day).  ticker: SERIES-YYMMMDD-...
    by_event = {}
    for m in markets:
        tk = m.get("ticker", "")
        parts = tk.split("-")
        if len(parts) < 3:
            continue
        datecode = parts[1]                 # e.g. 26JUN09
        by_event.setdefault(datecode, []).append(m)

    # most recent N_DAYS event dates
    def code_to_date(code):
        return DT.datetime.strptime(code, "%y%b%d").date()
    try:
        codes = sorted(by_event, key=code_to_date)[-N_DAYS:]
    except Exception:
        codes = sorted(by_event)[-N_DAYS:]

    rows = []
    for code in codes:
        try:
            d = code_to_date(code)
        except Exception:
            continue
        date_iso = d.isoformat()
        ladder = by_event[code]
        # realized bucket
        realized = [m for m in ladder if m.get("result") == "yes"]
        if not realized:
            continue
        # decision timestamp = D-1 DECISION_HOUR_UTC
        dec_dt = DT.datetime(d.year, d.month, d.day, DECISION_HOUR_UTC,
                             tzinfo=DT.timezone.utc) - DT.timedelta(days=1)
        dec_ts = int(dec_dt.timestamp())

        buckets = []
        for m in ladder:
            kind, lo, hi = parse_bucket(m)
            price = cached(
                f"cdl_{m['ticker']}_{DECISION_HOUR_UTC}.json",
                lambda mm=m: candle_price_at(series, mm["ticker"], dec_ts) or {})
            buckets.append(dict(ticker=m["ticker"], kind=kind, lo=lo, hi=hi,
                                result=m.get("result"), price=price))
        # forecast
        members = cached(f"ens_{city}_{date_iso}.json",
                         lambda: openmeteo_ensemble(lat, lon, date_iso))
        hf = cached(f"hf_{city}_{date_iso}.json",
                    lambda: {"v": openmeteo_histforecast(lat, lon, date_iso)})
        arch = cached(f"arch_{city}_{date_iso}.json",
                      lambda: {"v": openmeteo_archive(lat, lon, date_iso)})
        rows.append(dict(city=city, date=date_iso, buckets=buckets,
                         ens_members=members, hist_forecast=hf.get("v"),
                         archive_tmax=arch.get("v"),
                         realized_tickers=[m["ticker"] for m in realized]))
        time.sleep(0.05)
    print(f"  built {len(rows)} day-rows")
    return rows


def main():
    import sys
    cities = sys.argv[1:] if len(sys.argv) > 1 else ["NYC"]
    all_rows = []
    for c in cities:
        all_rows += build_city(c)
    with open(os.path.join(HERE, "rows.json"), "w", encoding="utf-8") as f:
        json.dump(all_rows, f)
    print(f"\nWrote rows.json: {len(all_rows)} day-rows across {cities}")


if __name__ == "__main__":
    main()
