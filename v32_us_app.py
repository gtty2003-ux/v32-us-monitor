import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
from github import Github
import io
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
    .big-font {font-size:20px !important; font-weight: bold;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 1. GitHub 雲端存取模組
# ==========================================
def get_repo():
    """連線到 GitHub Repo"""
    try:
        # 從 Streamlit Secrets 讀取金鑰
        token = st.secrets["general"]["GITHUB_TOKEN"]
        repo_name = st.secrets["general"]["REPO_NAME"]
        g = Github(token)
        return g.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub 連線失敗: {e}")
        return None

def load_holdings():
    """從 GitHub 讀取庫存 CSV"""
    try:
        repo = get_repo()
        if not repo: return pd.DataFrame(columns=['Code', 'Type', 'Cost', 'Shares', 'Note'])
        
        try:
            contents = repo.get_contents("holdings.csv")
            df = pd.read_csv(io.StringIO(contents.decoded_content.decode()))
            df['Code'] = df['Code'].astype(str) # 確保代號是字串
            return df
        except:
            # 如果檔案不存在，回傳空的 DataFrame
            return pd.DataFrame(columns=['Code', 'Type', 'Cost', 'Shares', 'Note'])
    except Exception as e:
        st.error(f"讀取庫存失敗: {e}")
        return pd.DataFrame(columns=['Code', 'Type', 'Cost', 'Shares', 'Note'])

def save_holdings(df):
    """將庫存 DataFrame 寫回 GitHub CSV"""
    try:
        repo = get_repo()
        if not repo: return
        
        csv_content = df.to_csv(index=False)
        
        try:
            # 嘗試取得現有檔案以更新
            contents = repo.get_contents("holdings.csv")
            repo.update_file(
                path="holdings.csv",
                message=f"Update holdings {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                content=csv_content,
                sha=contents.sha
            )
        except:
            # 若檔案不存在則建立新檔案
            repo.create_file(
                path="holdings.csv",
                message="Create holdings.csv",
                content=csv_content
            )
            
        st.toast("✅ 庫存已儲存至雲端！", icon="☁️")
    except Exception as e:
        st.error(f"儲存失敗: {e}")

# ==========================================
# 2. V32 核心邏輯與運算
# ==========================================
def get_us_time():
    """取得美東時間字串"""
    return datetime.now(pytz.timezone('US/Eastern')).strftime("%Y-%m-%d %H:%M:%S")

def get_market_status():
    """大盤濾網 (S&P 500)"""
    try:
        spy = yf.Ticker("^GSPC")
        hist = spy.history(period="1y")
        if hist.empty: return None
        
        close = hist['Close']
        curr = close.iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        
        status = "不明"
        signal = "🟡"
        
        # 簡單的均線多空判定
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
        # 嘗試抓取日曆
        cal = ticker_obj.calendar
        if cal is not None and not cal.empty:
            # 不同版本的 yfinance 格式可能不同，這裡嘗試通用的抓法
            # 通常第一行或 key 為 'Earnings Date'
            earnings_date = cal.iloc[0][0] # 取最接近的日期
            
            if isinstance(earnings_date, (datetime, pd.Timestamp)):
                 today = datetime.now().date()
                 e_date = earnings_date.date()
                 days = (e_date - today).days
                 # 只回傳未來的日期，若已過期回傳 999
                 return days if days >= 0 else 999
        return 999 
    except:
        return 999

@st.cache_data(ttl=600) # 10分鐘快取，避免重複抓取太慢
def calculate_v32_us(ticker):
    """計算美股 V32 分數 (核心算法)"""
    try:
        stock = yf.Ticker(ticker)
        # 抓 1 年數據以計算 200MA
        hist = stock.history(period="1y")
        if len(hist) < 200: return None
        
        # 基礎數據
        close = hist['Close']
        vol = hist['Volume']
        curr = close.iloc[-1]
        
        # MA 計算
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        
        # RVol (相對量能) - 這裡用 20 日均量做基準
        vol_ma20 = vol.rolling(20).mean().iloc[-1]
        curr_vol = vol.iloc[-1]
        rvol = curr_vol / vol_ma20 if vol_ma20 > 0 else 0
        
        # RSI 計算
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]

        # MACD 計算
        exp12 = close.ewm(span=12, adjust=False).mean()
        exp26 = close.ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_val = macd.iloc[-1]
        sig_val = signal.iloc[-1]
        
        # --- V32 評分邏輯 ---
        score = 60 # 基礎分
        
        # 1. 趨勢面 (40%)
        if curr > ma200: score += 10 # 牛市
        if ma50 > ma200: score += 10 # 多頭排列
        if curr > ma50: score += 10  # 站穩季線
        if curr > ma20: score += 10  # 短線強勢
        
        # 2. 量能面 (30%)
        if rvol > 1.2: score += 5
        if rvol > 1.5: score += 10
        if rvol > 2.0: score += 15 # 爆量攻擊
        
        # 3. 技術面 (30%)
        if 50 < rsi < 75: score += 10
        if macd_val > sig_val: score += 10
        if macd_val > 0: score += 10

        # 4. 取得財報風險
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

