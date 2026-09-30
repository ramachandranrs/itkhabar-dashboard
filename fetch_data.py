#!/usr/bin/env python3
"""
IT Services Command Center — Live Data Fetcher
Pulls stock prices, market indices and news headlines,
writes data.json for the dashboard to consume.

Usage:
  pip install yfinance requests
  python fetch_data.py

Runs on GitHub Actions via .github/workflows/refresh.yml
"""

import json
import datetime
import os
import sys

try:
    import yfinance as yf
except ImportError:
    print("Installing yfinance...")
    os.system(f"{sys.executable} -m pip install yfinance -q")
    import yfinance as yf

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

# ─── Company ticker mapping ───
# Maps our dashboard ticker to Yahoo Finance symbol
TICKERS = {
    # Indian IT (NSE)
    "TCS":   {"yf": "TCS.NS",    "currency": "₹", "name": "Tata Consultancy Services"},
    "INFY":  {"yf": "INFY.NS",   "currency": "₹", "name": "Infosys"},
    "CTSH":  {"yf": "CTSH",      "currency": "$", "name": "Cognizant"},
    "HCLT":  {"yf": "HCLTECH.NS","currency": "₹", "name": "HCLTech"},
    "WIPRO": {"yf": "WIPRO.NS",  "currency": "₹", "name": "Wipro"},
    "TECHM": {"yf": "TECHM.NS",  "currency": "₹", "name": "Tech Mahindra"},
    "LTIM":  {"yf": "LTIMINDLT.NS","currency": "₹", "name": "LTIMindtree"},
    "MPHL":  {"yf": "MPHASIS.NS","currency": "₹", "name": "Mphasis"},
    "PSYS":  {"yf": "PERSISTENT.NS","currency": "₹", "name": "Persistent Systems"},
    "COFG":  {"yf": "COFORGE.NS","currency": "₹", "name": "Coforge"},
    # Global
    "ACN":   {"yf": "ACN",       "currency": "$", "name": "Accenture"},
    "CAP":   {"yf": "CAP.PA",    "currency": "€", "name": "Capgemini"},
    "NTTD":  {"yf": "9613.T",    "currency": "¥", "name": "NTT Data"},
    "ATOS":  {"yf": "ATO.PA",    "currency": "€", "name": "Atos"},
    "DXC":   {"yf": "DXC",       "currency": "$", "name": "DXC Technology"},
    "GIB":   {"yf": "GIB",       "currency": "$", "name": "CGI Group"},
}

# Market indices
INDICES = {
    "SENSEX":   "^BSESN",
    "NIFTY_IT": "^CNXIT",
    "SP500":    "^GSPC",
    "USD_INR":  "INR=X",
    "EUR_INR":  "EURINR=X",
}


def fetch_stock_prices():
    """Fetch latest stock prices for all tracked companies."""
    print("Fetching stock prices...")
    prices = {}

    symbols = [v["yf"] for v in TICKERS.values()]
    try:
        data = yf.download(symbols, period="5d", group_by="ticker", progress=False)
    except Exception as e:
        print(f"  Bulk download failed: {e}, trying individually...")
        data = None

    for tk, info in TICKERS.items():
        sym = info["yf"]
        try:
            if data is not None and sym in data.columns.get_level_values(0):
                df = data[sym].dropna()
                if len(df) >= 2:
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    price = float(latest["Close"])
                    chg = round((price - float(prev["Close"])) / float(prev["Close"]) * 100, 1)
                else:
                    raise ValueError("Not enough data")
            else:
                raise ValueError("Not in bulk data")
        except Exception:
            try:
                ticker = yf.Ticker(sym)
                hist = ticker.history(period="5d")
                if len(hist) >= 2:
                    price = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2])
                    chg = round((price - prev) / prev * 100, 1)
                else:
                    print(f"  ⚠ {tk}: insufficient data")
                    continue
            except Exception as e2:
                print(f"  ✗ {tk}: {e2}")
                continue

        # Format price for display
        cur = info["currency"]
        if cur == "₹":
            display = f"₹{price:,.0f}"
        elif cur == "¥":
            display = f"¥{price:,.0f}"
        elif cur == "€":
            display = f"€{price:,.0f}" if price >= 100 else f"€{price:,.2f}"
        else:
            display = f"${price:,.0f}" if price >= 100 else f"${price:,.2f}"

        prices[tk] = {"price": round(price, 2), "display": display, "change": chg}
        print(f"  ✓ {tk}: {display} ({'+' if chg >= 0 else ''}{chg}%)")

    return prices


