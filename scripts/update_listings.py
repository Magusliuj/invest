#!/usr/bin/env python3
"""
Bay Area Real Estate — Daily Data Updater
Fetches median prices, market stats, and recent listings from Redfin
for each tracked ZIP code. Saves results to data/latest.json and
data/history/YYYY-MM-DD.json.

Run:  python3 scripts/update_listings.py
Deps: pip install requests
"""

import json
import os
import time
import re
from datetime import date, datetime
from pathlib import Path

import requests

# ── Configuration ────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
ROOT        = SCRIPT_DIR.parent
DATA_DIR    = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_PATH = DATA_DIR / "latest.json"

DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
})

# ── ZIP Registry ─────────────────────────────────────────────────────────────
# tier: 1=top, 2=good, 3=mixed, 4=peripheral
# landmark ZIPs (airports, universities) are excluded from price tracking

ZIPS = {
    # Tier 1
    "94027": {"city": "Atherton",         "tier": 1},
    "94022": {"city": "Los Altos",        "tier": 1},
    "94024": {"city": "Los Altos Hills",  "tier": 1},
    "94028": {"city": "Portola Valley",   "tier": 1},
    "94062": {"city": "Woodside",         "tier": 1},
    "94301": {"city": "Palo Alto",        "tier": 1},
    "94303": {"city": "Palo Alto",        "tier": 1},
    "94304": {"city": "Palo Alto",        "tier": 1},
    "94306": {"city": "Palo Alto",        "tier": 1},
    "95014": {"city": "Cupertino",        "tier": 1},
    "95070": {"city": "Saratoga",         "tier": 1},
    "94010": {"city": "Hillsborough",     "tier": 1},
    # Tier 2
    "94025": {"city": "Menlo Park",       "tier": 2},
    "95030": {"city": "Los Gatos",        "tier": 2},
    "95032": {"city": "Los Gatos",        "tier": 2},
    "94040": {"city": "Mountain View",    "tier": 2},
    "94041": {"city": "Mountain View",    "tier": 2},
    "94043": {"city": "Mountain View",    "tier": 2},
    "94087": {"city": "Sunnyvale",        "tier": 2},
    "94086": {"city": "Sunnyvale",        "tier": 2},
    "94085": {"city": "Sunnyvale",        "tier": 2},
    "94089": {"city": "Sunnyvale",        "tier": 2},
    "95129": {"city": "West San Jose",    "tier": 2},
    "94401": {"city": "San Mateo",        "tier": 2},
    "94402": {"city": "San Mateo",        "tier": 2},
    "94403": {"city": "San Mateo",        "tier": 2},
    "94114": {"city": "Noe Valley SF",    "tier": 2},
    "94115": {"city": "Pacific Heights",  "tier": 2},
    "94065": {"city": "Redwood Shores",   "tier": 2},
    "94070": {"city": "San Carlos",       "tier": 2},
    "94002": {"city": "Belmont",          "tier": 2},
    "94030": {"city": "Millbrae",         "tier": 2},
    "94103": {"city": "SoMa SF",          "tier": 2},
    "94107": {"city": "Mission Bay SF",   "tier": 2},
    "94105": {"city": "Embarcadero SF",   "tier": 2},
    "94158": {"city": "Mission Bay SF",   "tier": 2},
    # Tier 3
    "95051": {"city": "Santa Clara",      "tier": 3},
    "95050": {"city": "Santa Clara",      "tier": 3},
    "95054": {"city": "Santa Clara",      "tier": 3},
    "94539": {"city": "Fremont",          "tier": 3},
    "94538": {"city": "Fremont",          "tier": 3},
    "94536": {"city": "Fremont",          "tier": 3},
    "94537": {"city": "Fremont",          "tier": 3},
    "94541": {"city": "Hayward",          "tier": 3},
    "94555": {"city": "Fremont",          "tier": 3},
    "95035": {"city": "Milpitas",         "tier": 3},
    "94560": {"city": "Newark",           "tier": 3},
    "94061": {"city": "Redwood City",     "tier": 3},
    "94063": {"city": "Redwood City",     "tier": 3},
    "94066": {"city": "San Bruno",        "tier": 3},
    "94080": {"city": "S. San Francisco", "tier": 3},
    "95117": {"city": "West San Jose",    "tier": 3},
    "95128": {"city": "West San Jose",    "tier": 3},
    "95130": {"city": "West San Jose",    "tier": 3},
    "94404": {"city": "Foster City",      "tier": 3},
    "95123": {"city": "San Jose",         "tier": 3},
    "95124": {"city": "San Jose",         "tier": 3},
    "95120": {"city": "Almaden Valley",   "tier": 3},
    "95008": {"city": "Campbell",         "tier": 3},
    "95116": {"city": "San Jose East",    "tier": 3},
    "95122": {"city": "San Jose East",    "tier": 3},
    # Tier 4
    "94509": {"city": "Antioch",          "tier": 4},
    "94531": {"city": "Antioch",          "tier": 4},
    "95376": {"city": "Tracy",            "tier": 4},
    "95377": {"city": "Tracy",            "tier": 4},
    "95037": {"city": "Morgan Hill",      "tier": 4},
    "95038": {"city": "Morgan Hill",      "tier": 4},
}

