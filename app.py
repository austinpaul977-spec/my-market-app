import streamlit as st
import pandas as pd
import yfinance as yf
import ta
import plotly.graph_objects as go
from datetime import datetime, timedelta

# Page Configuration
st.set_page_config(
    page_title="NIFTY 50 Market Analysis & Algo",
    page_icon="📈",
    layout="wide"
)

st.title("📈 NIFTY 50 Strategy & Live Analysis Dashboard")

# Sidebar Controls
st.sidebar.header("Data & Strategy Settings")
timeframe = st.sidebar.selectbox("Interval", ["5m", "15m", "1h", "1d"], index=0)
period_days = st.sidebar.slider("Data Period (Days)", min_value=5, max_value=60, value=30)

ema_period = st.sidebar.number_input("EMA Period", value=20)
rsi_period = st.sidebar.number_input("RSI Period", value=14)
adx_threshold = st.sidebar.number_input("ADX Trending Threshold", value=25)

# Fetch Market Data (Free & High Reliability via Yahoo Finance)
@st.cache_data(ttl=60)
def load_market_data(interval, days):
    ticker = "^NSEI"  # NIFTY 50 Index
    data = yf.download(tickers=ticker, period=f"{days}d", interval=interval, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.dropna()
    return data

with st.spinner("Market data fetch ho raha hai..."):
    df = load_market_data(timeframe, period_days)

if df.empty:
    st.error("Market data load nahi ho paya. Kripya timeframe ya days badal kar dekhein.")
    st.stop()

# Technical Indicators
df['EMA'] = ta.trend.EMAIndicator(close=df['Close'], window=int(ema_period)).ema_indicator()
df['RSI'] = ta.momentum.RSIIndicator(close=df['Close'], window=int(rsi_period)).rsi()
df['ADX'] = ta.trend.ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14).adx()
df['ATR'] = ta.volatility.AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14).average_true_range()

latest = df.iloc[-1]
prev = df.iloc[-2]

# Top Metrics Row
col1, col2, col3, col4 = st.columns(4)
col1.metric("NIFTY 50 Current", f"{latest['Close']:.2f}", f"{latest['Close'] - prev['Close']:.2f}")
col2.metric("RSI (14)", f"{latest['RSI']:.2f}")
col3.metric("ADX (14)", f"{latest['ADX']:.2f}", "Trending" if latest['ADX'] > adx_threshold else "Ranging")
col4.metric("EMA (20)", f"{latest['EMA']:.2f}")

# Market Regime & Signal Engine
market_regime = "TRENDING" if latest['ADX'] > adx_threshold else "RANGING (SIDEWAYS)"

signal = "NEUTRAL"
reason = "Conditions meet nahi hui"

if market_regime == "TRENDING":
    if latest['Close'] > prev['High'] and latest['Close'] > latest['EMA']:
        signal = "BUY CALL (Momentum Breakout)"
        reason = "ADX > 25, Price above EMA & Prev Candle High"
    elif latest['Close'] < prev['Low'] and latest['Close'] < latest['EMA']:
        signal = "BUY PUT (Momentum Breakdown)"
        reason = "ADX > 25, Price below EMA & Prev Candle Low"
else:
    if latest['RSI'] < 30 and latest['Close'] > latest['EMA']:
        signal = "BUY CALL (Mean Reversion)"
        reason = "ADX <= 25, RSI Oversold bounce"
    elif latest['RSI'] > 70 and latest['Close'] < latest['EMA']:
        signal = "BUY PUT (Mean Reversion)"
        reason = "ADX <= 25, RSI Overbought pullback"

st.info(f"**Current Market Regime:** `{market_regime}` | **Active Signal:** `{signal}` | **Reason:** {reason}")

# Interactive Candlestick Chart
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=df.index,
    open=df['Open'], high=df['High'],
    low=df['Low'], close=df['Close'],
    name="NIFTY 50"
))
fig.add_trace(go.Scatter(x=df.index, y=df['EMA'], line=dict(color='orange', width=1.5), name="EMA 20"))
fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=30, b=20))
st.plotly_chart(fig, use_container_width=True)

# Backtest Simulation Engine
st.subheader("Strategy Backtest Report (Selected Period)")

trades = []
in_pos = False
pos_type = None
entry_p = 0
trail_sl = 0

for i in range(30, len(df)):
    c = df.iloc[i]
    p = df.iloc[i-1]
    
    if in_pos:
        if pos_type == "CALL":
            trail_sl = max(trail_sl, c['Close'] - (1.8 * c['ATR']))
            if c['Low'] <= trail_sl:
                trades.append({"Type": "CALL", "Entry": entry_p, "Exit": trail_sl, "PnL": trail_sl - entry_p})
                in_pos = False
        elif pos_type == "PUT":
            trail_sl = min(trail_sl, c['Close'] + (1.8 * c['ATR']))
            if c['High'] >= trail_sl:
                trades.append({"Type": "PUT", "Entry": entry_p, "Exit": trail_sl, "PnL": entry_p - trail_sl})
                in_pos = False
        continue

    # Signals
    if c['ADX'] > adx_threshold:
        if c['Close'] > p['High'] and c['Close'] > c['EMA']:
            in_pos, pos_type, entry_p = True, "CALL", c['Close']
            trail_sl = c['Close'] - (1.5 * c['ATR'])
        elif c['Close'] < p['Low'] and c['Close'] < c['EMA']:
            in_pos, pos_type, entry_p = True, "PUT", c['Close']
            trail_sl = c['Close'] + (1.5 * c['ATR'])
    else:
        if c['RSI'] < 30 and c['Close'] > c['EMA']:
            in_pos, pos_type, entry_p = True, "CALL", c['Close']
            trail_sl = c['Close'] - (1.2 * c['ATR'])
        elif c['RSI'] > 70 and c['Close'] < c['EMA']:
            in_pos, pos_type, entry_p = True, "PUT", c['Close']
            trail_sl = c['Close'] + (1.2 * c['ATR'])

if trades:
    tdf = pd.DataFrame(trades)
    wins = tdf[tdf['PnL'] > 0]
    losses = tdf[tdf['PnL'] <= 0]
    
    bcol1, bcol2, bcol3, bcol4 = st.columns(4)
    bcol1.metric("Total Trades", len(tdf))
    bcol2.metric("Win Rate", f"{(len(wins)/len(tdf))*100:.1f}%")
    bcol3.metric("Net Points Captured", f"{tdf['PnL'].sum():.2f} pts")
    bcol4.metric("Profit/Loss Trades", f"{len(wins)} W / {len(losses)} L")
    
    with st.expander("Show Trade Logs"):
        st.dataframe(tdf.tail(20), use_container_width=True)
else:
    st.write("Is period me koi trade trigger nahi hua.")
