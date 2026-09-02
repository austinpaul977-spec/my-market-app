import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import os
import json
import pyotp
from datetime import datetime, timedelta
from SmartApi import SmartConnect
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Institutional Engine & Risk Backtester", layout="wide")

BOT_TOKEN = "8751296227:AAERElotbBhsItNoZAsFjIgYhArGB3Mw1eI"
CHAT_ID = "7921963538"
API_KEY = "lga05JNK"
CLIENT_CODE = "O53184355"
PIN = "1914"
TOTP_SECRET = "QNJM3G2COJWVQ44CVS4CFHBKIE"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "trade_history.csv")
ACTIVE_TRADE_FILE = os.path.join(BASE_DIR, "active_trade.json")

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

# --- SIDEBAR: ASSET & RISK CONFIGURATION ---
st.sidebar.header("⚙️ Market Controls")
asset_config = {
    "NIFTY 50": {"yf_symbol": "^NSEI", "token": "99926000", "exchange": "NSE", "step": 50, "multiplier": 75, "cost_shift": 15.0, "trail_step": 25.0},
    "BANK NIFTY": {"yf_symbol": "^NSEBANK", "token": "99926009", "exchange": "NSE", "step": 100, "multiplier": 25, "cost_shift": 30.0, "trail_step": 50.0},
    "SENSEX": {"yf_symbol": "^BSESN", "token": "99919000", "exchange": "BSE", "step": 100, "multiplier": 20, "cost_shift": 40.0, "trail_step": 70.0},
    "CRUDE OIL": {"yf_symbol": "CL=F", "token": "253460", "exchange": "MCX", "step": 50, "multiplier": 100, "cost_shift": 12.0, "trail_step": 20.0},
    "RELIANCE": {"yf_symbol": "RELIANCE.NS", "token": "2885", "exchange": "NSE", "step": 20, "multiplier": 250, "cost_shift": 5.0, "trail_step": 10.0},
    "INFY": {"yf_symbol": "INFY.NS", "token": "1594", "exchange": "NSE", "step": 20, "multiplier": 400, "cost_shift": 4.0, "trail_step": 8.0}
}