# Tier thresholds for auto-reclassification (median SFR price in $M)
TIER_THRESHOLDS = {
    1: (2.8, None),   # tier1: median > $2.8M
    2: (1.6, 2.8),    # tier2: $1.6M – $2.8M
    3: (0.9, 1.6),    # tier3: $0.9M – $1.6M
    4: (0.0, 0.9),    # tier4: < $0.9M
}

# ── Redfin API helpers ────────────────────────────────────────────────────────

BASE = "https://www.redfin.com/stingray"

def redfin_get(path: str, params: dict) -> dict:
    """Call a Redfin internal endpoint and return parsed JSON."""
    url = BASE + path
    resp = SESSION.get(url, params=params, timeout=20)
    resp.raise_for_status()
    text = resp.text
    # Redfin prefixes JSON with '{}&&' to prevent CSRF hijacking
    if text.startswith("{}&&"):
        text = text[4:]
    return json.loads(text)


def get_region_id(zip_code: str) -> str | None:
    """Resolve a ZIP code to Redfin's internal region ID."""
    try:
        data = redfin_get("/api/v1/search/autocomplete", {"location": zip_code, "v": 2})
        for item in data.get("payload", {}).get("sections", []):
            for result in item.get("rows", []):
                if result.get("type") == 2:  # type 2 = ZIP
                    return result.get("id")
    except Exception as e:
        print(f"  [region_id] {zip_code}: {e}")
    return None


def get_market_stats(region_id: str, zip_code: str) -> dict:
    """Fetch median sale price, days on market, sale/list ratio for a region."""
    try:
        data = redfin_get("/api/v1/market_tracker/point_history", {
            "region_id": region_id,
            "region_type": 2,
            "property_type": 1,   # 1 = single family
            "num_weeks": 4,
            "metric_type": "median_sale_price_per_sqft,median_dom,sale_to_list",
        })
        payload = data.get("payload", {})
        rows = payload.get("rows", [])
        if not rows:
            return {}
        latest = rows[-1] if rows else {}
        return {
            "median_price":      payload.get("medianSalePrice", {}).get("last"),
            "median_dom":        payload.get("medianDOM", {}).get("last"),
            "sale_to_list":      payload.get("saleToList", {}).get("last"),
            "yoy_change":        payload.get("medianSalePrice", {}).get("yearOverYearChange"),
        }
    except Exception as e:
        print(f"  [market_stats] {zip_code}: {e}")
        return {}


