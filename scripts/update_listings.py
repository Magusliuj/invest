#!/usr/bin/env python3
"""
Bay Area Real Estate — Daily Data Updater

Two data sources, each used for what it does best:
  - Zillow ZHVI (free public CSV): tier placement — smoothed model value
    of the entire housing stock, consistent across ZIPs.
  - Redfin internal API (session-based): actual median sale price for
    individual deal evaluation — real transactions, more volatile.

If Redfin is unavailable (blocked/rate-limited), ZHVI is used as fallback
for display price too.

Run:  python3 scripts/update_listings.py
Deps: pip install requests pandas
"""

import io
import json
import time
from datetime import date, datetime
from pathlib import Path

import requests
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
ROOT        = SCRIPT_DIR.parent
DATA_DIR    = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_PATH = DATA_DIR / "latest.json"

DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

# ── Zillow public research CSV URLs ───────────────────────────────────────────
# ZHVI is the only Zillow dataset available at ZIP-code granularity (free).
# Median sale price and DOM are Metro-only in Zillow's public data.
ZILLOW_ZHVI_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
    "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
)

# ── ZIP Registry ──────────────────────────────────────────────────────────────

ZIPS = {
    # Tier 1
    "94027": {"city": "Atherton",         "tier": 1},
    "94022": {"city": "Los Altos",        "tier": 1},
    "94024": {"city": "Los Altos Hills",  "tier": 1},
    "94028": {"city": "Portola Valley",   "tier": 1},
    "94062": {"city": "Woodside",         "tier": 1, "pin": True},
    "94301": {"city": "Palo Alto",        "tier": 1},
    "94303": {"city": "Palo Alto",        "tier": 1, "pin": True},
    "94304": {"city": "Palo Alto",        "tier": 1},
    "94306": {"city": "Palo Alto",        "tier": 1},
    "95014": {"city": "Cupertino",        "tier": 1},
    "95070": {"city": "Saratoga",         "tier": 1},
    "94010": {"city": "Hillsborough",     "tier": 1},
    # Tier 2
    "94025": {"city": "Menlo Park",       "tier": 2, "pin": True},
    "95030": {"city": "Los Gatos",        "tier": 2, "pin": True},
    "95032": {"city": "Los Gatos",        "tier": 2},
    "94040": {"city": "Mountain View",    "tier": 2, "pin": True},
    "94041": {"city": "Mountain View",    "tier": 2},
    "94043": {"city": "Mountain View",    "tier": 2, "pin": True},
    "94087": {"city": "Sunnyvale",        "tier": 2, "pin": True},
    "94086": {"city": "Sunnyvale",        "tier": 2},
    "94085": {"city": "Sunnyvale",        "tier": 2, "pin": True},
    "94089": {"city": "Sunnyvale",        "tier": 2, "pin": True},
    "95129": {"city": "West San Jose",    "tier": 2},
    "94401": {"city": "San Mateo",        "tier": 2, "pin": True},
    "94402": {"city": "San Mateo",        "tier": 2},
    "94403": {"city": "San Mateo",        "tier": 2},
    "94114": {"city": "Noe Valley SF",    "tier": 2},
    "94115": {"city": "Pacific Heights",  "tier": 3},
    "94065": {"city": "Redwood Shores",   "tier": 2},
    "94070": {"city": "San Carlos",       "tier": 2},
    "94002": {"city": "Belmont",          "tier": 2},
    "94030": {"city": "Millbrae",         "tier": 2},
    "94103": {"city": "SoMa SF",          "tier": 4},
    "94107": {"city": "Mission Bay SF",   "tier": 3},
    "94105": {"city": "Embarcadero SF",   "tier": 3},
    "94158": {"city": "Mission Bay SF",   "tier": 3},
    # Tier 3
    "95051": {"city": "Santa Clara",      "tier": 3, "pin": True},
    "95050": {"city": "Santa Clara",      "tier": 3, "pin": True},
    "95054": {"city": "Santa Clara",      "tier": 3},
    "94539": {"city": "Fremont",          "tier": 3, "pin": True},
    "94538": {"city": "Fremont",          "tier": 3},
    "94536": {"city": "Fremont",          "tier": 3},
    "94537": {"city": "Fremont",          "tier": 3},
    "94541": {"city": "Hayward",          "tier": 4},
    "94555": {"city": "Fremont",          "tier": 3},
    "95035": {"city": "Milpitas",         "tier": 3},
    "94560": {"city": "Newark",           "tier": 3},
    "94061": {"city": "Redwood City",     "tier": 2},
    "94063": {"city": "Redwood City",     "tier": 3},
    "94066": {"city": "San Bruno",        "tier": 3},
    "94080": {"city": "S. San Francisco", "tier": 3},
    "95117": {"city": "West San Jose",    "tier": 3, "pin": True},
    "95128": {"city": "West San Jose",    "tier": 3},
    "95130": {"city": "West San Jose",    "tier": 3, "pin": True},
    "94404": {"city": "Foster City",      "tier": 3, "pin": True},
    "95123": {"city": "San Jose",         "tier": 3},
    "95124": {"city": "San Jose",         "tier": 3, "pin": True},
    "95120": {"city": "Almaden Valley",   "tier": 2},
    "95008": {"city": "Campbell",         "tier": 3, "pin": True},
    "95116": {"city": "San Jose East",    "tier": 3},
    "95122": {"city": "San Jose East",    "tier": 3},
    # Tier 4
    "94509": {"city": "Antioch",          "tier": 4},
    "94531": {"city": "Antioch",          "tier": 4},
    "95376": {"city": "Tracy",            "tier": 4},
    "95377": {"city": "Tracy",            "tier": 4},
    "95037": {"city": "Morgan Hill",      "tier": 4, "pin": True},
    "95038": {"city": "Morgan Hill",      "tier": 4},
}