selected_asset = st.sidebar.selectbox("Asset", list(asset_config.keys()), index=0)
cfg = asset_config[selected_asset]
product_type = st.sidebar.selectbox("Order Product", ["CARRYFORWARD (NRML)", "INTRADAY (MIS)"], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Strict Risk Management")
account_capital = st.sidebar.number_input("Account Capital (₹)", min_value=10000.0, max_value=5000000.0, value=100000.0, step=10000.0)
risk_per_trade_pct = st.sidebar.slider("Risk Per Trade (%)", 0.5, 5.0, 1.5, 0.25)
daily_loss_limit = st.sidebar.number_input("Daily Max Loss Circuit (₹)", min_value=1000.0, max_value=50000.0, value=3000.0, step=500.0)
max_slippage_pts = st.sidebar.number_input("Max Slippage Guard (Pts)", min_value=1.0, max_value=10.0, value=3.0, step=0.5)
sl_points_input = st.sidebar.number_input("Spot Stop Loss (Pts)", min_value=10.0, max_value=150.0, value=30.0, step=5.0)

# Position Sizing Calculator
risk_inr = account_capital * (risk_per_trade_pct / 100.0)
risk_per_lot = sl_points_input * 0.55 * cfg["multiplier"]
calculated_lots = max(1, int(risk_inr // risk_per_lot))
st.sidebar.info(f"📐 **Auto Sizing:** **{calculated_lots} Lot(s)** (Risk: ₹{risk_inr:.0f} / Trade)")

st.sidebar.markdown("---")
auto_trade_enabled = st.sidebar.toggle("⚡ Auto-Pilot Mode", value=True)
trade_mode = st.sidebar.radio("Target", ["📝 Paper Trading (Virtual)", "⚡ Live Demat (Angel One)"], index=0)
auto_refresh = st.sidebar.checkbox("Auto-Refresh Loop", value=True)
refresh_interval = st.sidebar.slider("Interval (sec)", 3, 30, 5, 1)

if st.sidebar.button("🛑 Force Close Active Trade"):
    set_persisted_active_trade(None)
    st.sidebar.success("सक्रिय ट्रेड रीसेट हुआ!")
    st.rerun()

if st.sidebar.button("🗑️ Reset All Records & History"):
    clear_all_records()
    st.sidebar.success("हिस्ट्री रीसेट हो गई!")
    st.rerun()

smart_api_client, user_name = get_angel_session()

# Check Daily Circuit Breaker
df_hist_check = load_trade_history()
today_str = datetime.now().strftime("%Y-%m-%d")
daily_pnl = 0.0
if not df_hist_check.empty and 'Date' in df_hist_check.columns and 'Total_PnL_INR' in df_hist_check.columns:
    df_today_trades = df_hist_check[df_hist_check['Date'] == today_str]
    daily_pnl = float(df_today_trades['Total_PnL_INR'].sum())

circuit_broken = daily_pnl <= -abs(daily_loss_limit)

st.title("🎯 Institutional Algo & Quantitative Workspace")

if circuit_broken:
    st.error(f"🛑 **DAILY RISK CIRCUIT BREAKER HIT:** Today's Loss is ₹{daily_pnl:.2f} (Limit: -₹{daily_loss_limit:.2f}). Algo locked for rest of the day!")
    auto_trade_enabled = False

tab_live, tab_backtest = st.tabs(["⚡ Live Trading Terminal & Journal", "📊 Automated Quantitative Backtester"])

def val(s):
    if hasattr(s, 'values'):
        return float(s.values[0])
    return float(s)

# ==================== TAB 1: LIVE TERMINAL ====================
with tab_live:
    if smart_api_client:
        st.success(f"🔗 **Broker Connected:** {user_name} (`{CLIENT_CODE}`) | Feed: **{selected_asset}** | Daily P&L: **₹{daily_pnl:+.2f}**")
    else:
        st.info("ℹ️ Market Engine Syncing...")

    data_5m = get_market_data(smart_api_client, cfg, interval="5m", period="5d")
    data_15m = get_market_data(smart_api_client, cfg, interval="15m", period="5d")
    data_1h = get_market_data(smart_api_client, cfg, interval="1h", period="1mo")

    if not data_5m.empty and len(data_5m) > 15:
        data_5m['EMA_9'] = data_5m['Close'].ewm(span=9, adjust=False).mean()
        data_5m['EMA_21'] = data_5m['Close'].ewm(span=21, adjust=False).mean()
        data_5m['EMA_50'] = data_5m['Close'].ewm(span=50, adjust=False).mean()
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

        trend_15m = "🟡 NEUTRAL"
        if not data_15m.empty and len(data_15m) > 20:
            e20_15 = val(data_15m['Close'].ewm(span=20).mean().iloc[-1])
            c_15 = val(data_15m['Close'].iloc[-1])
            trend_15m = "🟢 BULLISH" if c_15 > e20_15 else "🔴 BEARISH"

        diff_ratio = (curr_c - e21_5m) / e21_5m if e21_5m > 0 else 0
        derived_pcr = max(min(round(1.0 + (diff_ratio * 15), 2), 1.75), 0.55)

        step = cfg["step"]
        atm_strike = round(curr_c / step) * step
        call_strike = int(atm_strike - step)
        put_strike = int(atm_strike + step)
        est_call_ltp = round(max((curr_c - call_strike) + 85, 45.0), 1)
        est_put_ltp = round(max((put_strike - curr_c) + 85, 45.0), 1)

        bull_confluence = (curr_c >= vwap_val) and (e9_5m >= e21_5m) and (curr_c >= e9_5m or (curr_l <= e21_5m and curr_c > e21_5m)) and (48 <= rsi_5m <= 85)
        bear_confluence = (curr_c <= vwap_val) and (e9_5m <= e21_5m) and (curr_c <= e9_5m or (curr_h >= e21_5m and curr_c < e21_5m)) and (12 <= rsi_5m <= 52)

        action = "WAIT"
        suggested_strike = ""
        active_opt_ltp = 0.0
        initial_sl = 0.0

        if bull_confluence:
            action = "BUY_CALL"
            suggested_strike = f"{call_strike} CE (ITM)"
            active_opt_ltp = est_call_ltp
            initial_sl = curr_c - sl_points_input
        elif bear_confluence:
            action = "BUY_PUT"
            suggested_strike = f"{put_strike} PE (ITM)"
            active_opt_ltp = est_put_ltp
            initial_sl = curr_c + sl_points_input

        persisted_trade = get_persisted_active_trade()
        if persisted_trade is not None and persisted_trade.get("Asset") != selected_asset:
            persisted_trade = None
            set_persisted_active_trade(None)

        # Execution with Slippage Guard
        if auto_trade_enabled and not circuit_broken and persisted_trade is None and action in ["BUY_CALL", "BUY_PUT"]:
            # Slippage Guard: Skip trade if candle range is extraordinarily wild
            candle_spread = abs(curr_c - curr_o)
            if candle_spread > (max_slippage_pts * 8):
                st.warning(f"⚠️ Trade Skipped by Slippage Guard! Volatility Spike detected ({candle_spread:.1f} pts).")
            else:
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
                    f"⚡ *NEW HYBRID ORDER*\n\n📌 *Asset:* `{selected_asset}`\n🎯 *Signal:* `{action}`\n🏷 *Strike:* `{suggested_strike}` (LTP: ₹{active_opt_ltp})\n📦 *Lots:* {calculated_lots} ({total_qty} Qty)\n💰 *Spot Entry:* ₹{curr_c:.2f}\n🛑 *Spot SL:* ₹{initial_sl:.2f}"
                )

        # Radar Row
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Live Spot", f"₹{curr_c:.2f}", f"{((curr_c - prev_c)/prev_c)*100:.2f}%")
        r2.metric("ITM Call LTP", f"₹{est_call_ltp:.1f}", f"Strike: {call_strike} CE")
        r3.metric("ITM Put LTP", f"₹{est_put_ltp:.1f}", f"Strike: {put_strike} PE")
        r4.metric("PCR Health", f"{derived_pcr:.2f}")

        # Active Position Monitor
        st.write("### 💼 Active Position Terminal")
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
            pos2.metric("Option Premium LTP", f"₹{curr_opt_ltp:.1f}", f"Entry: ₹{opt_entry:.1f}")
            pos3.metric("Spot Movement", f"{pts_diff:+.2f} pts", f"Entry Spot: ₹{entry:.2f}")
            pos4.metric("Live Net P&L (₹)", f"₹{trade_pnl:+.2f}", delta=f"{trade_pnl:.2f}")

            st.info(f"🛡️ **Trailing Engine:** SL at **₹{t['Trailing_SL']:.2f}** | Status: {'Locked at Cost (Zero Risk) 🔒' if t['Cost_Shifted'] else 'Initial SL Active ⏳'}")

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
                    f"🏁 *TRADE COMPLETED*\n\n📌 *Asset:* `{t['Asset']}`\n🏷 *Strike:* `{t['Strike']}`\n💰 *Real P&L:* ₹{trade_pnl:+.2f}\n🚪 *Reason:* `{exit_reason}`"
                )
                st.rerun()
        else:
            st.info("🟢 **इंजन सक्रिय है:** कन्फ्लुएंस बनते ही पोजीशन साइजिंग के अनुसार ऑटो-ट्रेड प्लेस होगा।")

        # Chart
        st.write("### 📈 Live Candlestick Multi-Overlay")
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

    # Permanent Trade Book
    st.write("---")
    st.write("### 📚 Completed Trade Book & Historical Journal")
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

# ==================== TAB 2: AUTOMATED BACKTESTER ====================
with tab_backtest:
    st.subheader(f"📊 Quantitative Backtest Simulation ({selected_asset})")
    st.write("यह इंजन पिछले 60 दिनों के 5-मिनट डेटा पर हाइब्रिड स्ट्रेटेजी के सिग्नल्स को बैकटेस्ट करता है।")

    backtest_period = st.selectbox("Historical Horizon", ["30d", "60d"], index=0)

    if st.button("🚀 Run Institutional Backtest"):
        with st.spinner("Simulating historical execution..."):
            try:
                df_bt = yf.download(cfg["yf_symbol"], period=backtest_period, interval="5m", progress=False)
                if isinstance(df_bt.columns, pd.MultiIndex):
                    df_bt.columns = df_bt.columns.get_level_values(0)
                df_bt = df_bt[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()

                if len(df_bt) > 50:
                    df_bt['EMA_9'] = df_bt['Close'].ewm(span=9, adjust=False).mean()
                    df_bt['EMA_21'] = df_bt['Close'].ewm(span=21, adjust=False).mean()

                    delta_bt = df_bt['Close'].diff()
                    g_bt = (delta_bt.where(delta_bt > 0, 0)).rolling(14).mean()
                    l_bt = (-delta_bt.where(delta_bt < 0, 0)).rolling(14).mean()
                    df_bt['RSI'] = 100 - (100 / (1 + (g_bt / l_bt)))

                    trades = []
                    in_pos = False
                    pos_type = ""
                    entry_p = 0.0
                    sl_p = 0.0
                    cost_shifted = False

                    # Iterative Candle Simulation
                    for i in range(25, len(df_bt)):
                        close_p = float(df_bt['Close'].iloc[i])
                        high_p = float(df_bt['High'].iloc[i])
                        low_p = float(df_bt['Low'].iloc[i])
                        e9 = float(df_bt['EMA_9'].iloc[i])
                        e21 = float(df_bt['EMA_21'].iloc[i])
                        rsi = float(df_bt['RSI'].iloc[i])
                        date_idx = df_bt.index[i]

                        if not in_pos:
                            # Buy Call Condition
                            if (e9 > e21) and (close_p > e9) and (50 <= rsi <= 80):
                                in_pos = True
                                pos_type = "BUY_CALL"
                                entry_p = close_p
                                sl_p = entry_p - sl_points_input
                                cost_shifted = False
                            # Buy Put Condition
                            elif (e9 < e21) and (close_p < e9) and (20 <= rsi <= 50):
                                in_pos = True
                                pos_type = "BUY_PUT"
                                entry_p = close_p
                                sl_p = entry_p + sl_points_input
                                cost_shifted = False
                        else:
                            if pos_type == "BUY_CALL":
                                pts = close_p - entry_p
                                if pts >= cfg["cost_shift"] and not cost_shifted:
                                    sl_p = entry_p
                                    cost_shifted = True
                                if pts >= cfg["trail_step"]:
                                    trail_lvl = close_p - cfg["cost_shift"]
                                    if trail_lvl > sl_p:
                                        sl_p = trail_lvl
                                if close_p <= sl_p or i == len(df_bt) - 1:
                                    net_pts = close_p - entry_p
                                    pnl_inr = round(net_pts * 0.55 * (calculated_lots * cfg["multiplier"]), 2)
                                    trades.append({"Date": date_idx, "Type": pos_type, "P&L": pnl_inr, "Pts": net_pts})
                                    in_pos = False

                            elif pos_type == "BUY_PUT":
                                pts = entry_p - close_p
                                if pts >= cfg["cost_shift"] and not cost_shifted:
                                    sl_p = entry_p
                                    cost_shifted = True
                                if pts >= cfg["trail_step"]:
                                    trail_lvl = close_p + cfg["cost_shift"]
                                    if trail_lvl < sl_p:
                                        sl_p = trail_lvl
                                if close_p >= sl_p or i == len(df_bt) - 1:
                                    net_pts = entry_p - close_p
                                    pnl_inr = round(net_pts * 0.55 * (calculated_lots * cfg["multiplier"]), 2)
                                    trades.append({"Date": date_idx, "Type": pos_type, "P&L": pnl_inr, "Pts": net_pts})
                                    in_pos = False

                    if trades:
                        df_res = pd.DataFrame(trades)
                        df_res['Cumulative_PnL'] = df_res['P&L'].cumsum()
                        df_res['Peak'] = df_res['Cumulative_PnL'].cummax()
                        df_res['Drawdown'] = df_res['Cumulative_PnL'] - df_res['Peak']

                        tot_trades = len(df_res)
                        wins = len(df_res[df_res['P&L'] > 0])
                        losses = len(df_res[df_res['P&L'] < 0])
                        win_rate_bt = (wins / tot_trades) * 100 if tot_trades > 0 else 0
                        gross_profit = df_res[df_res['P&L'] > 0]['P&L'].sum()
                        gross_loss = abs(df_res[df_res['P&L'] < 0]['P&L'].sum())
                        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.0
                        max_dd = df_res['Drawdown'].min()

                        b1, b2, b3, b4 = st.columns(4)
                        b1.metric("Simulated Net P&L", f"₹{df_res['Cumulative_PnL'].iloc[-1]:+,.2f}")
                        b2.metric("Backtest Win Rate", f"{win_rate_bt:.1f}%", f"{wins}W / {losses}L")
                        b3.metric("Profit Factor", f"{profit_factor}")
                        b4.metric("Max Drawdown", f"₹{max_dd:,.2f}")

                        # Equity Curve
                        st.write("#### 📈 Simulated Equity Curve (Growth of Capital)")
                        fig_eq = go.Figure()
                        fig_eq.add_trace(go.Scatter(x=df_res['Date'], y=df_res['Cumulative_PnL'], mode='lines', line=dict(color='#00FFCC', width=2), name="Net P&L (₹)"))
                        fig_eq.update_layout(height=400, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Trade Date", yaxis_title="Cumulative P&L (₹)")
                        st.plotly_chart(fig_eq, use_container_width=True)

                        st.dataframe(df_res[['Date', 'Type', 'Pts', 'P&L', 'Cumulative_PnL']], use_container_width=True)
                    else:
                        st.warning("इस टाइमफ्रेम में कोई मान्य सिग्नल नहीं मिला।")
                else:
                    st.error("बैकटेस्ट के लिए पर्याप्त हिस्टोरिकल डेटा नहीं मिला।")
            except Exception as e:
                st.error(f"Backtesting Error: {e}")

if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
