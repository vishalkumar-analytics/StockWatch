# =============================================================
# STOCK WATCH - information only, no automatic trading
# Shows Technical + Fundamental + News for your NSE watchlist
# Run in Google Colab. You take every buy/sell decision yourself.
# This is not financial advice.
# =============================================================

# ---------- STEP 0: install (Colab only, first run) ----------
# !pip install -q yfinance

import re
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pandas as pd

# ---------- STEP 1: YOUR SETTINGS (change these) ----------
# NSE stocks end with ".NS". Example: "ITC.NS"
WATCHLIST = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "INFY.NS": "Infosys",
    "ITC.NS": "ITC",
    "SBIN.NS": "State Bank of India",
    "LT.NS": "Larsen & Toubro",
    "BHARTIARTL.NS": "Bharti Airtel",
}

# Your own price levels (optional). Leave {} if not needed.
MY_LEVELS = {
    # "ITC.NS": {"target": 500, "stop_loss": 400},
}

RSI_LOW, RSI_HIGH = 30, 70        # oversold / overbought
VOLUME_SPIKE = 2.0                # volume x times the 20-day average
NEAR_52W = 0.03                   # within 3% of 52-week high or low
NEWS_HOURS = 48                   # look at news from the last 48 hours

# Telegram alert (optional). Leave empty to skip.
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# Words that make a headline worth a closer look
NEWS_GOOD = ["order win", "bags order", "upgrade", "buyback", "dividend", "record profit",
             "profit rises", "profit jumps", "beats estimates", "approval", "acquisition"]
NEWS_BAD = ["downgrade", "raid", "fraud", "penalty", "probe", "resigns", "default",
            "profit falls", "loss widens", "misses estimates", "sebi order", "pledge"]


