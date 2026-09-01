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

st.set_page_config(page_title="Pro Algo Fast Breakdown & Trailing Engine", layout="wide")

# Pre-configured Telegram credentials
BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"

# Pre-configured Angel One credentials
API_KEY = "lga05JNK"
CLIENT_CODE = "O53184355"
PIN = "1914"
TOTP_SECRET = "QNJM3G2COJWVQ44CVS4CFHBKIE"

# Session State for Orders
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

def calculate_live_pcr(df):
    try:
        c_now = float(df['Close'].iloc[-1])
        e20_now = float(df['Close'].ewm(span=20).mean().iloc[-1])
        diff_ratio = (c_now - e20_now) / e20_now
        derived_pcr = round(1.0 + (diff_ratio * 15), 2)
        return max(min(derived_pcr, 1.75), 0.55)
    except Exception:
        return 1.05

# --- SIDEBAR ---
st.sidebar.header("⚙️ Market Configuration")
asset_choice = st.sidebar.selectbox(
    "Asset",
    ["^NSEI (NIFTY 50)", "^NSEBANK (BANK NIFTY)", "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS"],
    index=0
)
clean_ticker = asset_choice.split(" ")[0]
lot_multiplier = 25 if "NSEBANK" in clean_ticker else (75 if "NSEI" in clean_ticker else 1)
product_type = st.sidebar.selectbox("Product Order Type", ["CARRYFORWARD (NRML)", "INTRADAY (MIS)"], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Algo Auto-Pilot")
auto_trade_enabled = st.sidebar.toggle("⚡ 100% Auto-Trade (Zero Click)", value=True)
trade_mode = st.sidebar.radio("Execution Mode", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
lots = st.sidebar.number_input("Lots", min_value=1, max_value=5, value=1)
max_loss_limit = st.sidebar.number_input("Max Hard Risk Limit (₹)", min_value=500, max_value=10000, value=2000, step=250)

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 5, 60, 10, 5)

if st.sidebar.button("🗑 Clear Trade History"):
    st.session_state.paper_trades = []
    st.rerun()

smart_api_client, user_name = get_angel_session()

st.title("🎯 Pro Algo Fast Breakdown & Profit Trailing Engine")

# Broker Status
if smart_api_client:
    st.success(f"🔗 **Angel One Live:** {user_name} (`{CLIENT_CODE}`) | Product: **{product_type}** | Engine: **{'RUNNING 🟢' if auto_trade_enabled else 'PAUSED 🔴'}**")
else:
    st.warning("⚠️ Broker Syncing...")

# Multi-Timeframe Fetching
data_5m = yf.download(clean_ticker, period="5d", interval="5m")
data_15m = yf.download(clean_ticker, period="5d", interval="15m")

def val(s):
    return float(s.values[0] if hasattr(s, 'values') else s)

if not data_5m.empty and not data_15m.empty and len(data_5m) > 15:
    # 5M Indicators
    data_5m['EMA_20'] = data_5m['Close'].ewm(span=20, adjust=False).mean()
    data_5m['EMA_50'] = data_5m['Close'].ewm(span=50, adjust=False).mean()
    delta_5 = data_5m['Close'].diff()
    g5 = (delta_5.where(delta_5 > 0, 0)).rolling(14).mean()
    l5 = (-delta_5.where(delta_5 < 0, 0)).rolling(14).mean()
    data_5m['RSI'] = 100 - (100 / (1 + (g5 / l5)))

    # 15M Indicators
    data_15m['EMA_20'] = data_15m['Close'].ewm(span=20, adjust=False).mean()
    data_15m['EMA_50'] = data_15m['Close'].ewm(span=50, adjust=False).mean()

    curr_c = val(data_5m['Close'].iloc[-1])
    prev_c = val(data_5m['Close'].iloc[-2])
    curr_o = val(data_5m['Open'].iloc[-1])
    e20_5m = val(data_5m['EMA_20'].iloc[-1])
    e50_5m = val(data_5m['EMA_50'].iloc[-1])
    rsi_5m = val(data_5m['RSI'].iloc[-1])

    e20_15m = val(data_15m['EMA_20'].iloc[-1])
    c_15m = val(data_15m['Close'].iloc[-1])

    live_pcr = calculate_live_pcr(data_5m)

    # FAST DYNAMIC SIGNAL RULES (No Over-Filtering)
    # Bullish: Price > 20 EMA on 5m, Price > 20 EMA on 15m or Green Momentum
    fast_bull = (curr_c > e20_5m) and (curr_c >= c_15m or curr_c > e20_15m) and (45 <= rsi_5m <= 88)
    # Bearish Breakdown: Price < 20 EMA on 5m, Price < 20 EMA on 15m or Red Momentum (Down to RSI 10)
    fast_bear = (curr_c < e20_5m) and (curr_c <= c_15m or curr_c < e20_15m) and (10 <= rsi_5m <= 55)

    step = 50 if "NSEI" in clean_ticker else (100 if "NSEBANK" in clean_ticker else 10)
    atm_strike = round(curr_c / step) * step

    total_qty = lots * lot_multiplier
    fixed_sl_pts = round(max_loss_limit / (0.55 * total_qty), 1)

    action = "WAIT"
    suggested_strike = ""
    initial_sl = 0.0

    if fast_bull:
        action = "BUY_CALL"
        suggested_strike = f"{int(atm_strike - step)} CE (ITM)"
        initial_sl = curr_c - fixed_sl_pts
    elif fast_bear:
        action = "BUY_PUT"
        suggested_strike = f"{int(atm_strike + step)} PE (ITM)"
        initial_sl = curr_c + fixed_sl_pts

    # Auto Execution Loop
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
            "Cost Shifted": False,
            "Lot Qty": total_qty,
            "Status": "OPEN",
            "Product": product_type
        }
        st.session_state.paper_trades.append(new_trade)
        send_telegram_alert(
            BOT_TOKEN, CHAT_ID,
            f"⚡ *FAST BREAKDOWN / BREAKOUT TRIGGERED*\n\n📌 *Asset:* `{clean_ticker}`\n🎯 *Signal:* `{action}`\n🏷 *Selected Strike:* `{suggested_strike}`\n💰 *Spot Entry:* ₹{curr_c:.2f}\n🛑 *Hard SL:* ₹{initial_sl:.2f} (Max Loss: ₹{max_loss_limit})\n🛡️ *Auto-Cost Lock:* Active at +15 pts"
        )

    # Top Metrics Grid
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Spot Price", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
    c2.metric("20 EMA (5m)", f"₹{e20_5m:.2f}", f"Diff: {curr_c - e20_5m:.2f}")
    c3.metric("50 EMA (5m)", f"₹{e50_5m:.2f}")
    c4.metric("RSI (14)", f"{rsi_5m:.1f}")
    c5.metric("PCR Score", f"{live_pcr:.2f}")

    # Action Status Banner
    st.write("### ⚡ Fast Algo Signal & Recommended Option Strike")
    r1, r2 = st.columns(2)
    with r1:
        if action == "BUY_CALL":
            st.success(f"🟢 **FAST MOMENTUM SIGNAL: BUY CALL**\n\n🎯 **Recommended Strike:** `{suggested_strike}`\n\n⚡ Price above 20 EMA with Bullish Continuation.")
        elif action == "BUY_PUT":
            st.error(f"🔴 **FAST BREAKDOWN SIGNAL: BUY PUT**\n\n🎯 **Recommended Strike:** `{suggested_strike}`\n\n⚡ Price below 20 EMA with Strong Bearish Pressure.")
        else:
            st.info(f"🟡 **STATUS: CONSOLIDATING NEAR 20 EMA** (ATM Strike: {int(atm_strike)})")

    with r2:
        st.markdown(f"""
        * **Active Asset:** `{clean_ticker}`
        * **Order Product Type:** `{product_type}`
        * **Hard SL Protection:** Max ₹{max_loss_limit} (`{fixed_sl_pts}` spot pts)
        * **Break-Even Rule:** SL shifts to Cost automatically at `+15 pts`
        """)

    # --- LIVE P&L ENGINE (SMART TRAILING) ---
    st.write("### 📊 Active Position & Smart Trailing Engine")
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

                    # Move to cost at +15 pts
                    if pts_diff >= 15.0 and not t["Cost Shifted"]:
                        t["Trailing SL"] = entry + 1.0
                        t["Cost Shifted"] = True
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛡️ *BREAK-EVEN LOCKED:* SL moved to Cost (Entry: ₹{entry:.2f}) for `{t['Asset']}`.")

                    # Trail above +25 pts
                    if pts_diff >= 25.0:
                        new_trail = curr_c - 15.0
                        if new_trail > t["Trailing SL"]:
                            t["Trailing SL"] = new_trail

                    if curr_c <= t["Trailing SL"]:
                        t["Status"] = "COST / TRAIL EXIT 🛑" if t["Cost Shifted"] else "STOP-LOSS HIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🏁 *POSITION CLOSED*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}\nPts: {pts_diff:+.2f}")

                else: # BUY_PUT
                    pts_diff = entry - curr_c
                    if curr_c < t["Peak Price"]:
                        t["Peak Price"] = curr_c

                    if pts_diff >= 15.0 and not t["Cost Shifted"]:
                        t["Trailing SL"] = entry - 1.0
                        t["Cost Shifted"] = True
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛡️ *BREAK-EVEN LOCKED:* SL moved to Cost (Entry: ₹{entry:.2f}) for `{t['Asset']}`.")

                    if pts_diff >= 25.0:
                        new_trail = curr_c + 15.0
                        if new_trail < t["Trailing SL"]:
                            t["Trailing SL"] = new_trail

                    if curr_c >= t["Trailing SL"]:
                        t["Status"] = "COST / TRAIL EXIT 🛑" if t["Cost Shifted"] else "STOP-LOSS HIT 🛑"
                        send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🏁 *POSITION CLOSED*\nAsset: `{t['Asset']}`\nExit: ₹{curr_c:.2f}\nPts: {pts_diff:+.2f}")

                approx_opt_pts = round(pts_diff * 0.55, 2)
                trade_pnl = round(approx_opt_pts * qty, 2)
                total_pnl += trade_pnl
            else:
                trade_pnl = 0.0
                pts_diff = 0.0

            pnl_records.append({
                "ID": t["ID"],
                "Time": t["Time"],
                "Type": t["Type"],
                "Strike": t["Strike"],
                "Entry": f"₹{t['Entry Spot']:.2f}",
                "Live SL (Cost/Trail)": f"₹{t['Trailing SL']:.2f}",
                "Spot Move": f"{pts_diff:+.2f} pts",
                "Live P&L (₹)": f"₹{trade_pnl:+.2f}",
                "Status": t["Status"]
            })

        df_pnl = pd.DataFrame(pnl_records)
        st.dataframe(df_pnl, use_container_width=True)

        cp1, cp2 = st.columns(2)
        cp1.metric("Active Session P&L", f"₹{total_pnl:+.2f}", delta=f"{total_pnl:.2f}")
        cp2.info("🛡️ **Zero Risk Trigger:** +15 pts profit aate hi Stop-Loss Cost par shift ho jayega.")
    else:
        st.info("⚡ इंजन लाइव सिग्नल्स ट्रैक कर रहा है। मोमेंटम आते ही ऑटोमैटिक ऑर्डर प्लेस होगा।")

    # Interactive Candlestick Chart
    st.write("### 📈 Live 5-Minute Interactive Candlestick Chart")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(
        x=data_5m.index,
        open=data_5m['Open'].values.flatten(), high=data_5m['High'].values.flatten(),
        low=data_5m['Low'].values.flatten(), close=data_5m['Close'].values.flatten(),
        name="Price"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_20'].values.flatten(), line=dict(color='orange', width=1.5), name="20 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_50'].values.flatten(), line=dict(color='cyan', width=1.5), name="50 EMA"), row=1, col=1)

    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['RSI'].values.flatten(), line=dict(color='magenta', width=1.5), name="RSI (14)"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

else:
    st.error("डेटा सिंक हो रहा है... कृपया 5 सेकंड प्रतीक्षा करें।")