def fetch_historical_prices():
    """Fetch historical prices for trend charts.

    Returns dict keyed by dashboard ticker:
      { "TCS": { "mp": [12 monthly closing prices], "dp": [daily closes this month] }, ... }

    mp = last-trading-day close of each of the past 12 calendar months
         (oldest first, current month excluded — current month is covered by dp).
    dp = every trading-day close in the current calendar month so far (oldest first).
    """
    print("Fetching historical prices for trend charts...")
    historical = {}
    now = datetime.datetime.now(datetime.timezone.utc)

    for tk, info in TICKERS.items():
        sym = info["yf"]
        try:
            ticker = yf.Ticker(sym)
            # Fetch ~14 months of daily data to derive monthly closes
            hist = ticker.history(period="14mo")
            if hist.empty or len(hist) < 5:
                print(f"  ⚠ {tk}: insufficient historical data")
                continue

            # --- Monthly closes (mp): last trading day of each of the past 12 months ---
            # Group by year-month
            hist.index = hist.index.tz_localize(None) if hist.index.tz is not None else hist.index
            monthly = hist["Close"].resample("ME").last().dropna()
            # Exclude current month (it's incomplete — dp covers it)
            cur_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0,
                                          tzinfo=None)
            monthly = monthly[monthly.index < cur_month_start]
            # Take latest 12 months
            mp_values = [round(float(v), 0) for v in monthly.tail(12).values]

            # --- Daily closes for current month (dp) ---
            month_start = cur_month_start
            daily_mask = hist.index >= month_start
            daily_this_month = hist.loc[daily_mask, "Close"].dropna()
            dp_values = [round(float(v), 0) for v in daily_this_month.values]

            # Only include if we have meaningful data
            if len(mp_values) >= 6:
                historical[tk] = {"mp": mp_values, "dp": dp_values}
                print(f"  ✓ {tk}: {len(mp_values)} monthly + {len(dp_values)} daily prices")
            else:
                print(f"  ⚠ {tk}: only {len(mp_values)} monthly points, skipping")

        except Exception as e:
            print(f"  ✗ {tk}: {e}")

    return historical


def fetch_indices():
    """Fetch market index values."""
    print("Fetching market indices...")
    indices = {}

    for name, sym in INDICES.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if len(hist) >= 2:
                val = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg = round((val - prev) / prev * 100, 2)
                indices[name] = {"value": round(val, 2), "change": chg}
                print(f"  ✓ {name}: {val:,.2f} ({'+' if chg >= 0 else ''}{chg}%)")
            else:
                print(f"  ⚠ {name}: insufficient data")
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    return indices