# ---------- STEP 2: TECHNICAL ----------
def rsi(close, period=14):
    """Relative Strength Index (Wilder's method)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def technicals(hist):
    """hist = daily price table with Close and Volume columns (about 1 year)."""
    c, v = hist["Close"], hist["Volume"]
    last = c.iloc[-1]
    hi52, lo52 = c.tail(252).max(), c.tail(252).min()
    sma20, sma50, sma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    vol_avg = v.iloc[-21:-1].mean()
    return {
        "price": round(last, 2),
        "chg_1d_%": round((last / c.iloc[-2] - 1) * 100, 2),
        "chg_5d_%": round((last / c.iloc[-6] - 1) * 100, 2),
        "rsi14": round(rsi(c).iloc[-1], 1),
        "above_sma50": bool(last > sma50.iloc[-1]),
        "above_sma200": bool(last > sma200.iloc[-1]) if pd.notna(sma200.iloc[-1]) else None,
        # golden cross = 20-day average crossed above 50-day average today
        "cross_up": bool(sma20.iloc[-2] <= sma50.iloc[-2] and sma20.iloc[-1] > sma50.iloc[-1]),
        "cross_down": bool(sma20.iloc[-2] >= sma50.iloc[-2] and sma20.iloc[-1] < sma50.iloc[-1]),
        "vol_x_avg": round(v.iloc[-1] / vol_avg, 2) if vol_avg else None,
        "from_52w_high_%": round((last / hi52 - 1) * 100, 2),
        "from_52w_low_%": round((last / lo52 - 1) * 100, 2),
    }


# ---------- STEP 3: FUNDAMENTAL ----------
def fundamentals(info):
    """info = yfinance Ticker.info dictionary. Missing values stay empty."""
    def pct(x):
        return round(x * 100, 1) if isinstance(x, (int, float)) else None

    def num(x, d=1):
        return round(x, d) if isinstance(x, (int, float)) else None

    return {
        "mcap_cr": num((info.get("marketCap") or 0) / 1e7, 0) or None,  # crore rupees
        "pe": num(info.get("trailingPE")),
        "pb": num(info.get("priceToBook")),
        "roe_%": pct(info.get("returnOnEquity")),
        "debt_to_equity": num(info.get("debtToEquity")),  # in %, so 100 = debt equals equity
        "profit_margin_%": pct(info.get("profitMargins")),
        "revenue_growth_%": pct(info.get("revenueGrowth")),
        "earnings_growth_%": pct(info.get("earningsGrowth")),
        "dividend_yield_%": num(info.get("dividendYield")),
    }


# ---------- STEP 4: NEWS (Google News RSS, free) ----------
def news(company, hours=NEWS_HOURS, limit=5):
    q = urllib.parse.quote(f'"{company}" share OR stock')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        return [{"title": f"(news not loaded: {e})", "link": "", "flag": ""}]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for item in root.iter("item"):
        try:
            when = pd.to_datetime(item.findtext("pubDate"), utc=True)
        except Exception:
            continue
        if when < cutoff:
            continue
        title = html.unescape(item.findtext("title") or "")
        out.append({"title": title, "link": item.findtext("link") or "",
                    "when": when, "flag": news_flag(title)})
    out.sort(key=lambda n: n["when"], reverse=True)
    return out[:limit]


def news_flag(title):
    t = title.lower()
    if any(w in t for w in NEWS_BAD):
        return "NEGATIVE?"
    if any(w in t for w in NEWS_GOOD):
        return "POSITIVE?"
    return ""


# ---------- STEP 5: SIGNALS (plain-English reasons to look) ----------
def signals(sym, t, f, n):
    s = []
    if t["rsi14"] <= RSI_LOW:
        s.append(f"RSI {t['rsi14']} - oversold")
    if t["rsi14"] >= RSI_HIGH:
        s.append(f"RSI {t['rsi14']} - overbought")
    if t["vol_x_avg"] and t["vol_x_avg"] >= VOLUME_SPIKE:
        s.append(f"Volume {t['vol_x_avg']}x normal")
    if t["from_52w_high_%"] >= -NEAR_52W * 100:
        s.append("Near 52-week HIGH")
    if t["from_52w_low_%"] <= NEAR_52W * 100:
        s.append("Near 52-week LOW")
    if t["cross_up"]:
        s.append("20-day avg crossed ABOVE 50-day avg")
    if t["cross_down"]:
        s.append("20-day avg crossed BELOW 50-day avg")
    lv = MY_LEVELS.get(sym, {})
    if lv.get("target") and t["price"] >= lv["target"]:
        s.append(f"Reached your target {lv['target']}")
    if lv.get("stop_loss") and t["price"] <= lv["stop_loss"]:
        s.append(f"Hit your stop-loss {lv['stop_loss']}")
    if f.get("debt_to_equity") and f["debt_to_equity"] > 200:
        s.append(f"High debt (D/E {f['debt_to_equity']})")
    flagged = [x for x in n if x.get("flag")]
    if flagged:
        s.append(f"{len(flagged)} news headline(s) flagged")
    return s


# ---------- STEP 6: RUN EVERYTHING ----------
def run():
    import yfinance as yf
    rows, all_news = [], {}
    for sym, name in WATCHLIST.items():
        print("Checking", sym, "...")
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="1y", interval="1d")
            if len(hist) < 60:
                print("  not enough price data, skipped")
                continue
            t = technicals(hist)
            try:
                f = fundamentals(tk.info)
            except Exception:
                f = {}
            n = news(name)
            sig = signals(sym, t, f, n)
            rows.append({"symbol": sym.replace(".NS", ""), **t, **f,
                         "signals": " | ".join(sig), "n_signals": len(sig)})
            all_news[sym.replace(".NS", "")] = n
        except Exception as e:
            print("  error:", e)
    table = pd.DataFrame(rows).sort_values("n_signals", ascending=False)
    return table, all_news


def html_report(table, all_news, path="stock_watch_report.html"):
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    parts = [f"<h1>Stock Watch - {stamp}</h1>",
             "<p><i>Information only. Not financial advice. You decide every trade.</i></p>",
             "<h2>Summary</h2>", table.to_html(index=False, na_rep="-"), "<h2>News</h2>"]
    for sym, items in all_news.items():
        parts.append(f"<h3>{sym}</h3><ul>")
        for it in items or [{"title": "No news in this period", "link": "", "flag": ""}]:
            flag = f" <b>[{it['flag']}]</b>" if it.get("flag") else ""
            link = f"<a href='{it['link']}'>{html.escape(it['title'])}</a>" if it["link"] else html.escape(it["title"])
            parts.append(f"<li>{link}{flag}</li>")
        parts.append("</ul>")
    style = ("<style>body{font-family:Arial;margin:24px}table{border-collapse:collapse;font-size:12px}"
             "td,th{border:1px solid #ccc;padding:4px 6px}th{background:#1E3A40;color:#fff}</style>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<html><head><meta charset='utf-8'>" + style + "</head><body>" + "".join(parts) + "</body></html>")
    return path


def telegram(table):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    hits = table[table["n_signals"] > 0]
    if hits.empty:
        msg = "Stock Watch: no signals today."
    else:
        msg = "Stock Watch\n" + "\n".join(f"{r.symbol} ({r.price}): {r.signals}" for r in hits.itertuples())
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": msg[:4000]}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data, timeout=15)
    print("Telegram alert sent.")


if __name__ == "__main__":
    table, all_news = run()
    cols = ["symbol", "price", "chg_1d_%", "rsi14", "vol_x_avg", "from_52w_high_%", "pe", "roe_%", "debt_to_equity", "signals"]
    print(table[cols].to_string(index=False))
    print("\nReport saved:", html_report(table, all_news))
    table.to_csv("stock_watch_table.csv", index=False)
    telegram(table)
