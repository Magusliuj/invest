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


def build_stats_html(zip_code: str, data: dict) -> str:
    """Build the zip-stats div content from fetched data."""
    stats = data.get("stats", {})
    mp    = stats.get("median_price")
    yoy   = stats.get("yoy_change")
    dom   = stats.get("median_dom")
    s2l   = stats.get("sale_to_list")
    cls   = price_class(yoy)

    return (
        f'<div class="zstat"><span class="zval {cls}">{fmt_price_clean(mp)}</span>'
        f'<span class="zlabel">中位成交价</span></div>'
        f'<div class="zstat"><span class="zval {cls}">{fmt_yoy(yoy)}</span>'
        f'<span class="zlabel">同比涨幅</span></div>'
        f'<div class="zstat"><span class="zval neutral">{fmt_dom(dom)}</span>'
        f'<span class="zlabel">平均成交</span></div>'
        f'<div class="zstat"><span class="zval neutral">{fmt_ratio(s2l)}</span>'
        f'<span class="zlabel">成交/要价比</span></div>'
    )


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
    Find the zip-block for a given ZIP in the HTML and update:
    - The zip-stats section (price, YoY, DOM, ratio)
    - Auto-listing markers if present
    """

    # ── 1. Update stats ──────────────────────────────────────────────────────
    # Find the zip-block that contains this zip code
    # Strategy: find <span class="zip-code">94027</span> then walk forward
    # to the zip-stats div and replace its contents.

    zip_pattern = re.compile(
        r'(<span class="zip-code">' + re.escape(zip_code) + r'</span>.*?'
        r'<div class="zip-stats">)(.*?)(</div>\s*</div>\s*</div>)',
        re.DOTALL
    )

    stats_html = build_stats_html(zip_code, zip_data)

    def replace_stats(m):
        return m.group(1) + "\n          " + stats_html + "\n        " + m.group(3)

    html, n = re.subn(zip_pattern, replace_stats, html, count=1)
    if n:
        print(f"  [{zip_code}] stats updated")

    # ── 2. Update auto-listing markers ────────────────────────────────────────
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


def update_last_updated(html: str, today: str) -> str:
    """Update or insert a 'last updated' badge near the top of the page."""
    badge = f'<span id="last-updated" style="font-size:0.75rem;color:var(--muted);margin-left:12px;">数据更新：{today}</span>'
    if 'id="last-updated"' in html:
        html = re.sub(r'<span id="last-updated"[^>]*>.*?</span>', badge, html)
    else:
        # Insert after the first <h1>
        html = re.sub(r'(<h1[^>]*>.*?</h1>)', r'\1\n    ' + badge, html, count=1, flags=re.DOTALL)
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

    # Update timestamp
    html = update_last_updated(html, today)

    # Write tier alerts as an HTML comment for visibility
    if alerts:
        alert_block = "\n<!-- TIER ALERTS " + today + ":\n" + "\n".join(alerts) + "\n-->\n"
        html = re.sub(r'<!-- TIER ALERTS.*?-->\n?', '', html, flags=re.DOTALL)
        html = alert_block + html

    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"\n✓ index.html patched")

    if alerts:
        print(f"\n⚠ {len(alerts)} tier alert(s) — review data/latest.json")
        for a in alerts:
            print(f"  {a}")


if __name__ == "__main__":
    main()
