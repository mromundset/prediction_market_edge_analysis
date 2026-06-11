"""
fetch_forecasts.py — genuine point-in-time day-ahead forecasts per city.

Open-Meteo historical-forecast-api exposes hourly `temperature_2m_previous_day1`
and `_previous_day2`: the forecast for each hour made ~1 / ~2 days earlier. We take
the daily max over local-day hours => an honest ~1-day-ahead (available at the D-1
decision) high-temp forecast.  Cached to cache/leads_<CITY>.json.

Note: api.open-meteo.com is DNS-blocked in this env; historical-forecast-api,
ensemble-api, archive-api resolve fine.
"""
import json, os, time, collections
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
CITIES = {"NYC": (40.7790, -73.9693), "CHI": (41.9742, -87.9073),
          "MIA": (25.7906, -80.3164), "LAX": (33.9416, -118.4085),
          "AUS": (30.1975, -97.6664)}
START, END = "2026-04-10", "2026-06-11"


def fetch(url):
    for _ in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research/1"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2)
    raise RuntimeError("fetch failed: " + url)


def daily_max_from_hourly(times, vals):
    by = collections.defaultdict(list)
    for t, v in zip(times, vals):
        if v is not None:
            by[t[:10]].append(v)
    return {d: max(vs) for d, vs in by.items() if len(vs) >= 20}


def main():
    for city, (lat, lon) in CITIES.items():
        out = os.path.join(CACHE, f"leads_{city}.json")
        if os.path.exists(out):
            print(f"{city}: cached")
            continue
        url = (f"https://historical-forecast-api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               f"&hourly=temperature_2m,temperature_2m_previous_day1,temperature_2m_previous_day2"
               f"&temperature_unit=fahrenheit&start_date={START}&end_date={END}"
               f"&timezone=America/New_York")
        d = fetch(url)
        H = d["hourly"]
        t = H["time"]
        res = {
            "lead0": daily_max_from_hourly(t, H.get("temperature_2m", [])),
            "prev1": daily_max_from_hourly(t, H.get("temperature_2m_previous_day1", [])),
            "prev2": daily_max_from_hourly(t, H.get("temperature_2m_previous_day2", [])),
        }
        with open(out, "w") as f:
            json.dump(res, f)
        print(f"{city}: lead0={len(res['lead0'])} prev1={len(res['prev1'])} prev2={len(res['prev2'])}")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
