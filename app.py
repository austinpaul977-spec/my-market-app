import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import os
import pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Multi-Asset Institutional Confluence Engine", layout="wide")

# Pre-configured Telegram credentials
BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"

# Pre-configured Angel One credentials
API_KEY = "lga05JNK"
CLIENT_CODE = "O53184355"
PIN = "1914"
TOTP_SECRET = "QNJM3G2COJWVQ44CVS4CFHBKIE"

CSV_FILE = "trade_history.csv"

def load_trade_history():
    if os.path.exists(CSV_FILE):
        try:
            return pd.read_csv(CSV_FILE)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def save_trade_to_csv(trade_dict):
    df_new = pd.DataFrame([trade_dict])
    if not os.path.exists(CSV_FILE):
        df_new.to_csv(CSV_FILE, index=False)
    else:
        df_new.to_csv(CSV_FILE, mode='a', header=False, index=False)

if "active_trade" not in st.session_state:
    st.session_state.active_trade = None

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

def fetch_angel_candles(smart_api, token, exchange="NSE", interval="FIVE_MINUTE", days=5):
    try:
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        params = {
            "exchange": exchange,
            "symboltoken": str(token),
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date
        }
        res = smart_api.getCandleData(params)
        if res.get('status') and res.get('data'):
            df = pd.DataFrame(res['data'], columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df.set_index('Timestamp', inplace=True)
            return df
    except Exception:
        pass
    return pd.DataFrame()

# --- SIDEBAR CONTROLS (NSE + BSE + MCX) ---
st.sidebar.header("⚙️ Multi-Market Controls")
asset_config = {
    "NIFTY 50": {"token": "99926000", "exchange": "NSE", "step": 50, "multiplier": 75, "tsym": "Nifty 50", "cost_shift": 15.0, "trail_step": 25.0},
    "BANK NIFTY": {"token": "99926009", "exchange": "NSE", "step": 100, "multiplier": 25, "tsym": "Nifty Bank", "cost_shift": 30.0, "trail_step": 50.0},
    "SENSEX": {"token": "99919000", "exchange": "BSE", "step": 100, "multiplier": 20, "tsym": "SENSEX", "cost_shift": 40.0, "trail_step": 70.0},
    "CRUDE OIL": {"token": "253460", "exchange": "MCX", "step": 50, "multiplier": 100, "tsym": "CRUDEOIL", "cost_shift": 12.0, "trail_step": 20.0},
    "RELIANCE": {"token": "2885", "exchange": "NSE", "step": 20, "multiplier": 250, "tsym": "RELIANCE-EQ", "cost_shift": 5.0, "trail_step": 10.0},
    "INFY": {"token": "1594", "exchange": "NSE", "step": 20, "multiplier": 400, "tsym": "INFY-EQ", "cost_shift": 4.0, "trail_step": 8.0},
    "HDFC BANK": {"token": "1333", "exchange": "NSE", "step": 10, "multiplier": 550, "tsym": "HDFCBANK-EQ", "cost_shift": 3.0, "trail_step": 6.0}
}

selected_asset = st.sidebar.selectbox("Asset Chunein", list(asset_config.keys()), index=0)
cfg = asset_config[selected_asset]

product_type = st.sidebar.selectbox("Product Order Type", ["CARRYFORWARD (NRML)", "INTRADAY (MIS)"], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Algo Auto-Pilot")
auto_trade_enabled = st.sidebar.toggle("⚡ 100% Auto-Trade (Zero Click)", value=True)
trade_mode = st.sidebar.radio("Execution Target", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
lots = st.sidebar.number_input("Lots", min_value=1, max_value=5, value=1)
max_loss_limit = st.sidebar.number_input("Hard Stop-Loss Limit (₹)", min_value=500, max_value=10000, value=2000, step=250)

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 3, 30, 5, 1)

if st.sidebar.button("🗑 Clear Session Logs"):
    st.session_state.paper_trades = []
    st.session_state.active_trade = None
    st.rerun()

smart_api_client, user_name = get_angel_session()

st.title("🎯 Multi-Asset Institutional Confluence & Auto-Execution Engine")

if smart_api_client:
    st.success(f"🔗 **Angel One Live Feed:** {user_name} (`{CLIENT_CODE}`) | Asset: **{selected_asset} ({cfg['exchange']})** | Mode: **{trade_mode}** | Strategy: **Hybrid Confluence**")
else:
    st.error("⚠️ Angel One Connection Error. Re-authorizing...")
    st.stop()

# --- CANDLE DATA FETCHING ---
data_5m = fetch_angel_candles(smart_api_client, cfg["token"], exchange=cfg["exchange"], interval="FIVE_MINUTE", days=5)

if not data_5m.empty and len(data_5m) > 25:
    # 1. EMAs (9, 21, 50)
    data_5m['EMA_9'] = data_5m['Close'].ewm(span=9, adjust=False).mean()
    data_5m['EMA_21'] = data_5m['Close'].ewm(span=21, adjust=False).mean()
    data_5m['EMA_50'] = data_5m['Close'].ewm(span=50, adjust=False).mean()

    # 2. Intraday VWAP Calculation
    df_today = data_5m[data_5m.index.date == data_5m.index[-1].date()].copy()
    if not df_today.empty and df_today['Volume'].sum() > 0:
        typical_price = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
        data_5m.loc[df_today.index, 'VWAP'] = (typical_price * df_today['Volume']).cumsum() / df_today['Volume'].cumsum()
    else:
        data_5m['VWAP'] = data_5m['EMA_21']

    # 3. RSI
    delta = data_5m['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    data_5m['RSI'] = 100 - (100 / (1 + rs))

    # 4. ATR
    hl = data_5m['High'] - data_5m['Low']
    hc = np.abs(data_5m['High'] - data_5m['Close'].shift())
    lc = np.abs(data_5m['Low'] - data_5m['Close'].shift())
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    data_5m['ATR'] = tr.rolling(14).mean()

    curr_c = float(data_5m['Close'].iloc[-1])
    prev_c = float(data_5m['Close'].iloc[-2])
    curr_o = float(data_5m['Open'].iloc[-1])
    curr_h = float(data_5m['High'].iloc[-1])
    curr_l = float(data_5m['Low'].iloc[-1])

    e9 = float(data_5m['EMA_9'].iloc[-1])
    e21 = float(data_5m['EMA_21'].iloc[-1])
    e50 = float(data_5m['EMA_50'].iloc[-1])
    vwap_val = float(data_5m['VWAP'].iloc[-1]) if not np.isnan(data_5m['VWAP'].iloc[-1]) else e21
    rsi = float(data_5m['RSI'].iloc[-1])
    atr = float(data_5m['ATR'].iloc[-1]) if not np.isnan(data_5m['ATR'].iloc[-1]) else (curr_c * 0.003)

    # Hybrid Confluence Conditions
    bull_confluence = (
        (curr_c >= vwap_val) and 
        (e9 >= e21) and 
        (curr_c >= e9 or (curr_l <= e21 and curr_c > e21)) and 
        (48 <= rsi <= 85)
    )

    bear_confluence = (
        (curr_c <= vwap_val) and 
        (e9 <= e21) and 
        (curr_c <= e9 or (curr_h >= e21 and curr_c < e21)) and 
        (12 <= rsi <= 52)
    )

    step = cfg["step"]
    atm_strike = round(curr_c / step) * step
    total_qty = lots * cfg["multiplier"]
    fixed_sl_pts = round(max_loss_limit / (0.55 * total_qty), 1)

    action = "WAIT"
    suggested_strike = ""
    initial_sl = 0.0

    if bull_confluence:
        action = "BUY_CALL"
        suggested_strike = f"{int(atm_strike - step)} CE (ITM)"
        initial_sl = curr_c - fixed_sl_pts
    elif bear_confluence:
        action = "BUY_PUT"
        suggested_strike = f"{int(atm_strike + step)} PE (ITM)"
        initial_sl = curr_c + fixed_sl_pts

    # Auto Entry Trigger
    if auto_trade_enabled and st.session_state.active_trade is None and action in ["BUY_CALL", "BUY_PUT"]:
        st.session_state.active_trade = {
            "Entry_Date": datetime.now().strftime("%Y-%m-%d"),
            "Entry_Time": datetime.now().strftime("%H:%M:%S"),
            "Asset": selected_asset,
            "Exchange": cfg["exchange"],
            "Type": action,
            "Strike": suggested_strike,
            "Entry_Spot": curr_c,
            "Initial_SL": initial_sl,
            "Trailing_SL": initial_sl,
            "Peak_Price": curr_c,
            "Cost_Shifted": False,
            "Qty": total_qty,
            "Product": product_type,
            "Mode": trade_mode,
            "Cost_Shift_Pts": cfg["cost_shift"],
            "Trail_Step_Pts": cfg["trail_step"]
        }
        send_telegram_alert(
            BOT_TOKEN, CHAT_ID,
            f"⚡ *{cfg['exchange']} HYBRID CONFLUENCE ORDER*\n\n📌 *Asset:* `{selected_asset}`\n🎯 *Action:* `{action}`\n🏷 *Strike:* `{suggested_strike}`\n💼 *Exchange:* `{cfg['exchange']}`\n💰 *Entry Spot:* ₹{curr_c:.2f}\n🛑 *Hard SL:* ₹{initial_sl:.2f} (Max Risk: ₹{max_loss_limit})\n🛡️ *Strategy:* VWAP + EMA Pullback"
        )

    # Top Metrics Grid
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Live Spot Price", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
    c2.metric("VWAP Floor", f"₹{vwap_val:.2f}", f"Diff: {curr_c - vwap_val:.2f}")
    c3.metric("9 / 21 EMA", f"₹{e9:.1f} / ₹{e21:.1f}")
    c4.metric("RSI (14)", f"{rsi:.1f}")
    c5.metric("Exchange Feed", f"{cfg['exchange']}")

    # Active Position & Smart Trailing Engine
    st.write("### ⚡ Live Hybrid Trade Monitor")
    t = st.session_state.active_trade
    if t is not None:
        entry = t["Entry_Spot"]
        qty = t["Qty"]
        shift_target = t.get("Cost_Shift_Pts", 15.0)
        trail_target = t.get("Trail_Step_Pts", 25.0)
        is_closed = False
        exit_reason = ""

        if t["Type"] == "BUY_CALL":
            pts_diff = curr_c - entry
            if curr_c > t["Peak_Price"]:
                t["Peak_Price"] = curr_c

            if pts_diff >= shift_target and not t["Cost_Shifted"]:
                t["Trailing_SL"] = entry + 1.0
                t["Cost_Shifted"] = True
                send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛡️ *BREAK-EVEN LOCKED:* SL moved to Cost (₹{entry:.2f}) for `{t['Asset']}`.")

            if pts_diff >= trail_target:
                new_trail = curr_c - shift_target
                if new_trail > t["Trailing_SL"]:
                    t["Trailing_SL"] = new_trail

            if curr_c <= t["Trailing_SL"]:
                is_closed = True
                exit_reason = "BREAK-EVEN COST EXIT 🛑" if t["Cost_Shifted"] else "HARD SL HIT 🛑"

        else: # BUY_PUT
            pts_diff = entry - curr_c
            if curr_c < t["Peak_Price"]:
                t["Peak_Price"] = curr_c

            if pts_diff >= shift_target and not t["Cost_Shifted"]:
                t["Trailing_SL"] = entry - 1.0
                t["Cost_Shifted"] = True
                send_telegram_alert(BOT_TOKEN, CHAT_ID, f"🛡️ *BREAK-EVEN LOCKED:* SL moved to Cost (₹{entry:.2f}) for `{t['Asset']}`.")

            if pts_diff >= trail_target:
                new_trail = curr_c + shift_target
                if new_trail < t["Trailing_SL"]:
                    t["Trailing_SL"] = new_trail

            if curr_c >= t["Trailing_SL"]:
                is_closed = True
                exit_reason = "BREAK-EVEN COST EXIT 🛑" if t["Cost_Shifted"] else "HARD SL HIT 🛑"

        approx_opt_pts = round(pts_diff * 0.55, 2)
        trade_pnl = round(approx_opt_pts * qty, 2)

        st.info(f"🟢 **OPEN POSITION:** `{t['Type']}` ({t['Strike']}) | Asset: **{t['Asset']} ({t.get('Exchange', 'NSE')})** | Entry: **₹{entry:.2f}** | Live Spot: **₹{curr_c:.2f}** | Move: **{pts_diff:+.2f} pts** | Trailing SL: **₹{t['Trailing_SL']:.2f}** | P&L: **₹{trade_pnl:+.2f}**")

        if is_closed:
            completed_trade = {
                "Date": t["Entry_Date"],
                "Entry_Time": t["Entry_Time"],
                "Exit_Time": datetime.now().strftime("%H:%M:%S"),
                "Asset": t["Asset"],
                "Exchange": t.get("Exchange", "NSE"),
                "Type": t["Type"],
                "Strike": t["Strike"],
                "Entry_Spot": t["Entry_Spot"],
                "Exit_Spot": curr_c,
                "Spot_Points": round(pts_diff, 2),
                "Opt_Points": approx_opt_pts,
                "Total_PnL_INR": trade_pnl,
                "Exit_Reason": exit_reason,
                "Mode": t["Mode"]
            }
            save_trade_to_csv(completed_trade)
            st.session_state.active_trade = None
            send_telegram_alert(
                BOT_TOKEN, CHAT_ID,
                f"🏁 *TRADE CLOSED & SAVED*\n\n📌 *Asset:* `{t['Asset']}` ({t.get('Exchange', 'NSE')})\n🏷 *Strike:* `{t['Strike']}`\n💰 *P&L:* ₹{trade_pnl:+.2f} ({pts_diff:+.2f} pts)\n🚪 *Reason:* `{exit_reason}`"
            )
            st.rerun()
    else:
        st.caption(f"⚡ हाइब्रिड इंजन {selected_asset} ({cfg['exchange']}) के VWAP, 9/21 EMA और लिक्विडिटी को मॉनिटर कर रहा है।")

    # --- PERMANENT PERFORMANCE JOURNAL (CSV) ---
    st.write("---")
    st.write("### 📚 Permanent Trade Book & Performance History")
    df_history = load_trade_history()

    if not df_history.empty:
        col_j1, col_j2, col_j3 = st.columns(3)
        total_pnl_all = df_history['Total_PnL_INR'].sum()
        total_trades = len(df_history)
        winning_trades = len(df_history[df_history['Total_PnL_INR'] > 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

        col_j1.metric("Cumulative Net P&L", f"₹{total_pnl_all:+.2f}", delta=f"{total_pnl_all:.2f}")
        col_j2.metric("Total Trades", f"{total_trades}")
        col_j3.metric("Win Rate", f"{win_rate:.1f}%", f"{winning_trades} Wins")

        st.dataframe(df_history, use_container_width=True)

        csv_data = df_history.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Complete Trade History (CSV)",
            data=csv_data,
            file_name=f"trade_book_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
    else:
        st.info("ℹ️ पहला ट्रेड क्लोज होते ही पूरा रिकॉर्ड यहाँ परमानेंट दिखने लगेगा।")

    # Interactive Candlestick Chart
    st.write("### 📈 Live Candlestick Chart (VWAP & EMA Multi-Overlay)")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(
        x=data_5m.index,
        open=data_5m['Open'], high=data_5m['High'],
        low=data_5m['Low'], close=data_5m['Close'],
        name="Price"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['VWAP'], line=dict(color='yellow', width=2), name="VWAP"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_9'], line=dict(color='lime', width=1.5), name="9 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_21'], line=dict(color='orange', width=1.5), name="21 EMA"), row=1, col=1)

    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['RSI'], line=dict(color='magenta', width=1.5), name="RSI (14)"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(height=600, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

else:
    st.error(f"Angel One से {selected_asset} का डेटा लोड हो रहा है... कृपया 3 सेकंड प्रतीक्षा करें।")
