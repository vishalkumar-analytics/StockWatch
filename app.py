# Stock Watch web app (Streamlit)
# Information only - you take every buy/sell decision yourself. Not financial advice.
# Uses the functions in stock_watch.py (keep both files in the same GitHub repo).

import pandas as pd
import streamlit as st
import yfinance as yf

import stock_watch as sw

st.set_page_config(page_title="Stock Watch", page_icon="📈", layout="wide")


# ---------- data helpers (cached so the app stays fast) ----------
def to_symbol(text):
    """'itc' -> 'ITC.NS'. Keeps symbols that already have a dot (e.g. ITC.BO)."""
    s = text.strip().upper()
    return s if "." in s else s + ".NS"


@st.cache_data(ttl=900, show_spinner=False)   # refresh every 15 minutes
def load(sym):
    tk = yf.Ticker(sym)
    hist = tk.history(period="1y", interval="1d")
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    return hist, info


@st.cache_data(ttl=1800, show_spinner=False)  # news every 30 minutes
def load_news(company):
    return sw.news(company)


def analyse(sym):
    hist, info = load(sym)
    if hist is None or len(hist) < 60:
        return None
    name = info.get("longName") or info.get("shortName") or sym.replace(".NS", "")
    t = sw.technicals(hist)
    f = sw.fundamentals(info)
    n = load_news(name)
    sig = sw.signals(sym, t, f, n)
    return {"sym": sym, "name": name, "hist": hist, "t": t, "f": f, "news": n, "signals": sig}


def show_news(items):
    if not items:
        st.write("No news in the last 48 hours.")
    for it in items:
        flag = f" **[{it['flag']}]**" if it.get("flag") else ""
        title = it["title"].replace("[", "(").replace("]", ")")
        st.markdown(f"- [{title}]({it['link']}){flag}" if it.get("link") else f"- {title}{flag}")


# ---------- page ----------
st.title("📈 Stock Watch")
st.caption("Technical + Fundamental + News for NSE stocks. Information only, not financial advice. "
           "Prices from Yahoo Finance, may be 15-20 minutes late.")

default_list = ", ".join(s.replace(".NS", "") for s in sw.WATCHLIST)
with st.sidebar:
    st.header("My watchlist")
    wl_text = st.text_area("NSE symbols, separated by commas", default_list, height=140)
    st.caption("To change the default list for good, edit WATCHLIST in stock_watch.py on GitHub.")
    if st.button("Refresh data"):
        st.cache_data.clear()

tab_list, tab_one = st.tabs(["Watchlist", "Check one stock"])

# ---------- tab 1: whole watchlist ----------
with tab_list:
    syms = [to_symbol(x) for x in wl_text.split(",") if x.strip()]
    rows, details = [], []
    bar = st.progress(0.0, text="Loading...")
    for i, sym in enumerate(syms):
        try:
            r = analyse(sym)
        except Exception as e:
            r = None
            st.warning(f"{sym}: {e}")
        if r:
            details.append(r)
            rows.append({"Stock": sym.replace(".NS", ""), "Price": r["t"]["price"],
                         "1D %": r["t"]["chg_1d_%"], "5D %": r["t"]["chg_5d_%"], "RSI": r["t"]["rsi14"],
                         "Vol x avg": r["t"]["vol_x_avg"], "From 52W high %": r["t"]["from_52w_high_%"],
                         "P/E": r["f"].get("pe"), "ROE %": r["f"].get("roe_%"),
                         "D/E": r["f"].get("debt_to_equity"), "Signals": len(r["signals"]),
                         "What to look at": " | ".join(r["signals"])})
        elif sym:
            st.warning(f"{sym}: no data. Check the symbol.")
        bar.progress((i + 1) / max(len(syms), 1), text=f"Checked {sym}")
    bar.empty()

    if rows:
        table = pd.DataFrame(rows).sort_values("Signals", ascending=False)
        hits = table[table["Signals"] > 0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Stocks checked", len(table))
        c2.metric("With signals", len(hits))
        c3.metric("Biggest move today", f"{table.loc[table['1D %'].abs().idxmax(), 'Stock']}")
        st.dataframe(table, hide_index=True)

        st.subheader("News flags")
        flagged = [(d, it) for d in details for it in d["news"] if it.get("flag")]
        if flagged:
            for d, it in flagged:
                st.markdown(f"- **{d['sym'].replace('.NS', '')}** [{it['flag']}] [{it['title']}]({it['link']})")
        else:
            st.write("No flagged headlines right now.")

# ---------- tab 2: one stock in detail ----------
with tab_one:
    q = st.text_input("Type an NSE symbol (e.g. ITC, TCS, HDFCBANK)", "ITC")
    if q:
        sym = to_symbol(q)
        with st.spinner(f"Loading {sym}..."):
            try:
                r = analyse(sym)
            except Exception as e:
                r = None
                st.error(f"Could not load {sym}: {e}")
        if not r:
            st.error(f"No data for {sym}. Check the symbol on nseindia.com.")
        else:
            t, f = r["t"], r["f"]
            st.subheader(f"{r['name']} ({sym.replace('.NS', '')})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Price", f"₹{t['price']:,}", f"{t['chg_1d_%']}% today")
            c2.metric("RSI (14)", t["rsi14"])
            c3.metric("Volume vs 20-day avg", f"{t['vol_x_avg']}x")
            c4.metric("From 52-week high", f"{t['from_52w_high_%']}%")

            if r["signals"]:
                st.info("**What to look at:** " + " | ".join(r["signals"]))
            else:
                st.success("No special signal right now.")

            chart = pd.DataFrame({"Price": r["hist"]["Close"],
                                  "50-day avg": r["hist"]["Close"].rolling(50).mean(),
                                  "200-day avg": r["hist"]["Close"].rolling(200).mean()})
            chart.index = chart.index.tz_localize(None) if chart.index.tz is not None else chart.index
            st.line_chart(chart)

            left, right = st.columns(2)
            with left:
                st.markdown("**Technical**")
                st.dataframe(pd.DataFrame({
                    "Measure": ["5-day change %", "Above 50-day avg", "Above 200-day avg",
                                "From 52-week low %", "20/50 cross up today", "20/50 cross down today"],
                    "Value": [t["chg_5d_%"], t["above_sma50"], t["above_sma200"],
                              t["from_52w_low_%"], t["cross_up"], t["cross_down"]]}).astype(str),
                    hide_index=True)
            with right:
                st.markdown("**Fundamental**")
                labels = {"mcap_cr": "Market cap (₹ crore)", "pe": "P/E", "pb": "P/B", "roe_%": "ROE %",
                          "debt_to_equity": "Debt to equity (%)", "profit_margin_%": "Profit margin %",
                          "revenue_growth_%": "Revenue growth %", "earnings_growth_%": "Earnings growth %",
                          "dividend_yield_%": "Dividend yield %"}
                st.dataframe(pd.DataFrame({"Measure": list(labels.values()),
                                           "Value": [("-" if f.get(k) is None else str(f[k])) for k in labels]}),
                             hide_index=True)

            st.markdown("**News (last 48 hours)**")
            show_news(r["news"])

st.divider()
st.caption("RSI below 30 = oversold, above 70 = overbought. News flags only look for words in headlines - "
           "read the article before you act.")
