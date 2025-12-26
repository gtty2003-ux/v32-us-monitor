import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import time

# --- 設定頁面資訊 ---
st.set_page_config(
    page_title="V32 美股戰情室 (Dual Core)",
    layout="wide",
    page_icon="🦅"
)

# --- 樣式設定 ---
st.markdown("""
    <style>
    .stDataFrame thead tr th {background-color: #e3f2fd !important; color: #0d47a1 !important; font-weight: bold;}
    div[data-testid="stMetricValue"] {font-size: 24px; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

# --- 工具函數 ---
def get_us_time():
    """取得美東時間"""
    return datetime.now(pytz.timezone('US/Eastern')).strftime("%Y-%m-%d %H:%M:%S")

def color_earnings(val):
    """財報倒數顏色標示"""
    if not isinstance(val, int): return ''
    if val <= 5:
        return 'color: white; background-color: #d32f2f; font-weight: bold;' # 紅底 (危險)
    elif val <= 14:
        return 'color: black; background-color: #ffeb3b; font-weight: bold;' # 黃底 (警戒)
    return 'color: #1b5e20; font-weight: bold;' # 綠字 (安全)

def color_v32_score(val):
    """V32 分數顏色"""
    if val >= 90: return 'color: #d32f2f; font-weight: bold;' # 極強
    if val >= 80: return 'color: #1565c0; font-weight: bold;' # 強
    return ''

# --- 核心邏輯 ---
@st.cache_data(ttl=3600)
def get_market_status():
    """大盤濾網 (S&P 500)"""
    try:
        spy = yf.Ticker("^GSPC") # S&P 500 Index
        hist = spy.history(period="1y")
        if hist.empty: return None
        
        close = hist['Close']
        curr = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        
        status = "不明"
        signal = "🟡"
        
        if curr > ma200:
            if curr > ma20:
                status = "🟢 多頭進攻 (Bullish)"
                signal = "🟢"
            elif curr > ma50:
                status = "🟡 多頭回檔 (Correction)"
                signal = "🟡"
            else:
                status = "🟠 跌破季線 (Weak)"
                signal = "🟠"
        else:
            status = "🔴 空頭走勢 (Bearish)"
            signal = "🔴"
            
        return {'status': status, 'signal': signal, 'price': curr, 'ma200': ma200}
    except: return None

def get_earnings_days(ticker_obj):
    """計算距離下次財報還有幾天"""
    try:
        cal = ticker_obj.calendar
        if cal is not None and not cal.empty:
            # yfinance 的 calendar 格式有時會變，嘗試抓取日期
            next_date = cal.iloc[0][0] # 通常第一列是 Earnings Date
            # 確保是未來時間，如果是過去的就找下一個 (簡易邏輯)
            if isinstance(next_date, (datetime, pd.Timestamp)):
                 days = (next_date.date() - datetime.now().date()).days
                 return days if days > -90 else 999 # 若數據太舊則回傳 999
        return 999 # 無法取得
    except:
        return 999

def calculate_v32_us(ticker):
    """計算美股 V32 分數 (雙軌邏輯)"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if len(hist) < 200: return None
        
        # 基礎數據
        close = hist['Close']
        vol = hist['Volume']
        curr = close.iloc[-1]
        
        # MA
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        
        # RVol (相對量能) - 過去 20 日均量
        vol_ma20 = vol.rolling(20).mean().iloc[-1]
        curr_vol = vol.iloc[-1]
        rvol = curr_vol / vol_ma20 if vol_ma20 > 0 else 0
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]

        # MACD
        exp12 = close.ewm(span=12, adjust=False).mean()
        exp26 = close.ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_val = macd.iloc[-1]
        sig_val = signal.iloc[-1]
        
        # --- 評分邏輯 ---
        score = 60 # 基礎分
        
        # 1. 趨勢 (40%)
        if curr > ma200: score += 10
        if curr > ma50: score += 10
        if ma50 > ma200: score += 10 # 多頭排列
        if curr > ma20: score += 10
        
        # 2. 量能 (30%) - RVol 是關鍵
        if rvol > 1.2: score += 5
        if rvol > 1.5: score += 10
        if rvol > 2.0: score += 15 # 爆量
        
        # 3. 指標 (30%)
        if 50 < rsi < 75: score += 10 # 強勢區
        if macd_val > sig_val: score += 10 # 黃金交叉
        if macd_val > 0: score += 10 # 零軸之上

        # 4. 取得財報日 (用於庫存顯示)
        days_to_earn = get_earnings_days(stock)
        
        return {
            '代號': ticker,
            '即時價': curr,
            'V32總分': min(100, score),
            'RVol': rvol,
            'RSI': rsi,
            '距200MA': (curr - ma200) / ma200 * 100,
            '財報倒數': days_to_earn
        }
    except Exception as e:
        return None

