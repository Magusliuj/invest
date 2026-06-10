#!/usr/bin/env python3
"""
Bay Area Real Estate — HTML Patcher
Reads data/latest.json and updates index.html with:
  - Fresh median prices in zip-block stat bars
  - Updated YoY change percentages
  - Updated days-on-market
  - Updated sale/list ratios
  - Injects latest 2 recent sales into each zip-block listing row
  - Adds a "Last updated" timestamp to the page header

Markers in HTML (auto-inserted on first run, then updated):
  <!-- ZIP_STATS:94027 --> ... <!-- /ZIP_STATS:94027 -->
  <!-- ZIP_LISTINGS:94027 --> ... <!-- /ZIP_LISTINGS:94027 -->

Run:  python3 scripts/patch_html.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

ROOT        = Path(__file__).parent.parent
LATEST_PATH = ROOT / "data" / "latest.json"
HTML_PATH   = ROOT / "index.html"
BACKUP_PATH = ROOT / "index.html.bak"


def fmt_price(p) -> str:
    """Format a raw price int like 2450000 → '$2.45M'"""
    if p is None:
        return "—"
    m = p / 1_000_000
    if m >= 1:
        return f"${m:.2f}M".rstrip('0').rstrip('.')  + "M" if '.' in f"${m:.2f}M" else f"${m:.2f}M"
    return f"${p:,}"


def fmt_price_clean(p) -> str:
    if p is None:
        return "—"
    m = p / 1_000_000
    return f"${m:.2f}M"


def fmt_yoy(yoy) -> str:
    """Format YoY change like 0.066 → '↑6.6%' or -0.05 → '↓5.0%'"""
    if yoy is None:
        return "—"
    pct = yoy * 100
    arrow = "↑" if pct >= 0 else "↓"
    return f"{arrow}{abs(pct):.1f}%"


def fmt_dom(dom) -> str:
    if dom is None:
        return "—"
    return f"{int(dom)}天"


def fmt_ratio(r) -> str:
    if r is None:
        return "—"
    return f"{r*100:.0f}%"


def price_class(yoy) -> str:
    """CSS class for the stat value based on direction."""
    if yoy is None:
        return "neutral"
    return "up" if yoy >= 0 else "down"


def update_zstat(block: str, label: str, new_value: str, new_class: str) -> Tuple[str, bool]:
    """Within a zip-block substring, update the value+class of the zstat whose zlabel matches."""
    pattern = re.compile(
        r'(<div class="zstat"><span class="zval )([\w\s-]+)(">)([^<]*)(</span><span class="zlabel">'
        + re.escape(label) + r'</span></div>)'
    )
    def repl(m):
        return m.group(1) + new_class + m.group(3) + new_value + m.group(5)
    new_block, n = pattern.subn(repl, block, count=1)
    return new_block, n > 0


def current_price_usd(block: str) -> Optional[int]:
    """Parse the existing 中位成交价 value (e.g. '$14.8M' or '$3.6M–4.1M') into a dollar int.
    Ranges return the midpoint. Returns None if unparseable."""
    m = re.search(
        r'<div class="zstat"><span class="zval [\w\s-]+">([^<]*)</span>'
        r'<span class="zlabel">中位成交价</span></div>',
        block,
    )
    if not m:
        return None
    raw = m.group(1).replace(',', '').replace('$', '').strip()
    nums = re.findall(r'(\d+(?:\.\d+)?)\s*M', raw)
    if not nums:
        return None
    vals = [float(n) * 1_000_000 for n in nums]
    return int(sum(vals) / len(vals))


# Skip a price update if the new value differs from current by more than this fraction.
PRICE_DRIFT_THRESHOLD = 0.25


def build_listings_html(zip_code: str, data: dict) -> str:
    """Build auto-fetched listing cards for a ZIP."""
    sales = data.get("recent_sales", [])
    if not sales:
        return ""

    tier = data.get("tier", 3)
    tier_cls = f"t{tier}"
    cards = []

    for s in sales[:2]:
        addr   = s.get("address", "")
        city   = s.get("city", "")
        price  = s.get("price")
        beds   = s.get("beds", "?")
        baths  = s.get("baths", "?")
        sqft   = s.get("sqft")
        url    = s.get("url", "#")
        sold   = s.get("sold_date", "")

        sqft_str = f" / {sqft:,} sqft" if sqft else ""
        price_str = f"${price:,}" if price else "—"
        sold_str  = f" · {sold[:10]}" if sold else ""

        card = (
            f'<div class="listing-card">'
            f'<div class="lc-price {tier_cls}">{price_str}</div>'
            f'<div class="lc-addr">🔄 {addr}, {city}</div>'
            f'<div class="lc-spec">{beds}卧 / {baths}浴{sqft_str}{sold_str}</div>'
            f'<div class="lc-tags">'
            f'<span class="lc-tag g">Redfin实时数据</span>'
            f'<span class="lc-tag">自动更新</span>'
            f'</div>'
            f'<div class="lc-note">自动从 Redfin 获取的最新成交记录。</div>'
            f'<a class="lc-link" href="{url}" target="_blank">在 Redfin 查看 →</a>'
            f'</div>'
        )
        cards.append(card)

    return "\n".join(cards)


def patch_zip_block(html: str, zip_code: str, zip_data: dict) -> str:
    """
    Surgically update the price (中位成交价) and YoY (同比涨幅) zstats inside
    the zip-block for this ZIP. Hand-curated DOM/school/ratio stats are left
    untouched (Zillow doesn't have ZIP-level DOM or sale/list ratio anyway).

    Auto-listing markers, if present, are also refreshed.
    """

    # ── 1. Locate this zip-block's slice of the HTML ─────────────────────────
    anchor = f'<span class="zip-code">{zip_code}</span>'
    start = html.find(anchor)
    if start == -1:
        return html
    # Block ends at the next zip-block opening, or end of file
    next_block = html.find('<div class="zip-block">', start + len(anchor))
    end = next_block if next_block != -1 else len(html)
    block = html[start:end]

    # ── 2. Update price + YoY in place ───────────────────────────────────────
    # Price update rules (guard against ZHVI smearing over hand-curated medians):
    #   (a) only accept Redfin prices — ZHVI is a smoothed model of all housing
    #       stock and routinely diverges from actual sale medians.
    #   (b) skip if the new value differs from the existing value by more than
    #       PRICE_DRIFT_THRESHOLD — likely a metric mismatch or ZIP miscoverage.
    redfin_price = zip_data.get("redfin_price")
    stats  = zip_data.get("stats", {})
    yoy    = stats.get("yoy_change")
    cls    = price_class(yoy)
    source = zip_data.get("price_source", "")

    updates = []
    skips = []

    if redfin_price is None:
        skips.append(f"price skipped (no redfin: source={source})")
    else:
        current = current_price_usd(block)
        if current and abs(redfin_price - current) / current > PRICE_DRIFT_THRESHOLD:
            skips.append(
                f"price skipped (drift {fmt_price_clean(current)}→"
                f"{fmt_price_clean(redfin_price)} exceeds {int(PRICE_DRIFT_THRESHOLD*100)}%)"
            )
        else:
            block, ok = update_zstat(block, "中位成交价", fmt_price_clean(redfin_price), cls)
            if ok:
                updates.append(f"price={fmt_price_clean(redfin_price)}[redfin]")

    if yoy is not None:
        block, ok = update_zstat(block, "同比涨幅", fmt_yoy(yoy), cls)
        if ok:
            updates.append(f"yoy={fmt_yoy(yoy)}")

    msg = " ".join(updates + skips)
    if msg:
        print(f"  [{zip_code}] {msg}")

    html = html[:start] + block + html[end:]

    # ── 3. Update auto-listing markers ────────────────────────────────────────
    marker_start = f"<!-- AUTO_LISTINGS:{zip_code} -->"
    marker_end   = f"<!-- /AUTO_LISTINGS:{zip_code} -->"
    new_listings = build_listings_html(zip_code, zip_data)

    if marker_start in html:
        # Replace existing marker block
        marker_pattern = re.compile(
            re.escape(marker_start) + r".*?" + re.escape(marker_end),
            re.DOTALL
        )
        html = marker_pattern.sub(
            marker_start + "\n" + new_listings + "\n" + marker_end,
            html
        )
        print(f"  [{zip_code}] auto-listings updated")

    return html


def main():
    if not LATEST_PATH.exists():
        print(f"ERROR: {LATEST_PATH} not found. Run update_listings.py first.")
        sys.exit(1)

    if not HTML_PATH.exists():
        print(f"ERROR: {HTML_PATH} not found.")
        sys.exit(1)

    with open(LATEST_PATH) as f:
        latest = json.load(f)

    today    = latest.get("date", date.today().isoformat())
    zips     = latest.get("zips", {})
    alerts   = latest.get("tier_alerts", [])

    print(f"=== HTML Patch — {today} ===")
    print(f"Patching {len(zips)} ZIPs into {HTML_PATH.name}\n")

    # Backup original
    html = HTML_PATH.read_text(encoding="utf-8")
    BACKUP_PATH.write_text(html, encoding="utf-8")
    print(f"Backup saved → {BACKUP_PATH.name}")

    # Patch each ZIP
    for zip_code, zip_data in zips.items():
        if zip_data.get("error"):
            print(f"  [{zip_code}] skipped (fetch error)")
            continue
        html = patch_zip_block(html, zip_code, zip_data)

    # Strip any stale tier-alert comment block left by older versions of this
    # script — alerts are stdout-only now.
    html = re.sub(r'<!-- TIER ALERTS.*?-->\n?', '', html, flags=re.DOTALL)

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"\n✓ index.html patched")

    if alerts:
        print(f"\n⚠ {len(alerts)} tier alert(s) — review data/latest.json")
        for a in alerts:
            print(f"  {a}")


if __name__ == "__main__":
    main()
