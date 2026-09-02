
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
import json
import pyotp
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Institutional Tri-Engine Algo Terminal", layout="wide")

# Pre-configured Telegram credentials
BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"

# Pre-configured Angel One credentials
API_KEY = "lga05JNK"
CLIENT_CODE = "O53184355"
PIN = "1914"
TOTP_SECRET = "QNJM3G2COJWVQ44CVS4CFHBKIE"

# File Paths for Persistent Storage
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "trade_history.csv")
ACTIVE_TRADE_FILE = os.path.join(BASE_DIR, "active_trade.json")
TV_SIGNAL_FILE = os.path.join(BASE_DIR, "tv_signals.json")

# --- TRADINGVIEW WEBHOOK RECEIVER (BACKGROUND THREAD) ---
class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            payload = json.loads(post_data)
            with open(TV_SIGNAL_FILE, "w") as f:
                json.dump({"signal": payload.get("signal", ""), "asset": payload.get("asset", ""), "time": datetime.now().strftime("%H:%M:%S")}, f)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "received"}).encode('utf-8'))
        except Exception:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        return

def start_webhook_server():
    try:
        server = HTTPServer(('0.0.0.0', 5001), WebhookHandler)
        server.serve_forever()
    except Exception:
        pass

if "webhook_started" not in st.session_state:
    t_wh = threading.Thread(target=start_webhook_server, daemon=True)
    t_wh.start()
    st.session_state.webhook_started = True

def get_latest_tv_signal():
    if os.path.exists(TV_SIGNAL_FILE):
        try:
            with open(TV_SIGNAL_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None

# --- NSE OPTION CHAIN SCRAPER ---
def fetch_nse_option_chain(symbol="NIFTY"):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br"
    }
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        response = session.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            records = data.get('records', {}).get('data', [])
            parsed = []
            for item in records:
                strike = item.get('strikePrice')
                ce = item.get('CE', {})
                pe = item.get('PE', {})
                if ce or pe:
                    parsed.append({
                        "Strike": strike,
                        "Call_OI": ce.get('openInterest', 0),
                        "Call_Chng_OI": ce.get('changeinOpenInterest', 0),
                        "Put_OI": pe.get('openInterest', 0),
                        "Put_Chng_OI": pe.get('changeinOpenInterest', 0)
                    })
            return pd.DataFrame(parsed)
    except Exception:
        pass
    return pd.DataFrame()

