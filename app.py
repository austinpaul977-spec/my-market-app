import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import requests
import time
import pyotp
from SmartApi import SmartConnect

st.set_page_config(page_title="Pro Algo Auto-Execution & Analytics Engine", layout="wide")

# Pre-configured Telegram credentials
BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"

# Pre-configured Angel One credentials
API_KEY = "lga05JNK"
CLIENT_CODE = "O53184355"
PIN = "1914"
TOTP_SECRET = "QNJM3G2COJWVQ44CVS4CFHBKIE"

# Initialize Session State
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []

def send_telegram_alert(token, chat_id, message_text):
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message_text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

@st.cache_resource(ttl=3600)
def get_angel_session():
    try:
        totp = pyotp.TOTP(TOTP_SECRET).now()
        smart_api = SmartConnect(api_key=API_KEY)
        data = smart_api.generateSession(CLIENT_CODE, PIN, totp)
        if data.get('status'):
            return smart_api, data['data'].get('name', 'OSTEN')
        return None, None
    except Exception:
        return None, None

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

# --- SIDEBAR ---
st.sidebar.header("⚙️ Configuration")
asset_choice = st.sidebar.selectbox(
    "Asset",
    ["^NSEI (NIFTY 50)", "^NSEBANK (BANK NIFTY)", "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS"],
    index=0
)
clean_ticker = asset_choice.split(" ")[0]
is_index = "NSEI" in clean_ticker or "NSEBANK" in clean_ticker
lot_multiplier = 25 if "NSEBANK" in clean_ticker else (75 if "NSEI" in clean_ticker else 1)

timeframe = st.sidebar.selectbox("Timeframe", ["5m", "15m", "1h", "1d"], index=0)
period = "5d" if timeframe in ["5m", "15m"] else "1mo"

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Auto-Execution Settings")
auto_trade_enabled = st.sidebar.toggle("⚡ Enable 100% Auto-Trade (No Click)", value=True)
trade_mode = st.sidebar.radio("Execution Target", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
lots = st.sidebar.number_input("Lots", min_value=1, max_value=5, value=1)
max_loss_limit = st.sidebar.number_input("Max Loss Limit (₹)", min_value=500, max_value=10000, value=2000, step=250)

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 5, 60, 10, 5)

if st.sidebar.button("🗑 Clear Session History"):
    st.session_state.paper_trades = []
    st.rerun()

smart_api_client, user_name = get_angel_session()

st.title("🎯 Pro Algo Auto-Execution & Full Analytics Engine")

# Broker Status
if smart_api_client:
    st.success(f"🔗 **Broker Connected:** {user_name} (`{CLIENT_CODE}`) | Mode: **{trade_mode}** | Auto-Trade: **{'ACTIVE 🟢' if auto_trade_enabled else 'PAUSED 🔴'}**")
else:
    st.warning("⚠️ Broker Syncing...")

# Data Fetching
data = yf.download(clean_ticker, period=period, interval=timeframe)
vix_data = yf.download("^INDIAVIX", period="5d", interval="1d")

latest_vix = None
vix_change = 0.0
if not vix_data.empty:
    v_close = vix_data['Close'].values.flatten() if hasattr(vix_data['Close'], 'values') else vix_data['Close']
    latest_vix = float(v_close[-1])
    if len(v_close) > 1:
        prev_vix = float(v_close[-2])
        vix_change = ((latest_vix - prev_vix) / prev_vix) * 100

pcr_val, pe_oi, ce_oi = None, None, None
if "NSEI" in clean_ticker:
    pcr_val, pe_oi, ce_oi = fetch_pcr("NIFTY")
elif "NSEBANK" in clean_ticker:
    pcr_val, pe_oi, ce_oi = fetch_pcr("BANKNIFTY")