# Tier thresholds (median SFR price in $M)
TIER_THRESHOLDS = {
    1: (2.8, None),
    2: (1.6, 2.8),
    3: (0.9, 1.6),
    4: (0.0, 0.9),
}


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
}

# Redfin session — warmed up once before ZIP lookups
REDFIN_SESSION = requests.Session()
REDFIN_SESSION.headers.update(HEADERS)
REDFIN_BASE = "https://www.redfin.com/stingray"


def warmup_redfin() -> bool:
    """Visit Redfin homepage to get session cookies. Returns True if successful."""
    try:
        r = REDFIN_SESSION.get("https://www.redfin.com", timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def redfin_get(path: str, params: dict) -> dict:
    url = REDFIN_BASE + path
    resp = REDFIN_SESSION.get(url, params=params, timeout=20)
    resp.raise_for_status()
    text = resp.text
    if text.startswith("{}&&"):
        text = text[4:]
    return json.loads(text)


def get_redfin_median(zip_code: str):
    """Fetch actual median sale price from Redfin for a ZIP. Returns None on failure."""
    try:
        data = redfin_get("/do/location-autocomplete", {"location": zip_code, "v": 2})
        region_id = None
        for section in data.get("payload", {}).get("sections", []):
            for row in section.get("rows", []):
                if row.get("type") == 2:
                    region_id = row.get("id")
                    break
            if region_id:
                break
        if not region_id:
            return None

        mdata = redfin_get("/api/v1/market_tracker/point_history", {
            "region_id": region_id,
            "region_type": 2,
            "property_type": 1,
            "num_weeks": 4,
            "metric_type": "median_sale_price",
        })
        price = mdata.get("payload", {}).get("medianSalePrice", {}).get("last")
        return int(price) if price else None
    except Exception:
        return None


def fetch_csv(url: str, label: str) -> pd.DataFrame:
    print(f"  Downloading {label} ...")
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), low_memory=False)


def latest_zip_value(df: pd.DataFrame, zip_code: int):
    """Zillow CSVs are wide format: columns are dates. Return latest non-null value."""
    row = df[df["RegionName"] == zip_code]
    if row.empty:
        return None, None
    row = row.iloc[0]
    # Date columns start after the metadata columns
    date_cols = [c for c in df.columns if c[:2] in ("19", "20")]
    if not date_cols:
        return None, None
    date_cols_sorted = sorted(date_cols)
    # Find latest non-null
    for col in reversed(date_cols_sorted):
        val = row[col]
        if pd.notna(val):
            return float(val), col
    return None, None