def fetch_news():
    """Fetch latest IT sector news headlines via NewsAPI (if API key is set).

    STRICT FILTER: Only headlines mentioning a tracked company name,
    or specific IT-services-sector terms, are kept. General tech/global
    news is discarded.
    """
    api_key = os.environ.get("NEWSAPI_KEY", "")
    if not api_key:
        print("No NEWSAPI_KEY set — skipping news fetch. Add it as a GitHub secret.")
        return []

    print("Fetching news...")
    headlines = []

    # ── Relevance keywords (case-insensitive matching) ──
    # Company names & tickers we track
    COMPANY_KEYWORDS = set()
    for tk, info in TICKERS.items():
        COMPANY_KEYWORDS.add(tk.upper())
        # Full name and first word
        full = info["name"]
        COMPANY_KEYWORDS.add(full.upper())
        first = full.split()[0].upper()
        if len(first) > 2:  # skip very short words
            COMPANY_KEYWORDS.add(first)
    # Add common alternate names
    for alt in ["TCS", "INFY", "HCLTECH", "HCL TECH", "TECH MAHINDRA",
                "LTIMINDTREE", "LTI MINDTREE", "MPHASIS", "COFORGE",
                "PERSISTENT", "NTT DATA", "DXC", "CGI GROUP"]:
        COMPANY_KEYWORDS.add(alt.upper())

    # IT-services-sector terms (not generic "technology")
    SECTOR_KEYWORDS = {
        "IT SERVICES", "IT SECTOR", "IT OUTSOURCING", "IT OFFSHORING",
        "NIFTY IT", "BSE IT", "DIGITAL TRANSFORMATION",
        "MANAGED SERVICES", "CONSULTING SERVICES", "BPO", "BPM",
        "SYSTEMS INTEGRATION", "IT SPENDING", "IT BUDGET",
        "CLOUD MIGRATION", "ENTERPRISE SOFTWARE", "IT DEAL",
        "IT CONTRACT", "OFFSHORE", "NEARSHORE",
    }

    # Words that are too common to use as standalone matchers
    AMBIGUOUS_FIRST_WORDS = {"TECH", "DXC", "CGI", "NTT", "PERSISTENT"}

    def is_relevant(title, desc):
        """Return (True, ticker) if article is about our IT services universe."""
        import re
        text = f"{title} {desc}".upper()
        # Check full company names first (high confidence)
        for tk_key, info in TICKERS.items():
            full_name = info["name"].upper()
            if full_name in text:
                return True, tk_key
        # Check ticker symbols with word boundaries (avoid partial matches)
        for tk_key, info in TICKERS.items():
            if re.search(r'\b' + re.escape(tk_key.upper()) + r'\b', text):
                # Skip very short tickers that could be false positives
                if len(tk_key) <= 3 and tk_key.upper() in {"CAP", "GIB"}:
                    continue
                return True, tk_key
        # Check well-known alternate names (only unambiguous ones)
        SAFE_ALTERNATES = {
            "HCLTECH": "HCLT", "HCL TECH": "HCLT",
            "TECH MAHINDRA": "TECHM",
            "LTIMINDTREE": "LTIM", "LTI MINDTREE": "LTIM",
            "MPHASIS": "MPHL", "COFORGE": "COFG",
            "PERSISTENT SYSTEMS": "PSYS",
            "NTT DATA": "NTTD", "CGI GROUP": "GIB",
            "DXC TECHNOLOGY": "DXC",
            "TATA CONSULTANCY": "TCS",
        }
        for alt, tk_key in SAFE_ALTERNATES.items():
            if alt in text:
                return True, tk_key
        # Check sector keywords
        for kw in SECTOR_KEYWORDS:
            if kw in text:
                return True, "Sector"
        return False, None

    # Queries: each targets company names explicitly using AND/OR
    # to force NewsAPI to return only IT-services-relevant articles
    queries = [
        '"TCS" OR "Infosys" OR "HCLTech" OR "Wipro" OR "Tech Mahindra"',
        '"Accenture" OR "Capgemini" OR "Cognizant" OR "LTIMindtree"',
        '"Mphasis" OR "Persistent Systems" OR "Coforge" OR "DXC Technology"',
        '"NTT Data" OR "CGI Group" OR "Atos"',
        '"IT services" AND ("deal" OR "revenue" OR "earnings" OR "contract")',
        '"Nifty IT" OR "IT sector" AND India',
        # ── Earnings season queries (Oct–Nov = Q2 FY27 results) ──
        '("TCS" OR "Infosys" OR "HCLTech" OR "Wipro") AND ("results" OR "earnings" OR "quarterly" OR "profit")',
        '("Tech Mahindra" OR "LTIMindtree" OR "Mphasis" OR "Persistent" OR "Coforge") AND ("results" OR "earnings" OR "quarterly")',
        '("Cognizant" OR "Accenture" OR "Capgemini" OR "DXC") AND ("results" OR "earnings" OR "revenue" OR "guidance")',
    ]

    import re as _re

    def _normalize(text):
        """Normalize headline for fuzzy dedup: lowercase, strip punctuation, collapse whitespace."""
        t = text.lower()
        t = _re.sub(r'[^\w\s]', '', t)
        t = _re.sub(r'\s+', ' ', t).strip()
        return t

    def _is_duplicate(title, seen_titles):
        """Check if a title is a near-duplicate of any seen title.
        Uses normalized overlap: if 60%+ of words in common, it's a dupe."""
        norm = _normalize(title)
        norm_words = set(norm.split())
        if len(norm_words) < 3:
            return norm in seen_titles
        for seen_norm, seen_words in seen_titles.values():
            # Check both directions of overlap
            if not seen_words:
                continue
            common = norm_words & seen_words
            overlap_a = len(common) / len(norm_words) if norm_words else 0
            overlap_b = len(common) / len(seen_words) if seen_words else 0
            if max(overlap_a, overlap_b) >= 0.6:
                return True
        return False

    seen_titles = {}  # {exact_title: (normalized, set_of_words)}
    for q in queries:
        try:
            resp = requests.get("https://newsapi.org/v2/everything", params={
                "q": q,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 8,
                "apiKey": api_key,
            }, timeout=15)
            if resp.status_code == 200:
                articles = resp.json().get("articles", [])
                for a in articles:
                    title = a.get("title", "")
                    desc = a.get("description", "") or ""
                    if not title or title in seen_titles:
                        continue
                    # ── Fuzzy dedup: skip near-duplicate headlines ──
                    if _is_duplicate(title, seen_titles):
                        continue
                    # ── STRICT relevance gate ──
                    relevant, tk = is_relevant(title, desc)
                    if not relevant:
                        continue
                    norm = _normalize(title)
                    seen_titles[title] = (norm, set(norm.split()))
                    # Auto-detect category from headline
                    upper_title = title.upper()
                    if any(kw in upper_title for kw in
                           ['RESULTS', 'EARNINGS', 'QUARTERLY', 'PROFIT', 'REVENUE',
                            'EBIT', 'EPS', 'PAT ', 'NET INCOME', 'Q1 ', 'Q2 ', 'Q3 ', 'Q4 ',
                            'FY26', 'FY27', 'FISCAL']):
                        cat = 'RESULTS'
                    elif any(kw in upper_title for kw in
                             ['DEAL', 'CONTRACT', 'WIN', 'AWARD', 'PARTNER', 'ACQUISITION', 'MERGER']):
                        cat = 'DEAL'
                    elif any(kw in upper_title for kw in
                             ['GUIDANCE', 'OUTLOOK', 'FORECAST', 'TARGET', 'UPGRADE',
                              'DOWNGRADE', 'RATING', ' BUY', 'SELL', ' ADD ']):
                        cat = 'ANALYST'
                    elif any(kw in upper_title for kw in
                             [' AI ', 'ARTIFICIAL INTELLIGENCE', 'GENAI', 'MACHINE LEARNING']):
                        cat = 'AI'
                    elif any(kw in upper_title for kw in
                             ['CEO', 'CTO', 'APPOINT', 'RESIGN', 'HIRE', 'BOARD']):
                        cat = 'PEOPLE'
                    else:
                        cat = 'MACRO'
                    headlines.append({
                        "time": a.get("publishedAt", "")[:16].replace("T", " "),
                        "tk": tk,
                        "src": a.get("source", {}).get("name", "NEWS"),
                        "cat": cat,
                        "hl": title,
                        "detail": desc,
                        "url": a.get("url", ""),
                    })
            else:
                print(f"  ⚠ NewsAPI returned {resp.status_code}")
        except Exception as e:
            print(f"  ✗ News query failed: {e}")

    print(f"  ✓ {len(headlines)} relevant headlines (filtered from {len(seen_titles)} unique titles)")
    return headlines[:40]  # Cap at 40 (higher for earnings season)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"═══ IT Dashboard Data Refresh — {now.strftime('%Y-%m-%d %H:%M UTC')} ═══\n")

    output = {
        "updated": now.isoformat(),
        "updated_display": now.strftime("%d %b %Y, %H:%M UTC"),
        "prices": fetch_stock_prices(),
        "indices": fetch_indices(),
        "historical": fetch_historical_prices(),
        "news": fetch_news(),
    }

    # Write data.json
    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(outpath, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Wrote {outpath} ({os.path.getsize(outpath):,} bytes)")
    print(f"  {len(output['prices'])} stock prices")
    print(f"  {len(output['indices'])} indices")
    print(f"  {len(output['historical'])} historical price sets (mp/dp for trend charts)")
    print(f"  {len(output['news'])} news items")


if __name__ == "__main__":
    main()