if not data.empty and len(data) > 20:
    # Calculations
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Vol_SMA_20'] = data['Volume'].rolling(window=20).mean()

    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    hl = data['High'] - data['Low']
    hc = np.abs(data['High'] - data['Close'].shift())
    lc = np.abs(data['Low'] - data['Close'].shift())
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    data['ATR'] = tr.rolling(14).mean()

    def val(s):
        return float(s.values[0] if hasattr(s, 'values') else s)

    curr_c = val(data['Close'].iloc[-1])
    prev_c = val(data['Close'].iloc[-2])
    curr_o = val(data['Open'].iloc[-1])
    e20 = val(data['EMA_20'].iloc[-1])
    e50 = val(data['EMA_50'].iloc[-1])
    rsi = val(data['RSI'].iloc[-1])
    atr = val(data['ATR'].iloc[-1]) if not np.isnan(val(data['ATR'].iloc[-1])) else (curr_c * 0.004)

    step = 50 if "NSEI" in clean_ticker else (100 if "NSEBANK" in clean_ticker else 10)
    atm_strike = round(curr_c / step) * step

    total_qty = lots * lot_multiplier
    fixed_sl_pts = round(max_loss_limit / (0.55 * total_qty), 1)

    # Strategy Filters (No Fake Moves)
    confirmed_bull = (curr_c > e20) and (e20 > e50) and (curr_c > curr_o) and (55 <= rsi <= 72)
    confirmed_bear = (curr_c < e20) and (e20 < e50) and (curr_c < curr_o) and (28 <= rsi <= 45)

    action = "WAIT"
    suggested_strike = ""
    initial_sl = 0.0

    if confirmed_bull:
        action = "BUY_CALL"
        suggested_strike = f"{int(atm_strike - step)} CE (ITM)"
        initial_sl = curr_c - fixed_sl_pts
    elif confirmed_bear:
        action = "BUY_PUT"
        suggested_strike = f"{int(atm_strike + step)} PE (ITM)"
        initial_sl = curr_c + fixed_sl_pts

    # Auto-Execution Trigger
    has_open_position = any(t.get("Status") == "OPEN" for t in st.session_state.paper_trades)
    if auto_trade_enabled and not has_open_position and action in ["BUY_CALL", "BUY_PUT"]:
        new_trade = {
            "ID": len(st.session_state.paper_trades) + 1,
            "Time": pd.Timestamp.now().strftime("%H:%M:%S"),
            "Asset": clean_ticker,
            "Type": action,
            "Strike": suggested_strike,
            "Entry Spot": curr_c,
            "Initial SL": initial_sl,
            "Trailing SL": initial_sl,
            "Peak Price": curr_c,
            "Lot Qty": total_qty,
            "Status": "OPEN",
            "Mode": trade_mode
        }
        st.session_state.paper_trades.append(new_trade)
        send_telegram_alert(
            BOT_TOKEN, CHAT_ID,
            f"⚡ *AUTO-ORDER EXECUTED (NO CLICK)*\n\n📌 *Asset:* `{clean_ticker}`\n🎯 *Action:* `{action}`\n🏷 *Strike:* `{suggested_strike}`\n💰 *Entry:* ₹{curr_c:.2f}\n🛑 *Max SL:* ₹{initial_sl:.2f} (Risk Cap: ₹{max_loss_limit})\n📈 *Strategy:* Trailing Profit"
        )

    # Top Metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Spot Price", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
    c2.metric("20 EMA", f"₹{e20:.2f}", f"Diff: {curr_c - e20:.2f}")
    c3.metric("50 EMA", f"₹{e50:.2f}", "Trend Line")
    c4.metric("RSI (14)", f"{rsi:.1f}", "Momentum")
    if latest_vix is not None:
        c5.metric("India VIX", f"{latest_vix:.2f}", f"{vix_change:.2f}%")
    else:
        c5.metric("India VIX", "N/A")

    # Options PCR Status
    st.write("### 📌 Options PCR & Market Health")
    cpcr1, cpcr2 = st.columns(2)
    with cpcr1:
        if pcr_val is not None:
            if pcr_val >= 1.2:
                st.success(f"📈 **PCR: {pcr_val} (Bullish Bias)** — Put Writing Active.")
            elif pcr_val <= 0.75:
                st.error(f"📉 **PCR: {pcr_val} (Bearish Bias)** — Call Writing Active.")
            else:
                st.info(f"⚖️ **PCR: {pcr_val} (Neutral)** — Rangebound Movement.")
        else:
            st.info("ℹ️ PCR Index (NIFTY/BANKNIFTY) par live evaluate hota hai.")
    with cpcr2:
        if action == "BUY_CALL":
            st.success(f"🟢 **RECOMMENDED STRIKE:** `{suggested_strike}`")
        elif action == "BUY_PUT":
            st.error(f"🔴 **RECOMMENDED STRIKE:** `{suggested_strike}`")
        else:
            st.info(f"🟡 **STATUS: WAITING FOR HIGH-CONFIRMATION SETUP** (ATM: {int(atm_strike)})")

    # Live P&L Table
    st.write("### 📊 Live Positions & Trailing P&L Tracker")
    if len(st.session_state.paper_trades) > 0:
        pnl_records = []
        total_pnl = 0.0

        for t in st.session_state.paper_trades:
            if t["Status"] == "OPEN":
                entry = t["Entry Spot"]
                qty = t["Lot Qty"]

                if t["Type"] == "BUY_CALL":
                    pts_diff = curr_c - entry
                    if curr_c > t["Peak Price"]:
                        t["Peak Price"] = curr_c
                        if (curr_c - entry) > 30:
                            new_trail = curr_c - fixed_sl_pts
                            if new_trail > t["Trailing SL"]:
                                t["Trailing SL"] = new_trail
                    if curr_c <= t["Trailing SL"]:
                        t["Status"] = "STOP-LOSS / TRAIL EXIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛑 *POSITION AUTO-CLOSED*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}")

                else:
                    pts_diff = entry - curr_c
                    if curr_c < t["Peak Price"]:
                        t["Peak Price"] = curr_c
                        if (entry - curr_c) > 30:
                            new_trail = curr_c + fixed_sl_pts
                            if new_trail < t["Trailing SL"]:
                                t["Trailing SL"] = new_trail
                    if curr_c >= t["Trailing SL"]:
                        t["Status"] = "STOP-LOSS / TRAIL EXIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛑 *POSITION AUTO-CLOSED*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}")

                approx_opt_pts = round(pts_diff * 0.55, 2)
                trade_pnl = round(approx_opt_pts * qty, 2)
                total_pnl += trade_pnl
            else:
                trade_pnl = 0.0
                pts_diff = 0.0
                approx_opt_pts = 0.0

            pnl_records.append({
                "ID": t["ID"],
                "Time": t["Time"],
                "Strike": t["Strike"],
                "Entry": f"₹{t['Entry Spot']:.2f}",
                "Trailing SL": f"₹{t['Trailing SL']:.2f}",
                "Spot Pts": f"{pts_diff:+.2f}",
                "Live P&L (₹)": f"₹{trade_pnl:+.2f}",
                "Status": t["Status"]
            })

        df_pnl = pd.DataFrame(pnl_records)
        st.dataframe(df_pnl, use_container_width=True)

        cp1, cp2 = st.columns(2)
        cp1.metric("Active Session P&L", f"₹{total_pnl:+.2f}", delta=f"{total_pnl:.2f}")
        cp2.info(f"🛡️ **Risk Guard:** ₹{max_loss_limit} Max Risk per trade | Profits Trail Automatically.")
    else:
        st.info("⚡ इंजन लाइव सिग्नल मॉनिटर कर रहा है। मोमेंटम कन्फ़र्म होते ही ऑटोमैटिक ऑर्डर लग जाएगा।")

    # Charts
    st.write("### 📈 Live Interactive Chart")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
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

    fig.add_trace(go.Scatter(x=data.index, y=data['RSI'].values.flatten() if hasattr(data['RSI'], 'values') else data['RSI'], line=dict(color='magenta', width=1.5), name="RSI (14)"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(height=650, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

else:
    st.error("डेटा लोड नहीं हो पाया। कृपया टाइमफ़्रेम या पीरियड बदलें।")
