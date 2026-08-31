import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import requests

st.set_page_config(page_title="Pro Algo & Strike Selector", layout="wide")

st.title("🎯 Pro Market Trend, Strike Selector & Telegram Alerts")

# Pre-configured Telegram credentials
BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"

# Telegram Send Function
def send_telegram_alert(token, chat_id, message_text):
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message_text, "parse_mode": "Markdown"}
        try:
            res = requests.post(url, json=payload, timeout=5)
            return res.status_code == 200
        except Exception:
            return False
    return False

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Configuration")
asset_choice = st.sidebar.selectbox(
    "Asset Chunein",
    ["^NSEI (NIFTY 50)", "^NSEBANK (BANK NIFTY)", "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS"],
    index=0
)
clean_ticker = asset_choice.split(" ")[0]
timeframe = st.sidebar.selectbox("Timeframe", ["1d", "1h", "15m", "5m"], index=0)

if timeframe in ["5m", "15m"]:
    period_options = ["1d", "5d", "1mo"]
    default_p_idx = 1
elif timeframe == "1h":
    period_options = ["5d", "1mo", "3mo", "6mo"]
    default_p_idx = 2
else:
    period_options = ["1mo", "3mo", "6mo", "1y", "2y"]
    default_p_idx = 2

period = st.sidebar.selectbox("Data Period", period_options, index=default_p_idx)

# Helper function to fetch live PCR
def fetch_pcr(symbol_name):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol_name}"
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        response = session.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            total_ce_oi = data['filtered']['CE']['totOI']
            total_pe_oi = data['filtered']['PE']['totOI']
            pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0
            return round(pcr, 2), total_pe_oi, total_ce_oi
    except Exception:
        return None, None, None
    return None, None, None

# 1. Fetch Main Asset Data
data = yf.download(clean_ticker, period=period, interval=timeframe)

# 2. Fetch India VIX Data
vix_data = yf.download("^INDIAVIX", period="5d", interval="1d")
latest_vix = None
vix_change = 0.0

if not vix_data.empty:
    v_close = vix_data['Close'].values.flatten() if hasattr(vix_data['Close'], 'values') else vix_data['Close']
    latest_vix = float(v_close[-1])
    if len(v_close) > 1:
        prev_vix = float(v_close[-2])
        vix_change = ((latest_vix - prev_vix) / prev_vix) * 100

# 3. Fetch PCR if Index selected
pcr_val, pe_oi, ce_oi = None, None, None
if "NSEI" in clean_ticker:
    pcr_val, pe_oi, ce_oi = fetch_pcr("NIFTY")
elif "NSEBANK" in clean_ticker:
    pcr_val, pe_oi, ce_oi = fetch_pcr("BANKNIFTY")

