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

st.set_page_config(page_title="Pro Algo Auto-Execution Engine", layout="wide")

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

# --- SIDEBAR ---
st.sidebar.header("⚙️ Configuration")
asset_choice = st.sidebar.selectbox(
    "Asset",
    ["^NSEI (NIFTY 50)", "^NSEBANK (BANK NIFTY)", "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS"],
    index=0
)
clean_ticker = asset_choice.split(" ")[0]
lot_multiplier = 25 if "NSEBANK" in clean_ticker else (75 if "NSEI" in clean_ticker else 1)

timeframe = st.sidebar.selectbox("Timeframe", ["5m", "15m", "1h", "1d"], index=0)
period = "5d" if timeframe in ["5m", "15m"] else "1mo"

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Auto-Execution Settings")
auto_trade_enabled = st.sidebar.toggle("⚡ Enable 100% Auto-Trade (No Click)", value=True)
trade_mode = st.sidebar.radio("Execution Target", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
lots = st.sidebar.number_input("Lots", min_value=1, max_value=5, value=1)
max_loss_limit = st.sidebar.number_input("Max Loss Limit (₹)", min_value=500, max_value=10000, value=2000, step=250)

auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 5, 60, 10, 5)

if st.sidebar.button("🗑 Clear Session History"):
    st.session_state.paper_trades = []
    st.rerun()

smart_api_client, user_name = get_angel_session()

st.title("🎯 Pro Algorithmic Auto-Execution & Trailing P&L")

if smart_api_client:
    st.success(f"🔗 **Broker Connected:** {user_name} (`{CLIENT_CODE}`) | Auto-Trade: **{'ACTIVE 🟢' if auto_trade_enabled else 'PAUSED 🔴'}**")
else:
    st.warning("⚠️ Broker Syncing...")

# Fetch Live Market Data
data = yf.download(clean_ticker, period=period, interval=timeframe)

if not data.empty and len(data) > 20:
    # Indicator Calculations
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()

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

    # Fixed ₹2,000 Stop-loss in Spot Points
    # Loss = Spot_Points * Delta(0.55) * Total_Qty
    total_qty = lots * lot_multiplier
    fixed_sl_pts = round(max_loss_limit / (0.55 * total_qty), 1)

    # Strategy Filters
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

    # Check Active Positions
    has_open_position = any(t.get("Status") == "OPEN" for t in st.session_state.paper_trades)

    # --- 100% AUTO-EXECUTION ENGINE (NO CLICK REQUIRED) ---
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
            f"⚡ *AUTO-ORDER EXECUTED (NO CLICK)*\n\n📌 *Asset:* `{clean_ticker}`\n🎯 *Action:* `{action}`\n🏷 *Strike:* `{suggested_strike}`\n💰 *Entry:* ₹{curr_c:.2f}\n🛑 *Max SL:* ₹{initial_sl:.2f} (Max Loss: ₹{max_loss_limit})\n📈 *Profit Strategy:* Unlimited Trailing"
        )

    # Top Metrics Bar
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot Price", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
    c2.metric("20 EMA", f"₹{e20:.2f}", f"Diff: {curr_c - e20:.2f}")
    c3.metric("50 EMA", f"₹{e50:.2f}", "Trend Line")
    c4.metric("RSI (14)", f"{rsi:.1f}", "Momentum")

    # Live Position & Trailing P&L Tracker
    st.write("### 📊 Live Positions & Trailing P&L (Unlimited Profit Tracker)")
    if len(st.session_state.paper_trades) > 0:
        pnl_records = []
        total_pnl = 0.0

        for t in st.session_state.paper_trades:
            if t["Status"] == "OPEN":
                entry = t["Entry Spot"]
                qty = t["Lot Qty"]

                if t["Type"] == "BUY_CALL":
                    pts_diff = curr_c - entry
                    # Update Peak and Trailing SL
                    if curr_c > t["Peak Price"]:
                        t["Peak Price"] = curr_c
                        # Trail SL: जैसे ही 30 pts प्रॉफिट मिले, SL को ऊपर खिसकाएँ
                        gained_pts = curr_c - entry
                        if gained_pts > 30:
                            new_trail = curr_c - fixed_sl_pts
                            if new_trail > t["Trailing SL"]:
                                t["Trailing SL"] = new_trail

                    # Check SL Trigger
                    if curr_c <= t["Trailing SL"]:
                        t["Status"] = "STOP-LOSS / TRAIL EXIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛑 *POSITION AUTO-CLOSED (SL HIT)*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}")

                else: # BUY_PUT
                    pts_diff = entry - curr_c
                    if curr_c < t["Peak Price"]:
                        t["Peak Price"] = curr_c
                        gained_pts = entry - curr_c
                        if gained_pts > 30:
                            new_trail = curr_c + fixed_sl_pts
                            if new_trail < t["Trailing SL"]:
                                t["Trailing SL"] = new_trail

                    if curr_c >= t["Trailing SL"]:
                        t["Status"] = "STOP-LOSS / TRAIL EXIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛑 *POSITION AUTO-CLOSED (SL HIT)*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}")

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
                "Spot Points": f"{pts_diff:+.2f}",
                "Live P&L (₹)": f"₹{trade_pnl:+.2f}",
                "Status": t["Status"]
            })

        df_pnl = pd.DataFrame(pnl_records)
        st.dataframe(df_pnl, use_container_width=True)

        cp1, cp2 = st.columns(2)
        cp1.metric("Active Session P&L", f"₹{total_pnl:+.2f}", delta=f"{total_pnl:.2f}")
        cp2.info(f"🛡️ **Risk Guard:** Max Loss per trade capped at **₹{max_loss_limit}** | Profits Trail Automatically.")
    else:
        st.info("⚡ इंजन लाइव सिग्नल मॉनिटर कर रहा है। मोमेंटम कन्फ़र्म होते ही ऑटोमैटिक ऑर्डर लग जाएगा।")

    # Auto Refresh
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