# --- 主程式 ---
def main():
    st.title("🦅 V32 美股戰情室")
    st.caption(f"美東時間: {get_us_time()}")
    
    # 1. 大盤顯示
    market = get_market_status()
    if market:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.info(f"{market['signal']} **S&P 500 狀態：{market['status']}**")
        with c2:
            st.metric("S&P 500", f"{market['price']:.2f}", f"MA200: {market['ma200']:.0f}")
        st.divider()

    # 2. 定義標的池 (為了演示，先寫死，之後可改為讀檔)
    shield_list = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD', 'COST', 'BRK-B']
    spear_list = ['PLTR', 'SOFI', 'MARA', 'COIN', 'GME', 'PATH', 'UPST', 'AI', 'DKNG', 'RBLX']
    
    # 3. 庫存模擬數據 (因為沒有資料庫，先用 Session State 模擬)
    if 'inventory' not in st.session_state:
        st.session_state['inventory'] = [
            {'代號': 'AAPL', '類型': '🛡️ 穩健', '成本': 180.0, '股數': 50},
            {'代號': 'PLTR', '類型': '🚀 攻擊', '成本': 18.5, '股數': 200}
        ]

    # --- Tabs ---
    tab_inv, tab_shield, tab_spear = st.tabs(["🏰 庫存堡壘", "🛡️ 穩健戰艦 (S&P)", "🚀 攻擊快艇 (Momentum)"])

    # === Tab 1: 庫存堡壘 ===
    with tab_inv:
        st.subheader("⚠️ 風險監控面板")
        if st.button("🔄 更新庫存狀態"):
            inv_data = []
            progress = st.progress(0)
            for i, item in enumerate(st.session_state['inventory']):
                data = calculate_v32_us(item['代號'])
                if data:
                    profit = (data['即時價'] - item['成本']) * item['股數']
                    profit_pct = (data['即時價'] - item['成本']) / item['成本'] * 100
                    
                    # 建議邏輯
                    advise = "續抱"
                    if data['財報倒數'] <= 5: advise = "🔴 財報避險(賣出)"
                    elif item['類型'] == '🚀 攻擊' and data['即時價'] < data['即時價'] * 0.9: advise = "🔴 停損出場" # 簡易停損邏輯
                    elif data['V32總分'] < 60: advise = "🟡 轉弱觀察"
                    
                    inv_data.append({
                        '代號': item['代號'],
                        '類型': item['類型'],
                        '即時價': data['即時價'],
                        '損益($)': profit,
                        '報酬率%': profit_pct,
                        '財報倒數': data['財報倒數'],
                        'V32分': data['V32總分'],
                        '建議': advise
                    })
                progress.progress((i+1)/len(st.session_state['inventory']))
            progress.empty()
            
            if inv_data:
                df_inv = pd.DataFrame(inv_data)
                st.dataframe(df_inv.style.format({
                    '即時價': '{:.2f}', '損益($)': '{:+.0f}', '報酬率%': '{:+.2f}%', 'V32分': '{:.0f}'
                }).map(color_earnings, subset=['財報倒數'])
                  .map(color_v32_score, subset=['V32分']), 
                use_container_width=True)
            else:
                st.warning("無法讀取數據")

    # === Tab 2: 穩健戰艦 ===
    with tab_shield:
        st.caption("篩選邏輯：S&P 500 成分股 | 站上 200MA | 尋找拉回支撐")
        if st.button("🔎 掃描穩健池", key='btn_shield'):
            results = []
            progress = st.progress(0)
            for i, ticker in enumerate(shield_list):
                data = calculate_v32_us(ticker)
                if data and data['V32總分'] >= 70: # 只顯示合格的
                    results.append(data)
                progress.progress((i+1)/len(shield_list))
            progress.empty()
            
            if results:
                df = pd.DataFrame(results)
                st.dataframe(df[['代號', '即時價', 'V32總分', 'RVol', '距200MA', 'RSI']].style.format({
                    '即時價': '{:.2f}', 'V32總分': '{:.0f}', 'RVol': '{:.2f}x', '距200MA': '{:+.2f}%', 'RSI': '{:.0f}'
                }).background_gradient(subset=['V32總分'], cmap='Blues'), use_container_width=True)

    # === Tab 3: 攻擊快艇 ===
    with tab_spear:
        st.caption("篩選邏輯：熱門成長股 | RVol 爆量 | 尋找動能突破")
        if st.button("🔥 掃描攻擊池", key='btn_spear'):
            results = []
            progress = st.progress(0)
            for i, ticker in enumerate(spear_list):
                data = calculate_v32_us(ticker)
                if data and data['V32總分'] >= 80: # 攻擊型要求更高分
                    results.append(data)
                progress.progress((i+1)/len(spear_list))
            progress.empty()
            
            if results:
                df = pd.DataFrame(results)
                st.dataframe(df[['代號', '即時價', 'V32總分', 'RVol', 'RSI', '財報倒數']].style.format({
                    '即時價': '{:.2f}', 'V32總分': '{:.0f}', 'RVol': '{:.2f}x', 'RSI': '{:.0f}'
                }).background_gradient(subset=['RVol'], cmap='Reds')
                  .map(color_earnings, subset=['財報倒數']), use_container_width=True)

if __name__ == "__main__":
    main()
