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

    _STOP_WORDS = {'a','an','the','to','for','of','in','on','at','by','is','are',
                    'was','were','with','and','or','but','from','has','have','had',
                    'been','be','its','it','that','this','as'}

    def _extract_entities(title):
        """Extract likely entity words: capitalised words 4+ chars."""
        ents = set()
        for w in _re.sub(r"[^\w\s'-]", '', title).split():
            if len(w) >= 4 and w[0].isupper():
                ents.add(w.lower())
        return ents

    def _is_duplicate(title, tk, seen_entries):
        """Check if a title is a near-duplicate of any seen title.
        Uses stop-word-filtered overlap + entity matching for same-ticker stories."""
        norm = _normalize(title)
        all_words = set(norm.split())
        sig_words = {w for w in all_words if len(w) > 2 and w not in _STOP_WORDS}
        ents = _extract_entities(title)
        if len(all_words) < 3:
            return any(norm == e['norm'] for e in seen_entries.values())
        for entry in seen_entries.values():
            # 1. Same ticker + 2+ shared entity words = duplicate
            if tk and tk == entry.get('tk') and len(ents) >= 2 and len(entry.get('ents', set())) >= 2:
                common_ents = ents & entry['ents']
                if len(common_ents) >= 2:
                    return True
            # 2. Significant-word overlap (no stop words)
            if entry['sig']:
                common_sig = sig_words & entry['sig']
                overlap_sig = max(
                    len(common_sig) / len(sig_words) if sig_words else 0,
                    len(common_sig) / len(entry['sig']) if entry['sig'] else 0
                )
                if overlap_sig >= 0.55:
                    return True
            # 3. All-word overlap
            common_all = all_words & entry['all']
            overlap_all = max(
                len(common_all) / len(all_words) if all_words else 0,
                len(common_all) / len(entry['all']) if entry['all'] else 0
            )
            if overlap_all >= 0.6:
                return True
        return False

    # Restrict to last 2 days to ensure fresh news
    from_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).strftime("%Y-%m-%d")

    seen_entries = {}  # {exact_title: {norm, all, sig, ents, tk}}
    for q in queries:
        try:
            resp = requests.get("https://newsapi.org/v2/everything", params={
                "q": q,
                "from": from_date,
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
                    if not title or title in seen_entries:
                        continue
                    # ── STRICT relevance gate ──
                    relevant, tk = is_relevant(title, desc)
                    if not relevant:
                        continue
                    # ── Fuzzy dedup: skip near-duplicate headlines ──
                    if _is_duplicate(title, tk, seen_entries):
                        continue
                    norm = _normalize(title)
                    norm_words = set(norm.split())
                    seen_entries[title] = {
                        'norm': norm,
                        'all': norm_words,
                        'sig': {w for w in norm_words if len(w) > 2 and w not in _STOP_WORDS},
                        'ents': _extract_entities(title),
                        'tk': tk,
                    }
                    # Auto-detect category from headline + description
                    upper_text = f"{title} {desc}".upper()
                    if any(kw in upper_text for kw in
                           ['RESULTS', 'EARNINGS', 'QUARTERLY', 'PROFIT', 'REVENUE',
                            'EBIT', 'EPS', 'PAT ', 'NET INCOME', 'Q1 ', 'Q2 ', 'Q3 ', 'Q4 ',
                            'FY26', 'FY27', 'FISCAL', 'MARGIN', 'BEAT', 'MISS',
                            'BLOCKBUSTER', 'ESTIMATES', 'OUTLOOK', 'GUIDANCE']):
                        cat = 'RESULTS'
                    elif any(kw in upper_text for kw in
                             ['DEAL', 'CONTRACT', 'WIN', 'AWARD', 'PARTNER', 'ACQUISITION',
                              'ACQUIRE', 'MERGER', 'MERGE', 'BUYOUT', 'TAKEOVER', ' GCC ']):
                        cat = 'DEAL'
                    elif any(kw in upper_text for kw in
                             ['FORECAST', 'TARGET', 'UPGRADE',
                              'DOWNGRADE', 'RATING', ' BUY', 'SELL', ' ADD ',
                              'STOCK PICK', 'RISK-REWARD', 'RISK REWARD']):
                        cat = 'ANALYST'
                    elif any(kw in upper_text for kw in
                             [' AI ', 'ARTIFICIAL INTELLIGENCE', 'GENAI', 'MACHINE LEARNING',
                              'AUTOMATION', ' RPA ', 'DIGITAL TRANSFORM']):
                        cat = 'AI'
                    elif any(kw in upper_text for kw in
                             ['CEO', 'CTO', 'CFO', 'COO', 'APPOINT', 'RESIGN', 'HIRE', 'BOARD',
                              'CHAIRMAN', 'CHAIRPERSON', 'LEADERSHIP', 'LAYOFF', 'RETRENCH']):
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

    print(f"  ✓ {len(headlines)} relevant headlines (filtered from {len(seen_entries)} unique titles)")
    return headlines[:40]  # Cap at 40 (higher for earnings season)


# ─── Fiscal year metadata for each company ───
# fyEnd = month number (1-12) the fiscal year ends in
# Indian companies: Mar (3), Accenture: Aug (8), Capgemini: Dec (12), etc.
FISCAL_YEARS = {
    "TCS": 3, "INFY": 3, "CTSH": 12, "HCLT": 3, "WIPRO": 3,
    "TECHM": 3, "LTIM": 3, "MPHL": 3, "PSYS": 3, "COFG": 3,
    "ACN": 8, "CAP": 12, "NTTD": 3, "ATOS": 12, "DXC": 3, "GIB": 9,
}

# Currency divisors: convert raw financials to $B
# Indian companies report in INR (divide by ~83-85 for USD, but we'll use yfinance which reports in local currency)
# We'll convert everything to USD billions for consistency
CURRENCY_INFO = {
    "TCS": {"curr": "INR", "div": 1e9}, "INFY": {"curr": "INR", "div": 1e9},
    "CTSH": {"curr": "USD", "div": 1e9}, "HCLT": {"curr": "INR", "div": 1e9},
    "WIPRO": {"curr": "INR", "div": 1e9}, "TECHM": {"curr": "INR", "div": 1e9},
    "LTIM": {"curr": "INR", "div": 1e9}, "MPHL": {"curr": "INR", "div": 1e9},
    "PSYS": {"curr": "INR", "div": 1e9}, "COFG": {"curr": "INR", "div": 1e9},
    "ACN": {"curr": "USD", "div": 1e9}, "CAP": {"curr": "EUR", "div": 1e9},
    "NTTD": {"curr": "JPY", "div": 1e9}, "ATOS": {"curr": "EUR", "div": 1e9},
    "DXC": {"curr": "USD", "div": 1e9}, "GIB": {"curr": "CAD", "div": 1e9},
}


def fetch_forex_rates():
    """Fetch latest USD exchange rates for all non-USD currencies used by tracked companies.

    Uses yfinance forex pairs to get live spot rates.
    Returns dict: {"EUR": 1.09, "JPY": 0.0067, "CAD": 0.74, "INR": 0.012, "USD": 1.0}
    (all rates are X_to_USD, i.e., multiply local currency by rate to get USD)
    """
    print("Fetching forex rates...")
    # yfinance forex pairs: XXXUSD=X gives price of 1 XXX in USD
    pairs = {
        "EUR": "EURUSD=X",
        "JPY": "JPYUSD=X",   # fallback: use 1/USDJPY
        "CAD": "CADUSD=X",
        "INR": "INRUSD=X",
    }
    rates = {"USD": 1.0}

    for curr, sym in pairs.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if hist is not None and not hist.empty:
                rate = float(hist["Close"].iloc[-1])
                rates[curr] = round(rate, 6)
                print(f"  ✓ {curr}/USD: {rate:.6f}")
            else:
                # Fallback: try inverse pair
                inv_sym = f"USD{curr}=X"
                ticker2 = yf.Ticker(inv_sym)
                hist2 = ticker2.history(period="5d")
                if hist2 is not None and not hist2.empty:
                    inv_rate = float(hist2["Close"].iloc[-1])
                    rate = round(1.0 / inv_rate, 6)
                    rates[curr] = rate
                    print(f"  ✓ {curr}/USD (via inverse): {rate:.6f}")
                else:
                    print(f"  ⚠ {curr}: no forex data, using fallback")
                    # Hardcoded fallbacks (approximate, updated rarely)
                    fallbacks = {"EUR": 1.09, "JPY": 0.0067, "CAD": 0.74, "INR": 0.012}
                    rates[curr] = fallbacks.get(curr, 1.0)
        except Exception as e:
            print(f"  ✗ {curr}: {e}")
            fallbacks = {"EUR": 1.09, "JPY": 0.0067, "CAD": 0.74, "INR": 0.012}
            rates[curr] = fallbacks.get(curr, 1.0)

    return rates


def fetch_quarterly_financials(forex_rates=None):
    """Fetch quarterly income statement + cash flow for all tracked companies.

    Uses yfinance to pull data from official filings (SEC EDGAR, BSE, etc.).
    When forex_rates is provided, adds USD-converted values alongside local currency.
    Returns dict keyed by dashboard ticker:
      { "ACN": {
          "quarters": [
            {"date": "2025-11-30", "label": "Q1 FY26", "rev": 18.74, "rev_usd": 18.74,
             "ebit_margin": 15.3, "fcf": 1.5, "fcf_usd": 1.5},
            ...
          ],
          "annual": {"rev": 74.2, "rev_usd": 74.2, "growth": 5.0, "ebit_margin": 15.4,
                     "op_profit": 11410, "fcf": 11.62, "fcf_usd": 11.62},
          "fy_end_month": 8,
          "currency": "USD",
          "usd_rate": 1.0
        }, ...
      }
    """
    print("Fetching quarterly financials...")
    if forex_rates is None:
        forex_rates = {"USD": 1.0}
    quarterly = {}

    for tk, info in TICKERS.items():
        sym = info["yf"]
        fy_end = FISCAL_YEARS.get(tk, 3)
        curr_info = CURRENCY_INFO.get(tk, {"curr": "USD", "div": 1e9})

        try:
            ticker = yf.Ticker(sym)

            # ── Income statement (quarterly) ──
            inc = ticker.quarterly_income_stmt
            if inc is None or inc.empty:
                print(f"  ⚠ {tk}: no income statement data")
                continue

            # ── Cash flow (quarterly) ──
            cf = ticker.quarterly_cashflow
            has_cf = cf is not None and not cf.empty

            # yfinance returns columns as dates (most recent first)
            # We want up to 12 quarters, sorted oldest-first
            dates = sorted(inc.columns)[-12:]  # last 12 quarters

            quarters = []
            for dt in dates:
                q_data = {}
                q_data["date"] = dt.strftime("%Y-%m-%d")

                # Generate FY quarter label from date and fiscal year end
                q_label = _make_quarter_label(dt, fy_end)
                q_data["label"] = q_label

                # Revenue — try multiple field names
                rev = _get_field(inc, dt, [
                    "Total Revenue", "Revenue", "Operating Revenue",
                    "Net Revenue", "Total Net Revenue"
                ])
                if rev is None:
                    continue  # skip quarter if no revenue
                rev_scaled = round(rev / curr_info["div"], 2)
                q_data["rev"] = rev_scaled
                # USD-converted revenue
                fx = forex_rates.get(curr_info["curr"], 1.0)
                q_data["rev_usd"] = round(rev_scaled * fx, 2)

                # Operating income / EBIT
                ebit = _get_field(inc, dt, [
                    "Operating Income", "EBIT", "Operating Profit",
                    "Total Operating Income As Reported"
                ])
                if ebit is not None and rev > 0:
                    q_data["ebit_margin"] = round(ebit / rev * 100, 1)
                    q_data["op_profit"] = round(ebit / curr_info["div"] * 1000, 0)  # in $M equivalent
                else:
                    q_data["ebit_margin"] = None
                    q_data["op_profit"] = None

                # Free cash flow from cash flow statement
                if has_cf and dt in cf.columns:
                    opcf = _get_field(cf, dt, [
                        "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                        "Free Cash Flow", "Total Cash From Operating Activities"
                    ])
                    capex = _get_field(cf, dt, [
                        "Capital Expenditure", "Purchase Of PPE",
                        "Capital Expenditures"
                    ])
                    if opcf is not None:
                        # If "Free Cash Flow" was found directly, use it
                        fcf_row = _get_field(cf, dt, ["Free Cash Flow"])
                        if fcf_row is not None:
                            q_data["fcf"] = round(fcf_row / curr_info["div"], 2)
                        elif capex is not None:
                            # capex is usually negative in yfinance
                            q_data["fcf"] = round((opcf + capex) / curr_info["div"], 2)
                        else:
                            q_data["fcf"] = round(opcf / curr_info["div"], 2)
                    else:
                        q_data["fcf"] = None
                else:
                    q_data["fcf"] = None

                # USD-converted FCF
                if q_data.get("fcf") is not None:
                    q_data["fcf_usd"] = round(q_data["fcf"] * fx, 2)
                else:
                    q_data["fcf_usd"] = None

                quarters.append(q_data)

            if not quarters:
                print(f"  ⚠ {tk}: no valid quarters extracted")
                continue

            # ── Compute annual totals from last 4 quarters ──
            last4 = quarters[-4:] if len(quarters) >= 4 else quarters
            annual_rev = sum(q["rev"] for q in last4)
            annual_ebit_margins = [q["ebit_margin"] for q in last4 if q.get("ebit_margin") is not None]
            annual_margin = round(sum(annual_ebit_margins) / len(annual_ebit_margins), 1) if annual_ebit_margins else None
            annual_op_profit = sum(q.get("op_profit", 0) or 0 for q in last4)
            annual_fcf_vals = [q.get("fcf") for q in last4 if q.get("fcf") is not None]
            annual_fcf = round(sum(annual_fcf_vals), 2) if annual_fcf_vals else None

            # USD-converted annual totals
            fx = forex_rates.get(curr_info["curr"], 1.0)
            annual_rev_usd = round(annual_rev * fx, 1)
            annual_fcf_usd = round(annual_fcf * fx, 2) if annual_fcf is not None else None

            # YoY revenue growth (last 4 vs prior 4)
            yoy_growth = None
            if len(quarters) >= 8:
                prior4 = quarters[-8:-4]
                prior_rev = sum(q["rev"] for q in prior4)
                if prior_rev > 0:
                    yoy_growth = round((annual_rev - prior_rev) / prior_rev * 100, 1)

            quarterly[tk] = {
                "quarters": quarters,
                "annual": {
                    "rev": round(annual_rev, 1),
                    "rev_usd": annual_rev_usd,
                    "growth": yoy_growth,
                    "ebit_margin": annual_margin,
                    "op_profit": round(annual_op_profit),
                    "op_profit_usd": round(annual_op_profit * fx),
                    "fcf": annual_fcf,
                    "fcf_usd": annual_fcf_usd,
                },
                "fy_end_month": fy_end,
                "currency": curr_info["curr"],
                "usd_rate": fx,
            }
            print(f"  ✓ {tk}: {len(quarters)} quarters, latest={quarters[-1]['label']} rev={quarters[-1]['rev']}")

        except Exception as e:
            print(f"  ✗ {tk}: {e}")

    print(f"  Total: {len(quarterly)} companies with quarterly data")
    return quarterly


def _make_quarter_label(dt, fy_end_month):
    """Generate a FY quarter label like 'Q2 FY26' from a quarter-end date and FY end month.

    fy_end_month: the month the fiscal year ends (3=Mar, 8=Aug, 12=Dec, etc.)
    The quarter containing fy_end_month is Q4.

    Examples for fy_end_month=3 (Indian companies):
      Jan-Mar -> Q4 FYxx, Apr-Jun -> Q1 FYxx+1, Jul-Sep -> Q2, Oct-Dec -> Q3
    For fy_end_month=8 (Accenture):
      Sep-Nov -> Q1, Dec-Feb -> Q2, Mar-May -> Q3, Jun-Aug -> Q4
    """
    m = dt.month
    y = dt.year

    # Compute which quarter (1-4) this month falls in relative to FY
    # Q4 ends in fy_end_month, Q3 ends 3 months before, etc.
    # Month offset from FY start
    fy_start_month = (fy_end_month % 12) + 1  # month after FY end = FY start
    # How many months after FY start?
    offset = (m - fy_start_month) % 12
    q_num = (offset // 3) + 1  # 1-4

    # FY year label: if we're past fy_end_month, we're in the next FY
    if fy_end_month == 12:
        fy_year = y
    elif m > fy_end_month:
        fy_year = y + 1
    else:
        fy_year = y

    return f"Q{q_num} FY{str(fy_year)[-2:]}"


def _get_field(df, col, field_names):
    """Try multiple row names in a yfinance DataFrame, return first found value."""
    for name in field_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and str(val) != 'nan':
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
    return None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"═══ IT Dashboard Data Refresh — {now.strftime('%Y-%m-%d %H:%M UTC')} ═══\n")

    forex = fetch_forex_rates()

    output = {
        "updated": now.isoformat(),
        "updated_display": now.strftime("%d %b %Y, %H:%M UTC"),
        "prices": fetch_stock_prices(),
        "indices": fetch_indices(),
        "historical": fetch_historical_prices(),
        "news": fetch_news(),
        "quarterly": fetch_quarterly_financials(forex),
        "forex_rates": forex,
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
    print(f"  {len(output['quarterly'])} companies with quarterly financials")
    print(f"  Forex rates: {', '.join(f'{k}={v}' for k,v in output['forex_rates'].items())}")


if __name__ == "__main__":
    main()