def get_recent_sales(region_id: str, zip_code: str, count: int = 3) -> list:
    """Fetch recently sold single-family homes in a ZIP."""
    try:
        data = redfin_get("/api/gis", {
            "region_id": region_id,
            "region_type": 2,
            "status": 9,          # 9 = recently sold
            "property_type": 1,   # single family
            "num_homes": count * 3,
            "ord": "redfin-recommended-asc",
            "sf": "1,2,3,5,6,7",
            "v": 8,
        })
        homes = data.get("payload", {}).get("homes", [])
        results = []
        for h in homes[:count]:
            hl = h.get("homeData", h)
            results.append({
                "address":    hl.get("streetLine", {}).get("value", ""),
                "city":       hl.get("cityState", {}).get("value", ""),
                "price":      hl.get("price", {}).get("value"),
                "beds":       hl.get("beds", {}).get("value"),
                "baths":      hl.get("baths", {}).get("value"),
                "sqft":       hl.get("sqFt", {}).get("value"),
                "url":        "https://www.redfin.com" + hl.get("url", ""),
                "sold_date":  hl.get("soldDate", {}).get("value", ""),
            })
        return results
    except Exception as e:
        print(f"  [recent_sales] {zip_code}: {e}")
        return []


# ── Tier auto-detection ───────────────────────────────────────────────────────

def suggest_tier(median_price: float | None, current_tier: int) -> dict:
    """Compare median price against thresholds; flag if tier may have changed."""
    if median_price is None:
        return {"suggested_tier": current_tier, "tier_changed": False}
    price_m = median_price / 1_000_000
    for tier, (lo, hi) in TIER_THRESHOLDS.items():
        if (hi is None and price_m >= lo) or (hi is not None and lo <= price_m < hi):
            return {
                "suggested_tier": tier,
                "tier_changed": tier != current_tier,
                "price_m": round(price_m, 2),
            }
    return {"suggested_tier": current_tier, "tier_changed": False}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    today = date.today().isoformat()
    print(f"=== Bay Area Listings Update — {today} ===\n")

    results = {}
    tier_alerts = []

    for zip_code, meta in ZIPS.items():
        city = meta["city"]
        tier = meta["tier"]
        print(f"[{zip_code}] {city} (tier{tier})")

        region_id = get_region_id(zip_code)
        if not region_id:
            print(f"  ⚠ Could not resolve region ID, skipping")
            results[zip_code] = {"city": city, "tier": tier, "error": "no_region_id"}
            time.sleep(0.5)
            continue

        stats  = get_market_stats(region_id, zip_code)
        sales  = get_recent_sales(region_id, zip_code)
        tier_check = suggest_tier(stats.get("median_price"), tier)

        if tier_check["tier_changed"]:
            alert = (f"⚠ TIER ALERT: {zip_code} {city} — "
                     f"current=tier{tier}, suggested=tier{tier_check['suggested_tier']} "
                     f"(median ${tier_check.get('price_m','?')}M)")
            print(f"  {alert}")
            tier_alerts.append(alert)

        results[zip_code] = {
            "city":           city,
            "tier":           tier,
            "region_id":      region_id,
            "fetched_at":     datetime.utcnow().isoformat() + "Z",
            "stats":          stats,
            "recent_sales":   sales,
            "tier_check":     tier_check,
        }
        time.sleep(0.8)   # be polite to Redfin

    # ── Save ──────────────────────────────────────────────────────────────────

    output = {
        "date":        today,
        "zip_count":   len(results),
        "tier_alerts": tier_alerts,
        "zips":        results,
    }

    # Daily history snapshot
    history_path = HISTORY_DIR / f"{today}.json"
    with open(history_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✓ History saved → {history_path}")

    # Latest (always overwrite)
    with open(LATEST_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"✓ Latest saved  → {LATEST_PATH}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"ZIPs processed : {len(results)}")
    print(f"Tier alerts    : {len(tier_alerts)}")
    if tier_alerts:
        print("\nTier Alerts:")
        for a in tier_alerts:
            print(f"  {a}")


if __name__ == "__main__":
    main()