# ==========================================
# 3. 視覺化輔助函數
# ==========================================
def color_earnings(val):
    if not isinstance(val, (int, float)): return ''
    if val <= 5: return 'color: white; background-color: #d32f2f; font-weight: bold;' # 紅底 (危險)
    elif val <= 14: return 'color: black; background-color: #ffeb3b; font-weight: bold;' # 黃底 (警戒)
    return 'color: #1b5e20; font-weight: bold;' # 綠字 (安全)

def color_v32_score(val):
    if val >= 90: return 'color: #d32f2f; font-weight: bold;' # 極強
    if val >= 80: return 'color: #1565c0; font-weight: bold;' # 強
    return ''

def color_rvol(val):
    if val >= 2.0: return 'color: white; background-color: #b71c1c; font-weight: bold;' # 爆量
    if val >= 1.5: return 'color: white; background-color: #ef5350; font-weight: bold;' # 顯著量增
    if val >= 1.2: return 'background-color: #ffebee;' # 微量增
    return ''

# ==========================================
# 4. 主程式 APP
# ==========================================
def main():
    st.title("🦅 V32 美股戰情室")
    st.caption(f"美東時間: {get_us_time()}")
    
    # 1. 初始化: 讀取庫存 (只在第一次讀取)
    if 'holdings_df' not in st.session_state:
        st.session_state['holdings_df'] = load_holdings()

    # 2. 顯示大盤狀態
    market = get_market_status()
    if market:
        c1, c2 = st.columns([3, 1])
        with c1:
            st.info(f"{market['signal']} **S&P 500 狀態：{market['status']}**")
        with c2:
            st.metric("S&P 500", f"{market['price']:.0f}", f"MA200: {market['ma200']:.0f}")
        st.divider()

    # 3. 分頁設置
    tab_inv, tab_shield, tab_spear = st.tabs(["🏰 庫存堡壘", "🛡️ 穩健戰艦 (S&P)", "🚀 攻擊快艇 (Momentum)"])

    # === Tab 1: 庫存堡壘 ===
    with tab_inv:
        c_left, c_right = st.columns([2, 1])
        
        # --- 左側：庫存列表 ---
        with c_left:
            st.subheader("⚠️ 風險監控面板")
            
            if st.button("🔄 更新庫存狀態 (含報價)", type="primary"):
                if not st.session_state['holdings_df'].empty:
                    with st.spinner("🚀 同步美股報價與分析中..."):
                        display_data = []
                        # 逐一計算每檔庫存
                        for index, row in st.session_state['holdings_df'].iterrows():
                            # 為了求最新數據，這裡呼叫不使用 Cache 的邏輯 (或手動清除)
                            # 這裡直接用 calculate_v32_us
                            v32_data = calculate_v32_us(row['Code'])
                            
                            if v32_data:
                                curr_price = v32_data['即時價']
                                cost = float(row['Cost'])
                                shares = float(row['Shares'])
                                profit = (curr_price - cost) * shares
                                profit_pct = (curr_price - cost) / cost * 100
                                
                                # 簡易建議
                                advise = "🟢 續抱"
                                if v32_data['財報倒數'] <= 5: advise = "🔴 財報避險"
                                elif v32_data['V32總分'] < 60: advise = "🟡 轉弱觀察"
                                
                                display_data.append({
                                    '代號': row['Code'],
                                    '類型': row['Type'],
                                    '成本': cost,
                                    '即時價': curr_price,
                                    '損益($)': profit,
                                    '報酬率%': profit_pct,
                                    '財報倒數': v32_data['財報倒數'],
                                    'V32分': v32_data['V32總分'],
                                    '建議': advise
                                })
                        
                        st.session_state['display_inv'] = pd.DataFrame(display_data)
            
            # 顯示庫存表格
            if 'display_inv' in st.session_state and not st.session_state['display_inv'].empty:
                df_show = st.session_state['display_inv']
                
                # 總結算
                total_profit = df_show['損益($)'].sum()
                st.metric("總損益", f"${total_profit:,.0f}", delta=f"{total_profit:,.0f}")
                
                st.dataframe(
                    df_show.style.format({
                        '即時價': '{:.2f}', '損益($)': '{:+,.0f}', '報酬率%': '{:+.2f}%', 'V32分': '{:.0f}'
                    }).map(color_earnings, subset=['財報倒數'])
                      .map(color_v32_score, subset=['V32分']),
                    use_container_width=True, hide_index=True
                )
            else:
                if st.session_state['holdings_df'].empty:
                    st.info("目前無庫存，請在右側新增。")
                else:
                    st.info("請點擊上方按鈕進行更新。")

        # --- 右側：交易輸入區 ---
        with c_right:
            st.markdown("### 📝 交易登記")
            with st.form("add_stock_form"):
                col_a, col_b = st.columns(2)
                new_code = col_a.text_input("代號", placeholder="AAPL").upper().strip()
                new_type = col_b.selectbox("類型", ["🛡️ 穩健", "🚀 攻擊"])
                new_cost = col_a.number_input("成本價", min_value=0.0, step=0.1)
                new_shares = col_b.number_input("股數", min_value=1, step=1)
                submitted = st.form_submit_button("➕ 新增/加碼")
                
                if submitted and new_code:
                    df = st.session_state['holdings_df']
                    # 檢查是否已存在 (簡單處理：若存在則直接新增一筆新的，使用者可自行刪除舊的)
                    new_row = pd.DataFrame([{
                        'Code': new_code, 'Type': new_type, 
                        'Cost': new_cost, 'Shares': new_shares, 'Note': ''
                    }])
                    df = pd.concat([df, new_row], ignore_index=True)
                    st.session_state['holdings_df'] = df
                    save_holdings(df) # 存回 GitHub
                    st.rerun()

            st.markdown("---")
            with st.expander("🗑️ 刪除庫存"):
                if not st.session_state['holdings_df'].empty:
                    # 製作選單：代號 + 成本 (方便辨識)
                    options = st.session_state['holdings_df'].apply(lambda x: f"{x['Code']} (成本 {x['Cost']})", axis=1)
                    selected_option = st.selectbox("選擇要刪除的項目", options)
                    
                    if st.button("確認刪除"):
                        # 這裡的邏輯是刪除選到的那一列
                        idx_to_del = options[options == selected_option].index[0]
                        df = st.session_state['holdings_df'].drop(idx_to_del).reset_index(drop=True)
                        st.session_state['holdings_df'] = df
                        save_holdings(df)
                        st.rerun()

    # === Tab 2: 穩健戰艦 (S&P 500) ===
    with tab_shield:
        st.subheader("🛡️ 穩健戰艦掃描")
        st.caption("目標：S&P 500 成分股 | 站上 200MA | V32 > 70")
        
        # 預設觀察清單 (你可以隨時修改這裡)
        shield_list = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD', 'COST', 'BRK-B', 'JPM', 'UNH', 'LLY', 'AVGO', 'V']
        
        if st.button("🔎 掃描穩健池", key='btn_shield'):
            results = []
            progress = st.progress(0)
            status_text = st.empty()
            
            for i, ticker in enumerate(shield_list):
                status_text.text(f"Scanning {ticker}...")
                data = calculate_v32_us(ticker)
                
                # Shield 篩選標準：V32 >= 70
                if data and data['V32總分'] >= 70:
                    results.append(data)
                progress.progress((i+1)/len(shield_list))
            
            progress.empty()
            status_text.empty()
            
            if results:
                df_shield = pd.DataFrame(results)
                # 排序：分數高 -> 低
                df_shield = df_shield.sort_values('V32總分', ascending=False)
                
                st.dataframe(df_shield[['代號', '即時價', 'V32總分', 'RVol', '距200MA', 'RSI', '財報倒數']].style.format({
                    '即時價': '{:.2f}', 'V32總分': '{:.0f}', 'RVol': '{:.2f}x', '距200MA': '{:+.2f}%', 'RSI': '{:.0f}'
                }).background_gradient(subset=['V32總分'], cmap='Blues')
                  .map(color_earnings, subset=['財報倒數']), 
                use_container_width=True, hide_index=True)
            else:
                st.warning("目前無符合標準的穩健標的")

    # === Tab 3: 攻擊快艇 (Momentum) ===
    with tab_spear:
        st.subheader("🔥 攻擊快艇掃描")
        st.caption("目標：熱門成長股 | RVol 爆量 (>1.5) | V32 > 80")
        
        # 預設觀察清單 (妖股/熱門股)
        spear_list = ['PLTR', 'SOFI', 'MARA', 'COIN', 'GME', 'PATH', 'UPST', 'AI', 'DKNG', 'RBLX', 'AFRM', 'CVNA', 'RIOT', 'MSTR']
        
        if st.button("🔥 掃描攻擊池", key='btn_spear'):
            results = []
            progress = st.progress(0)
            status_text = st.empty()
            
            for i, ticker in enumerate(spear_list):
                status_text.text(f"Scanning {ticker}...")
                data = calculate_v32_us(ticker)
                
                # Spear 篩選標準：V32 >= 80 (更嚴格)
                # 這裡不強制濾掉低 RVol，因為要顯示出來讓你看它是死魚還是活魚
                if data and data['V32總分'] >= 80:
                    results.append(data)
                progress.progress((i+1)/len(spear_list))
            
            progress.empty()
            status_text.empty()
            
            if results:
                df_spear = pd.DataFrame(results)
                df_spear = df_spear.sort_values('RVol', ascending=False) # 攻擊型按量能排序
                
                st.dataframe(df_spear[['代號', '即時價', 'V32總分', 'RVol', 'RSI', '財報倒數']].style.format({
                    '即時價': '{:.2f}', 'V32總分': '{:.0f}', 'RVol': '{:.2f}x', 'RSI': '{:.0f}'
                }).map(color_rvol, subset=['RVol']) # 特殊量能顏色
                  .map(color_earnings, subset=['財報倒數']), 
                use_container_width=True, hide_index=True)
            else:
                st.warning("目前無符合標準的攻擊標的")

if __name__ == "__main__":
    main()