def extract_zip_stats(zhvi_df, zip_code: str) -> dict:
    """Extract ZHVI home value and YoY change for a ZIP from Zillow's monthly CSV."""
    zc = int(zip_code)
    zhvi_val, period = latest_zip_value(zhvi_df, zc)

    if zhvi_val is None:
        return {}

    # YoY: compare to column 12 months ago (monthly data)
    yoy = None
    date_cols = sorted([c for c in zhvi_df.columns if c[:2] in ("19", "20")])
    if period and period in date_cols:
        idx = date_cols.index(period)
        if idx >= 12:
            past_col = date_cols[idx - 12]
            row = zhvi_df[zhvi_df["RegionName"] == zc]
            if not row.empty:
                past_val = row.iloc[0][past_col]
                if pd.notna(past_val) and float(past_val) > 0:
                    yoy = (zhvi_val - float(past_val)) / float(past_val)

    return {
        "median_price": int(zhvi_val),
        "yoy_change":   round(yoy, 4) if yoy is not None else None,
        "median_dom":   None,   # not available at ZIP level from Zillow
        "sale_to_list": None,   # not available at ZIP level from Zillow
        "period_end":   period,
    }


def suggest_tier(median_price, current_tier: int, pinned: bool = False) -> dict:
    if median_price is None or pinned:
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


def main():
    today = date.today().isoformat()
    print(f"=== Bay Area Listings Update — {today} ===\n")

    # ── Zillow ZHVI: tier placement ───────────────────────────────────────────
    print("Fetching Zillow ZHVI (tier placement) ...")
    try:
        zhvi_df = fetch_csv(ZILLOW_ZHVI_URL, "ZHVI by ZIP")
    except Exception as e:
        print(f"ERROR downloading Zillow data: {e}")
        raise

    # ── Redfin: actual sale price ─────────────────────────────────────────────
    print("\nWarming up Redfin session ...")
    redfin_ok = warmup_redfin()
    print(f"  Redfin session: {'✓ ready' if redfin_ok else '✗ unavailable — will use ZHVI as display price'}")
    print()

    results = {}
    tier_alerts = []

    for zip_code, meta in ZIPS.items():
        city = meta["city"]
        tier = meta["tier"]

        # ZHVI → tier decision
        stats = extract_zip_stats(zhvi_df, zip_code)
        pinned = meta.get("pin", False)
        tier_check = suggest_tier(stats.get("median_price"), tier, pinned)

        # Redfin → display price (actual transactions)
        redfin_price = None
        if redfin_ok:
            redfin_price = get_redfin_median(zip_code)
            time.sleep(0.8)

        display_price = redfin_price or stats.get("median_price")
        price_source  = "redfin" if redfin_price else "zhvi"

        if stats or redfin_price:
            mp_str   = f"${display_price/1e6:.2f}M" if display_price else "—"
            src_str  = f"[{price_source}]"
            pin_str  = " [pinned]" if pinned else ""
            print(f"[{zip_code}] {city}: {mp_str} {src_str}  YoY={stats.get('yoy_change')}{pin_str}")
        else:
            print(f"[{zip_code}] {city}: no data found")

        if tier_check["tier_changed"]:
            alert = (f"⚠ TIER ALERT: {zip_code} {city} — "
                     f"current=tier{tier}, suggested=tier{tier_check['suggested_tier']} "
                     f"(median ${tier_check.get('price_m','?')}M)")
            print(f"  {alert}")
            tier_alerts.append(alert)

        results[zip_code] = {
            "city":         city,
            "tier":         tier,
            "fetched_at":   datetime.utcnow().isoformat() + "Z",
            "display_price":  display_price,
            "price_source":   price_source,
            "redfin_price":   redfin_price,
            "stats":      stats,
            "tier_check": tier_check,
        }

    # ── Save ──────────────────────────────────────────────────────────────────
    output = {
        "date":        today,
        "zip_count":   len(results),
        "tier_alerts": tier_alerts,
        "zips":        results,
    }

    history_path = HISTORY_DIR / f"{today}.json"
    with open(history_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n✓ History saved → {history_path}")

    with open(LATEST_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"✓ Latest saved  → {LATEST_PATH}")

    print(f"\n=== Summary ===")
    print(f"ZIPs processed : {len(results)}")
    print(f"Tier alerts    : {len(tier_alerts)}")
    if tier_alerts:
        for a in tier_alerts:
            print(f"  {a}")


if __name__ == "__main__":
    main()