if not data.empty and len(data) > 5:
    # Calculations: Moving Averages & Volume
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Vol_SMA_20'] = data['Volume'].rolling(window=20).mean()

    # RSI
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    # ATR (Average True Range) for Dynamic Stoploss/Targets
    high_low = data['High'] - data['Low']
    high_cp = np.abs(data['High'] - data['Close'].shift())
    low_cp = np.abs(data['Low'] - data['Close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    data['ATR'] = tr.rolling(14).mean()

    latest = data.iloc[-1]
    prev = data.iloc[-2]

    def get_val(series):
        v = series.values[0] if hasattr(series, 'values') else series
        return float(v)

    c_price = get_val(latest['Close'])
    p_price = get_val(prev['Close'])
    e20 = get_val(latest['EMA_20'])
    e50 = get_val(latest['EMA_50'])
    rsi = get_val(latest['RSI'])
    c_vol = get_val(latest['Volume'])
    avg_vol = get_val(latest['Vol_SMA_20'])
    atr_val = get_val(latest['ATR']) if not np.isnan(get_val(latest['ATR'])) else (c_price * 0.005)

    pct_change = ((c_price - p_price) / p_price) * 100 if p_price > 0 else 0
    vol_ratio = (c_vol / avg_vol) if avg_vol > 0 else 1.0

    # Top Metrics Bar
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Current Price", f"₹{c_price:.2f}", f"{pct_change:.2f}%")
    col2.metric("20 EMA", f"₹{e20:.2f}")
    col3.metric("50 EMA", f"₹{e50:.2f}")
    col4.metric("RSI (14)", f"{rsi:.1f}")
    
    if latest_vix is not None:
        col5.metric("India VIX", f"{latest_vix:.2f}", f"{vix_change:.2f}%")
    else:
        col5.metric("India VIX", "N/A")

    # Options PCR & Volatility Row
    st.write("### 📌 Options PCR & Volatility Health")
    c_pcr, c_vol_status = st.columns(2)

    with c_pcr:
        if pcr_val is not None:
            if pcr_val >= 1.2:
                st.success(f"📈 **PCR: {pcr_val} (Bullish Bias)** — Put Writing active, Support strong.")
            elif pcr_val <= 0.75:
                st.error(f"📉 **PCR: {pcr_val} (Bearish Bias)** — Call Writing active, Resistance strong.")
            else:
                st.info(f"⚖️ **PCR: {pcr_val} (Neutral / Sideways)** — Range-bound movement.")
        else:
            st.info("ℹ️ Index (NIFTY / BANKNIFTY) par PCR live evaluate hota hai.")

    with c_vol_status:
        if vol_ratio >= 1.5:
            st.success(f"🔥 **Volume Spike Active:** Current volume {vol_ratio:.1f}x of 20-period average.")
        else:
            st.info(f"📊 **Volume Normal:** Trade volume around {vol_ratio:.1f}x of average.")

    # Strike Selector & Strategy Rules
    step = 50 if "NSEI" in clean_ticker else (100 if "NSEBANK" in clean_ticker else 10)
    atm_strike = round(c_price / step) * step

    trend_bullish = e20 > e50 and c_price > e20
    trend_bearish = e20 < e50 and c_price < e20

    # Trade Setup Calculations
    action = "WAIT"
    suggested_strike = ""
    stop_loss = 0.0
    target_1 = 0.0
    target_2 = 0.0
    sl_points = round(atr_val * 1.2, 1)

    if trend_bullish and vol_ratio >= 1.2:
        action = "BUY_CALL"
        itm_strike = atm_strike - step
        suggested_strike = f"{int(itm_strike)} CE (Slight ITM) ya {int(atm_strike)} CE (ATM)"
        stop_loss = c_price - sl_points
        target_1 = c_price + (sl_points * 1.5)
        target_2 = c_price + (sl_points * 2.5)
    elif trend_bearish and vol_ratio >= 1.2:
        action = "BUY_PUT"
        itm_strike = atm_strike + step
        suggested_strike = f"{int(itm_strike)} PE (Slight ITM) ya {int(atm_strike)} PE (ATM)"
        stop_loss = c_price + sl_points
        target_1 = c_price - (sl_points * 1.5)
        target_2 = c_price - (sl_points * 2.5)

    # Strategy & Strike Recommendation Box
    st.write("### 💡 Recommended Option Strike & Trade Plan")
    rec_col1, rec_col2 = st.columns(2)

    with rec_col1:
        if action == "BUY_CALL":
            st.success(f"🟢 **RECOMMENDED ACTION: BUY CALL (CE)**\n\n🎯 **Best Strike:** `{suggested_strike}`\n\n⚡ **Rationale:** Price 20 EMA ke upar hai aur volume breakout support kar raha hai.")
        elif action == "BUY_PUT":
            st.error(f"🔴 **RECOMMENDED ACTION: BUY PUT (PE)**\n\n🎯 **Best Strike:** `{suggested_strike}`\n\n⚡ **Rationale:** Price 20 EMA ke niche hai aur heavy volume selling chal rahi hai.")
        elif rsi >= 70:
            st.warning("⚠️ **OVERBOUGHT:** Market high par stretch ho chuka hai. Fresh CE buy avoid karein.")
        elif rsi <= 30:
            st.info("🔄 **OVERSOLD BOUNCE:** Market bottom zone me hai. Reversal pattern ka wait karein.")
        else:
            st.info(f"🟡 **NO DIRECT TRADE (WAIT):** Clear momentum nahi hai.\n\n*Reference ATM Strike:* **{int(atm_strike)}**")

    with rec_col2:
        if action in ["BUY_CALL", "BUY_PUT"]:
            st.markdown(f"""
            * **Spot Entry Level:** ₹{c_price:.2f}
            * **Suggested Stop-Loss:** ₹{stop_loss:.2f} (`-{sl_points}` pts)
            * **Target 1 (1:1.5 RR):** ₹{target_1:.2f}
            * **Target 2 (1:2.5 RR):** ₹{target_2:.2f}
            """)
        else:
            st.caption("Jab breakout signal aayega, tab dynamic Stop-Loss aur Targets yahan calculate honge.")

    # --- TELEGRAM DIRECT TRIGGER ---
    st.markdown("---")
    st.subheader("📲 Telegram Alerts")
    st.caption("Connected to bot: @Monty_market_bot")
    
    if st.button("🚀 Send Trade Recommendation to Telegram"):
        msg = (
            f"🚨 *PRO TRADE & STRIKE ALERT*\n\n"
            f"📌 *Asset:* `{clean_ticker}`\n"
            f"⏱ *Timeframe:* `{timeframe}`\n"
            f"💰 *Current Spot:* ₹{c_price:.2f} ({pct_change:.2f}%)\n"
            f"📊 *20 EMA:* ₹{e20:.2f} | *RSI:* {rsi:.1f}\n"
            f"🔥 *Volume:* {vol_ratio:.1f}x Avg\n"
        )
        if pcr_val is not None:
            msg += f"🎯 *PCR:* {pcr_val}\n"
        if latest_vix is not None:
            msg += f"⚡ *India VIX:* {latest_vix:.2f}\n"

        if action in ["BUY_CALL", "BUY_PUT"]:
            msg += (
                f"\n🎯 *ACTION:* `{'BUY CALL (CE)' if action == 'BUY_CALL' else 'BUY PUT (PE)'}`\n"
                f"🏷 *Suggested Strike:* `{suggested_strike}`\n"
                f"🛑 *Stop-Loss (Spot):* ₹{stop_loss:.2f}\n"
                f"🏁 *Target 1:* ₹{target_1:.2f}\n"
                f"🏁 *Target 2:* ₹{target_2:.2f}\n"
            )
        else:
            msg += f"\n📢 *SETUP VERDICT:* `WAIT / SIDEWAYS (ATM: {int(atm_strike)})`"

        sent = send_telegram_alert(BOT_TOKEN, CHAT_ID, msg)
        if sent:
            st.success("✅ Trade Recommendation Telegram (@Monty_market_bot) par bhej di gayi hai!")
        else:
            st.error("❌ Message bhejne me error aaya.")

    # Charts
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.6, 0.2, 0.2])
    fig.add_trace(go.Candlestick(
        x=data.index,
        open=data['Open'].values.flatten() if hasattr(data['Open'], 'values') else data['Open'],
        high=data['High'].values.flatten() if hasattr(data['High'], 'values') else data['High'],
        low=data['Low'].values.flatten() if hasattr(data['Low'], 'values') else data['Low'],
        close=data['Close'].values.flatten() if hasattr(data['Close'], 'values') else data['Close'],
        name="Price"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_20'].values.flatten() if hasattr(data['EMA_20'], 'values') else data['EMA_20'], line=dict(color='orange', width=1.5), name="20 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['EMA_50'].values.flatten() if hasattr(data['EMA_50'], 'values') else data['EMA_50'], line=dict(color='cyan', width=1.5), name="50 EMA"), row=1, col=1)

    colors = ['green' if (c >= o) else 'red' for o, c in zip(data['Open'].values.flatten(), data['Close'].values.flatten())]
    fig.add_trace(go.Bar(x=data.index, y=data['Volume'].values.flatten() if hasattr(data['Volume'], 'values') else data['Volume'], marker_color=colors, name="Volume"), row=2, col=1)
    fig.add_trace(go.Scatter(x=data.index, y=data['Vol_SMA_20'].values.flatten() if hasattr(data['Vol_SMA_20'], 'values') else data['Vol_SMA_20'], line=dict(color='yellow', width=1), name="20 Avg Vol"), row=2, col=1)

    fig.add_trace(go.Scatter(x=data.index, y=data['RSI'].values.flatten() if hasattr(data['RSI'], 'values') else data['RSI'], line=dict(color='magenta', width=1.5), name="RSI (14)"), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    fig.update_layout(height=750, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

else:
    st.error("Is timeframe ke liye data load nahi ho paya. Kripya chhota Period chunein.")