# --- STATE MANAGEMENT ---
def get_persisted_active_trade():
    if os.path.exists(ACTIVE_TRADE_FILE):
        try:
            with open(ACTIVE_TRADE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def set_persisted_active_trade(trade_dict):
    if trade_dict is None:
        if os.path.exists(ACTIVE_TRADE_FILE):
            os.remove(ACTIVE_TRADE_FILE)
    else:
        with open(ACTIVE_TRADE_FILE, "w") as f:
            json.dump(trade_dict, f, indent=4)

def load_trade_history():
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            if not df.empty and 'Total_PnL_INR' in df.columns:
                df['Total_PnL_INR'] = pd.to_numeric(df['Total_PnL_INR'], errors='coerce').fillna(0.0)
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def save_trade_to_csv(trade_dict):
    df_new = pd.DataFrame([trade_dict])
    if not os.path.exists(CSV_FILE):
        df_new.to_csv(CSV_FILE, index=False)
    else:
        df_new.to_csv(CSV_FILE, mode='a', header=False, index=False)

def clear_all_records():
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    if os.path.exists(ACTIVE_TRADE_FILE):
        os.remove(ACTIVE_TRADE_FILE)
    if os.path.exists(TV_SIGNAL_FILE):
        os.remove(TV_SIGNAL_FILE)

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

def get_market_data(smart_api, cfg, interval="5m", period="5d"):
    try:
        angel_int_map = {"5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE", "1h": "ONE_HOUR"}
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
        params = {
            "exchange": cfg["exchange"],
            "symboltoken": str(cfg["token"]),
            "interval": angel_int_map.get(interval, "FIVE_MINUTE"),
            "fromdate": from_date,
            "todate": to_date
        }
        res = smart_api.getCandleData(params) if smart_api else {}
        if res.get('status') and res.get('data'):
            df = pd.DataFrame(res['data'], columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df.set_index('Timestamp', inplace=True)
            return df
    except Exception:
        pass

    try:
        df_yf = yf.download(cfg["yf_symbol"], period=period, interval=interval, progress=False)
        if not df_yf.empty:
            if isinstance(df_yf.columns, pd.MultiIndex):
                df_yf.columns = df_yf.columns.get_level_values(0)
            df_yf = df_yf[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            for col in df_yf.columns:
                df_yf[col] = pd.to_numeric(df_yf[col], errors='coerce')
            return df_yf.dropna()
    except Exception:
        pass
    return pd.DataFrame()

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Market Controls")
asset_config = {
    "NIFTY 50": {"yf_symbol": "^NSEI", "token": "99926000", "exchange": "NSE", "step": 50, "multiplier": 75, "cost_shift": 15.0, "trail_step": 25.0, "nse_sym": "NIFTY"},
    "BANK NIFTY": {"yf_symbol": "^NSEBANK", "token": "99926009", "exchange": "NSE", "step": 100, "multiplier": 25, "cost_shift": 30.0, "trail_step": 50.0, "nse_sym": "BANKNIFTY"},
    "SENSEX": {"yf_symbol": "^BSESN", "token": "99919000", "exchange": "BSE", "step": 100, "multiplier": 20, "cost_shift": 40.0, "trail_step": 70.0, "nse_sym": None},
    "CRUDE OIL": {"yf_symbol": "CL=F", "token": "253460", "exchange": "MCX", "step": 50, "multiplier": 100, "cost_shift": 12.0, "trail_step": 20.0, "nse_sym": None}
}

selected_asset = st.sidebar.selectbox("Asset", list(asset_config.keys()), index=0)
cfg = asset_config[selected_asset]
product_type = st.sidebar.selectbox("Product Order Type", ["CARRYFORWARD (NRML)", "INTRADAY (MIS)"], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Parameters")
account_capital = st.sidebar.number_input("Capital (₹)", min_value=10000.0, max_value=5000000.0, value=100000.0, step=10000.0)
risk_pct = st.sidebar.slider("Risk Per Trade (%)", 0.5, 5.0, 1.5, 0.25)
daily_loss_limit = st.sidebar.number_input("Daily Circuit Limit (₹)", min_value=1000.0, max_value=50000.0, value=3000.0, step=500.0)
sl_points_input = st.sidebar.number_input("Spot Stop Loss (Pts)", min_value=10.0, max_value=150.0, value=30.0, step=5.0)

# Dynamic Position Sizing
risk_inr = account_capital * (risk_pct / 100.0)
risk_per_lot = sl_points_input * 0.55 * cfg["multiplier"]
calculated_lots = max(1, int(risk_inr // risk_per_lot))
st.sidebar.info(f"📐 **Auto Sizing:** **{calculated_lots} Lot(s)** (₹{risk_inr:.0f} Risk)")

st.sidebar.markdown("---")
auto_trade_enabled = st.sidebar.toggle("⚡ Auto-Pilot Active", value=True)
trade_mode = st.sidebar.radio("Execution Target", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 3, 30, 5, 1)

if st.sidebar.button("🛑 Force Close Active Trade"):
    set_persisted_active_trade(None)
    st.sidebar.success("Active trade cleared!")
    st.rerun()

if st.sidebar.button("🗑️ Reset All Records"):
    clear_all_records()
    st.sidebar.success("All data cleared!")
    st.rerun()

smart_api_client, user_name = get_angel_session()

# Check Daily Circuit
df_hist_check = load_trade_history()
today_str = datetime.now().strftime("%Y-%m-%d")
daily_pnl = 0.0
if not df_hist_check.empty and 'Date' in df_hist_check.columns and 'Total_PnL_INR' in df_hist_check.columns:
    df_today_trades = df_hist_check[df_hist_check['Date'] == today_str]
    daily_pnl = float(df_today_trades['Total_PnL_INR'].sum())

circuit_broken = daily_pnl <= -abs(daily_loss_limit)

st.title("🎯 Tri-Engine Algo Terminal (WebSocket + Webhook + Option Chain)")

if circuit_broken:
    st.error(f"🛑 **CIRCUIT BREAKER HIT:** Daily Loss: ₹{daily_pnl:.2f}. Auto-Trading Locked for the day.")
    auto_trade_enabled = False

def val(s):
    if hasattr(s, 'values'):
        return float(s.values[0])
    return float(s)

# Load Market Data
data_5m = get_market_data(smart_api_client, cfg, interval="5m", period="5d")
data_15m = get_market_data(smart_api_client, cfg, interval="15m", period="5d")

if not data_5m.empty and len(data_5m) > 15:
    data_5m['EMA_9'] = data_5m['Close'].ewm(span=9, adjust=False).mean()
    data_5m['EMA_21'] = data_5m['Close'].ewm(span=21, adjust=False).mean()
    data_5m['Vol_SMA'] = data_5m['Volume'].rolling(20).mean()

    try:
        df_today = data_5m[data_5m.index.date == data_5m.index[-1].date()].copy()
        vol_sum = float(np.nansum(df_today['Volume'].values))
        if not df_today.empty and vol_sum > 0:
            tp = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
            data_5m.loc[df_today.index, 'VWAP'] = (tp * df_today['Volume']).cumsum() / df_today['Volume'].cumsum()
        else:
            data_5m['VWAP'] = data_5m['EMA_21']
    except Exception:
        data_5m['VWAP'] = data_5m['EMA_21']

    delta = data_5m['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    data_5m['RSI'] = 100 - (100 / (1 + rs))

    curr_c = val(data_5m['Close'].iloc[-1])
    prev_c = val(data_5m['Close'].iloc[-2]) if len(data_5m) > 1 else curr_c
    curr_o = val(data_5m['Open'].iloc[-1])
    curr_h = val(data_5m['High'].iloc[-1])
    curr_l = val(data_5m['Low'].iloc[-1])
    curr_vol = val(data_5m['Volume'].iloc[-1])
    avg_vol = val(data_5m['Vol_SMA'].iloc[-1]) if not np.isnan(val(data_5m['Vol_SMA'].iloc[-1])) else curr_vol

    e9_5m = val(data_5m['EMA_9'].iloc[-1])
    e21_5m = val(data_5m['EMA_21'].iloc[-1])
    vwap_val = val(data_5m['VWAP'].iloc[-1]) if not np.isnan(val(data_5m['VWAP'].iloc[-1])) else e21_5m
    rsi_5m = val(data_5m['RSI'].iloc[-1]) if not np.isnan(val(data_5m['RSI'].iloc[-1])) else 50.0

    step = cfg["step"]
    atm_strike = round(curr_c / step) * step
    call_strike = int(atm_strike - step)
    put_strike = int(atm_strike + step)
    est_call_ltp = round(max((curr_c - call_strike) + 85, 45.0), 1)
    est_put_ltp = round(max((put_strike - curr_c) + 85, 45.0), 1)

    # 1. Indicator Confluence Signal
    bull_confluence = (curr_c >= vwap_val) and (e9_5m >= e21_5m) and (curr_c >= e9_5m or (curr_l <= e21_5m and curr_c > e21_5m)) and (48 <= rsi_5m <= 85)
    bear_confluence = (curr_c <= vwap_val) and (e9_5m <= e21_5m) and (curr_c <= e9_5m or (curr_h >= e21_5m and curr_c < e21_5m)) and (12 <= rsi_5m <= 52)

    # 2. TradingView External Webhook Check
    tv_data = get_latest_tv_signal()
    tv_signal = tv_data.get("signal", "") if tv_data else ""

    action = "WAIT"
    suggested_strike = ""
    active_opt_ltp = 0.0
    initial_sl = 0.0

    if bull_confluence or tv_signal == "BUY_CALL":
        action = "BUY_CALL"
        suggested_strike = f"{call_strike} CE (ITM)"
        active_opt_ltp = est_call_ltp
        initial_sl = curr_c - sl_points_input
    elif bear_confluence or tv_signal == "BUY_PUT":
        action = "BUY_PUT"
        suggested_strike = f"{put_strike} PE (ITM)"
        active_opt_ltp = est_put_ltp
        initial_sl = curr_c + sl_points_input

    persisted_trade = get_persisted_active_trade()
    if persisted_trade is not None and persisted_trade.get("Asset") != selected_asset:
        persisted_trade = None
        set_persisted_active_trade(None)

    # Trade Execution
    if auto_trade_enabled and not circuit_broken and persisted_trade is None and action in ["BUY_CALL", "BUY_PUT"]:
        total_qty = calculated_lots * cfg["multiplier"]
        new_trade_data = {
            "Entry_Date": datetime.now().strftime("%Y-%m-%d"),
            "Entry_Time": datetime.now().strftime("%H:%M:%S"),
            "Asset": selected_asset,
            "Exchange": cfg["exchange"],
            "Type": action,
            "Strike": suggested_strike,
            "Entry_Spot": curr_c,
            "Option_Entry_LTP": active_opt_ltp,
            "Initial_SL": initial_sl,
            "Trailing_SL": initial_sl,
            "Peak_Price": curr_c,
            "Cost_Shifted": False,
            "Qty": total_qty,
            "Lots": calculated_lots,
            "Product": product_type,
            "Mode": trade_mode,
            "Cost_Shift_Pts": cfg["cost_shift"],
            "Trail_Step_Pts": cfg["trail_step"]
        }
        set_persisted_active_trade(new_trade_data)
        persisted_trade = new_trade_data
        send_telegram_alert(
            BOT_TOKEN, CHAT_ID,
            f"⚡ *HYBRID ORDER*\n\n📌 *Asset:* `{selected_asset}`\n🎯 *Signal:* `{action}` (TV: {tv_signal if tv_signal else 'Hybrid'})\n🏷 *Strike:* `{suggested_strike}` (LTP: ₹{active_opt_ltp})\n📦 *Lots:* {calculated_lots}\n💰 *Spot:* ₹{curr_c:.2f}\n🛑 *SL:* ₹{initial_sl:.2f}"
        )
        if tv_signal:
            set_latest_tv_signal = None
            if os.path.exists(TV_SIGNAL_FILE):
                os.remove(TV_SIGNAL_FILE)

    # Top Confluence Row
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Live Spot", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
    w2.metric("ITM Call LTP", f"₹{est_call_ltp:.1f}", f"Strike: {call_strike} CE")
    w3.metric("ITM Put LTP", f"₹{est_put_ltp:.1f}", f"Strike: {put_strike} PE")
    tv_status = f"⚡ {tv_signal}" if tv_signal else "🟢 Listening (:5001)"
    w4.metric("TradingView Webhook", tv_status)

    # --- NSE OPTION CHAIN OI TRAP RADAR ---
    st.write("---")
    st.write("### 📊 NSE Live Option Chain & Open Interest Trap")
    if cfg.get("nse_sym"):
        df_oc = fetch_nse_option_chain(cfg["nse_sym"])
        if not df_oc.empty:
            df_oc_filtered = df_oc[(df_oc['Strike'] >= atm_strike - (step*4)) & (df_oc['Strike'] <= atm_strike + (step*4))].copy()
            total_call_oi = df_oc_filtered['Call_OI'].sum()
            total_put_oi = df_oc_filtered['Put_OI'].sum()
            oi_pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

            oc_col1, oc_col2, oc_col3 = st.columns(3)
            oc_col1.metric("Option Chain PCR", f"{oi_pcr:.2f}", "Bullish Floor" if oi_pcr >= 1.15 else ("Bearish Wall" if oi_pcr <= 0.85 else "Neutral"))
            oc_col2.metric("Total Put Writing (Support)", f"{int(total_put_oi):,}")
            oc_col3.metric("Total Call Writing (Resistance)", f"{int(total_call_oi):,}")

            st.dataframe(df_oc_filtered[['Strike', 'Call_OI', 'Call_Chng_OI', 'Put_OI', 'Put_Chng_OI']], use_container_width=True)
        else:
            st.info("ℹ️ NSE Option Chain API connects directly during live market hours.")
    else:
        st.info(f"ℹ️ Option Chain OI Tracker is active for NIFTY & BANK NIFTY.")

    # --- LIVE POSITION TERMINAL ---
    st.write("---")
    st.write("### 💼 Live Position Terminal")
    if persisted_trade is not None:
        t = persisted_trade
        entry = t["Entry_Spot"]
        opt_entry = t.get("Option_Entry_LTP", 100.0)
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
                exit_reason = "COST / TRAIL EXIT 🛑" if t["Cost_Shifted"] else "HARD SL HIT 🛑"
        else:
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
                exit_reason = "COST / TRAIL EXIT 🛑" if t["Cost_Shifted"] else "HARD SL HIT 🛑"

        opt_points = round(pts_diff * 0.55, 2)
        curr_opt_ltp = round(max(opt_entry + opt_points, 1.0), 1)
        trade_pnl = round(opt_points * qty, 2)

        if not is_closed:
            set_persisted_active_trade(t)

        pos1, pos2, pos3, pos4 = st.columns(4)
        pos1.metric("Position Instrument", f"{t['Strike']}", f"Lots: {t.get('Lots', 1)}")
        pos2.metric("Option LTP", f"₹{curr_opt_ltp:.1f}", f"Entry: ₹{opt_entry:.1f}")
        pos3.metric("Spot Move", f"{pts_diff:+.2f} pts", f"Entry: ₹{entry:.2f}")
        pos4.metric("Live Net P&L (₹)", f"₹{trade_pnl:+.2f}", delta=f"{trade_pnl:.2f}")

        st.info(f"🛡️ **Trailing SL:** ₹{t['Trailing_SL']:.2f} | Status: {'Zero Risk Cost Locked 🔒' if t['Cost_Shifted'] else 'Initial SL Active ⏳'}")

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
                "Opt_Entry": opt_entry,
                "Opt_Exit": curr_opt_ltp,
                "Spot_Points": round(pts_diff, 2),
                "Total_PnL_INR": trade_pnl,
                "Exit_Reason": exit_reason,
                "Mode": t["Mode"]
            }
            save_trade_to_csv(completed_trade)
            set_persisted_active_trade(None)
            send_telegram_alert(
                BOT_TOKEN, CHAT_ID,
                f"🏁 *TRADE CLOSED*\n\n📌 *Asset:* `{t['Asset']}`\n🏷 *Strike:* `{t['Strike']}`\n💰 *P&L:* ₹{trade_pnl:+.2f}\n🚪 *Reason:* `{exit_reason}`"
            )
            st.rerun()
    else:
        st.info("🟢 **इंजन सक्रिय है:** हाइब्रिड कन्फ्लुएंस या TradingView Webhook सिग्नल मिलते ही ट्रेड एग्जीक्यूट होगा।")

    # Candlestick Chart
    st.write("### 📈 Live Multi-Overlay Candlestick Chart")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(
        x=data_5m.index,
        open=data_5m['Open'].values.flatten() if hasattr(data_5m['Open'], 'values') else data_5m['Open'],
        high=data_5m['High'].values.flatten() if hasattr(data_5m['High'], 'values') else data_5m['High'],
        low=data_5m['Low'].values.flatten() if hasattr(data_5m['Low'], 'values') else data_5m['Low'],
        close=data_5m['Close'].values.flatten() if hasattr(data_5m['Close'], 'values') else data_5m['Close'],
        name="Price"
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['VWAP'].values.flatten() if hasattr(data_5m['VWAP'], 'values') else data_5m['VWAP'], line=dict(color='yellow', width=2), name="VWAP"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_9'].values.flatten() if hasattr(data_5m['EMA_9'], 'values') else data_5m['EMA_9'], line=dict(color='lime', width=1.5), name="9 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['EMA_21'].values.flatten() if hasattr(data_5m['EMA_21'], 'values') else data_5m['EMA_21'], line=dict(color='orange', width=1.5), name="21 EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=data_5m.index, y=data_5m['RSI'].values.flatten() if hasattr(data_5m['RSI'], 'values') else data_5m['RSI'], line=dict(color='magenta', width=1.5), name="RSI"), row=2, col=1)
    fig.update_layout(height=480, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

# Completed Trade History
st.write("---")
st.write("### 📚 Completed Trade Book & Historical Performance")
df_history = load_trade_history()
if not df_history.empty:
    col_j1, col_j2, col_j3 = st.columns(3)
    total_pnl_all = float(df_history['Total_PnL_INR'].sum())
    total_trades = len(df_history)
    winning_trades = len(df_history[df_history['Total_PnL_INR'] > 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

    col_j1.metric("Cumulative Net P&L", f"₹{total_pnl_all:+.2f}", delta=f"{total_pnl_all:.2f}")
    col_j2.metric("Total Trades Executed", f"{total_trades}")
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
    st.info("ℹ️ पहला ट्रेड क्लोज होते ही पूरी हिस्ट्री और डाउनलोड बटन यहाँ दिखेगा।")

if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
    import pandas as pd
import ta
from datetime import datetime, timedelta

def get_nifty_signal(smart_api):
    to_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    from_date = (datetime.now() - timedelta(days=4)).strftime('%Y-%m-%d 09:15')

    params = {
        "exchange": "NSE",
        "symboltoken": "99926000",
        "interval": "FIVE_MINUTE",
        "fromdate": from_date,
        "todate": to_date
    }
    try:
        response = smart_api.getCandleData(params)
        if not response or response.get('data') is None:
            return None, 0
            
        candles = response['data']
        df = pd.DataFrame(candles, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        df['rsi'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        df['ema20'] = ta.trend.EMAIndicator(close=df['close'], window=20).ema_indicator()
        
        df['pivot_low'] = df['low'] == df['low'].rolling(window=11, center=True).min()
        df['pivot_high'] = df['high'] == df['high'].rolling(window=11, center=True).max()
        
        latest_close = df['close'].iloc[-1]
        latest_ema = df['ema20'].iloc[-1]
        
        low_pivots = df[df['pivot_low']].tail(2)
        if len(low_pivots) == 2:
            prev_p = low_pivots.iloc[0]
            curr_p = low_pivots.iloc[1]
            if curr_p['low'] < prev_p['low'] and curr_p['rsi'] > prev_p['rsi']:
                if latest_close > latest_ema:
                    return "BUY_CALL", latest_close

        high_pivots = df[df['pivot_high']].tail(2)
        if len(high_pivots) == 2:
            prev_p = high_pivots.iloc[0]
            curr_p = high_pivots.iloc[1]
            if curr_p['high'] > prev_p['high'] and curr_p['rsi'] < prev_p['rsi']:
                if latest_close < latest_ema:
                    return "BUY_PUT", latest_close
                    
        return None, latest_close
    except Exception as e:
        print(f"Strategy Error: {e}")
        return None, 0
