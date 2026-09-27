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

    def is_relevant(title, desc):
        """Return (True, ticker) if article is about our IT services universe."""
        text = f"{title} {desc}".upper()
        # Check company names first
        for tk_key, info in TICKERS.items():
            names_to_check = [tk_key.upper(), info["name"].upper()]
            first_word = info["name"].split()[0].upper()
            if len(first_word) > 3:
                names_to_check.append(first_word)
            for name in names_to_check:
                if name in text:
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
    ]

    seen = set()
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
                    if not title or title in seen:
                        continue
                    # ── STRICT relevance gate ──
                    relevant, tk = is_relevant(title, desc)
                    if not relevant:
                        continue
                    seen.add(title)
                    headlines.append({
                        "time": a.get("publishedAt", "")[:16].replace("T", " "),
                        "tk": tk,
                        "src": a.get("source", {}).get("name", "NEWS"),
                        "hl": title,
                        "detail": desc,
                        "url": a.get("url", ""),
                    })
            else:
                print(f"  ⚠ NewsAPI returned {resp.status_code}")
        except Exception as e:
            print(f"  ✗ News query failed: {e}")

    print(f"  ✓ {len(headlines)} relevant headlines (filtered from {len(seen)} total)")
    return headlines[:25]  # Cap at 25


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"═══ IT Dashboard Data Refresh — {now.strftime('%Y-%m-%d %H:%M UTC')} ═══\n")

    output = {
        "updated": now.isoformat(),
        "updated_display": now.strftime("%d %b %Y, %H:%M UTC"),
        "prices": fetch_stock_prices(),
        "indices": fetch_indices(),
        "news": fetch_news(),
    }

    # Write data.json
    outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(outpath, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Wrote {outpath} ({os.path.getsize(outpath):,} bytes)")
    print(f"  {len(output['prices'])} stock prices")
    print(f"  {len(output['indices'])} indices")
    print(f"  {len(output['news'])} news items")


if __name__ == "__main__":
    main()
