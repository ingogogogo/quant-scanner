import pandas as pd
import yfinance as yf
import requests
import io
import warnings
import os
from datetime import datetime, timedelta
from fredapi import Fred
from collections import Counter

warnings.filterwarnings('ignore')

print("🚀 [1년 마스터 스캐너] 누적 데이터 엔진 및 유동성 추적 시작...")

# ==============================================================================
# 0. 🔑 FRED 공식 API 설정 (결측치 강제 보정 로직 추가)
# ==============================================================================
FRED_API_KEY = '7f64d6681ff75721a1135aa0488c5f4b'
try:
    print("⏳ 거시 유동성(FRED) 데이터 다운로드 중...")
    fred = Fred(api_key=FRED_API_KEY)
    fred_start = (datetime.today() - timedelta(days=600)).strftime('%Y-%m-%d')
    fred_end = datetime.today().strftime('%Y-%m-%d')
    
    walcl = fred.get_series('WALCL', observation_start=fred_start, observation_end=fred_end)
    wtregen = fred.get_series('WTREGEN', observation_start=fred_start, observation_end=fred_end)
    rrp = fred.get_series('RRPONTSYD', observation_start=fred_start, observation_end=fred_end)
    
    macro_df = pd.DataFrame({'WALCL': walcl, 'WTREGEN': wtregen, 'RRP': rrp})
    # 🚨 [수정 완료] 수요일/일일 발표 주기가 달라서 생기는 빈칸을 가장 최근 데이터로 강력하게 채움
    macro_df = macro_df.ffill().dropna()
    print(f"✅ FRED 데이터 로딩 완벽 성공! (데이터 수: {len(macro_df)}일치)")
except Exception as e:
    print(f"❌ FRED 데이터 로딩 실패: {e}")
    macro_df = pd.DataFrame()

# ==============================================================================
# 1. 지수별 티커 수집
# ==============================================================================
indices = {'S&P 500': 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'S&P MidCap 400': 'https://en.wikipedia.org/wiki/List_of_S%26P_400_companies'}
def get_tickers():
    td = {}
    for n, u in indices.items():
        try:
            df = pd.read_html(io.StringIO(requests.get(u, headers={'User-Agent': 'Mozilla/5.0'}).text))[0]
            tc = next((c for c in df.columns if 'symbol' in str(c).lower() or 'ticker' in str(c).lower()), None)
            sc = next((c for c in df.columns if 'sub-industry' in str(c).lower() or 'sector' in str(c).lower()), None)
            if tc:
                for _, r in df.iterrows(): td[str(r[tc]).replace('.', '-')] = {'index': n, 'industry': str(r[sc]) if sc else 'Unknown'}
        except: continue
    
    custom_vip_stocks = {
        'WDC': 'Computer Hardware & Storage', 'MU': 'Semiconductors', 'NVDA': 'Semiconductors', 'TSM': 'Semiconductors',
        'AMAT': 'Semiconductor Equipment', 'RMBS': 'Semiconductors', 'SMTC': 'Semiconductors', 'AXTI': 'Semiconductor Materials',
        'YOU': 'Software & IT Services', 'NE': 'Oil & Gas Drilling', 'KNSA': 'Biotechnology', 'RIG': 'Oil & Gas Drilling',
        'APA': 'Oil & Gas E&P', 'DAR': 'Agricultural Products', 'AHG': 'Real Estate (REITs)', 'FTI': 'Oil & Gas Equipment & Services',
        'BTE': 'Oil & Gas E&P', 'ADEA': 'Software & IT Services', 'OUT': 'Advertising & Media', 'TIMB': 'Telecommunication Services',
        'NYT': 'Publishing & Media', 'DBRG': 'Real Estate (REITs)', 'SBS': 'Water Utilities', 'AVGO': 'Semiconductors', 'AMD': 'Semiconductors'
    }
    for vip_ticker, vip_theme in custom_vip_stocks.items():
        td[vip_ticker] = {'index': '🔥 MY VIP WATCHLIST', 'industry': vip_theme}
    return td

ticker_info = get_tickers()
tickers = list(ticker_info.keys())

# ==============================================================================
# 2. 주가 데이터 다운로드
# ==============================================================================
start_history = (datetime.today() - timedelta(days=600)).strftime('%Y-%m-%d')
end_history_safe = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
print(f"📥 주가 데이터 다운로드 중... (진행률 확인, 약 1~3분 소요)")
data = yf.download(tickers + ['^GSPC', '^RUT'], start=start_history, end=end_history_safe, progress=True)

close_data = data['Close']
vol_data = data['Volume']
mkt_gspc = close_data['^GSPC']

# 🚨 결과물 엑셀에는 딱 '최근 1년치(365일)'만 담기 위한 타겟 날짜 설정
target_start_dt = datetime.today() - timedelta(days=365)
all_trading_days = close_data.index.unique().sort_values()

# ==============================================================================
# 3. 전체 거래일 루프 (과거 데이터를 생략하지 않고 100% 누적 계산!)
# ==============================================================================
summary_stats, all_caught_stocks = [], []
ticker_cumulative_counts = {}
streak_counter, last_state = 0, None
mkt_cache = {}

def get_mkt_data(d):
    d_str = d.strftime('%Y-%m-%d')
    if d_str in mkt_cache: return mkt_cache[d_str]
    b_start, b1_start = (d - timedelta(days=185)).strftime('%Y-%m-%d'), (d - timedelta(days=32)).strftime('%Y-%m-%d')
    m_series = mkt_gspc.loc[:d_str]
    m_6m = m_series.loc[b_start:].pct_change().dropna()
    m_v_6m = m_6m.var() if len(m_6m) > 0 else 0
    m_1m = m_series.loc[b1_start:].pct_change().dropna()
    m_v_1m = m_1m.var() if len(m_1m) > 0 else 0
    mkt_cache[d_str] = (m_6m, m_v_6m, m_1m, m_v_1m, b_start, b1_start)
    return mkt_cache[d_str]

for i, trade_date in enumerate(all_trading_days):
    date_str = trade_date.strftime('%Y-%m-%d')
    if trade_date >= target_start_dt and (i % 20 == 0): 
        print(f"  ... 🎯 [{date_str}] 타겟 거래일 종목 스캔 및 엑셀 기록 중 ...")
    
    # [거시 유동성 계산 및 연속성 추적]
    net_bal_str, net_str, streak_text = "-", "-", "-"
    fed_bal_str, gov_bal_str = "-", "-"
    current_state = "flat"
    
    if not macro_df.empty:
        try:
            date_dt = pd.to_datetime(date_str)
            idx = macro_df.index.get_indexer([date_dt], method='ffill')[0]
            past_idx = macro_df.index.get_indexer([date_dt - timedelta(days=7)], method='ffill')[0]
            if idx != -1 and past_idx != -1:
                f_B = macro_df['WALCL'].iloc[idx] / 1000
                g_B = macro_df['WTREGEN'].iloc[idx] + macro_df['RRP'].iloc[idx]
                net_B = f_B - g_B
                net_change_B = (macro_df['WALCL'].iloc[idx] - macro_df['WALCL'].iloc[past_idx])/1000 + (macro_df['WTREGEN'].iloc[past_idx] + macro_df['RRP'].iloc[past_idx]) - (macro_df['WTREGEN'].iloc[idx] + macro_df['RRP'].iloc[idx])
                
                net_bal_str = f"${net_B:,.1f}B"
                fed_bal_str = f"${f_B:,.1f}B"
                gov_bal_str = f"${g_B:,.1f}B"
                
                if net_change_B > 5.0:
                    net_str, current_state = f"🔥증가 (+${net_change_B:,.1f}B)", "up"
                elif net_change_B < -5.0:
                    net_str, current_state = f"❄️감소 (${net_change_B:,.1f}B)", "down"
                else:
                    net_str, current_state = f"➖보합 (${net_change_B:+,.1f}B)", "flat"
                
                if current_state == last_state and current_state != "flat":
                    streak_counter += 1
                else:
                    streak_counter, last_state = 1, current_state
                
                weeks = streak_counter // 5
                if weeks >= 1:
                    streak_text = f"{weeks}주 연속 {'증가' if current_state=='up' else '감소'}"
                else:
                    streak_text = "전환점"
        except: pass

    # 🚨 [수정 완료] 과거 데이터도 '건너뛰기(Skip)' 없이 무조건 계산하여 누적 횟수를 정확히 보존합니다.
    day_portfolio = []
    for t in tickers:
        if t not in close_data.columns or t in ['^GSPC', '^RUT']: continue
        series = close_data[t].dropna()
        if date_str not in series.index: continue
        s_upto = series.loc[:date_str]
        if len(s_upto) < 100: continue
        l3 = s_upto.index[-3:]
        if len(l3) < 3: continue

        passes = True
        fm = {}
        for d in reversed(l3):
            d_s = d.strftime('%Y-%m-%d')
            s_d = series.loc[:d_s]
            p = s_d.iloc[-1]
            if not (p > s_d.tail(50).mean() and p > s_d.tail(100).mean()): passes = False; break
            
            try:
                mr = (mkt_gspc.loc[:d_s].iloc[-1] / mkt_gspc.loc[:d_s].iloc[-2]) - 1
                sr = (s_d.iloc[-1] / s_d.iloc[-2]) - 1
            except: mr, sr = 0, 0
            
            is_m = (mr > 0 and sr > (mr * 3) and sr > 0.025) or (mr <= 0 and sr > 0.03)
            hp = s_d.loc[(d - timedelta(days=365)).strftime('%Y-%m-%d'):].max()
            px = ((p / hp) - 1) * 100
            if px > -2.0 or px < -20.0: passes = False; break
            
            v_d = vol_data[t].dropna().loc[:d_s]
            av60 = v_d.tail(60).mean()
            vr = v_d.tail(5).max() / av60 if av60 else 0
            
            m6, mv6, m1, mv1, bst, b1st = get_mkt_data(d)
            r6 = s_d.loc[bst:].pct_change().dropna()
            if len(r6) < 50: passes = False; break
            
            b6 = r6.cov(m6) / mv6 if mv6 else 0
            b1 = s_d.loc[b1st:].pct_change().dropna().cov(m1) / mv1 if mv1 else 0
            if b1 < 0.8: passes = False; break
            
            sec = any(s in str(ticker_info[t]['industry']) for s in ['Technology', 'Semiconductor', 'Software', 'Computer', 'Communication'])
            if sec:
                if b6 < 1.5: passes = False; break
                if not is_m and vr < 1.1: passes = False; break
            else:
                if b6 < 2.2: passes = False; break
                if not is_m and vr < 1.8: passes = False; break
                
            if d == l3[-1]: fm = {'p': p, 'b1': b1, 'b6': b6, 'px': px, 'vr': vr, 'is_m': is_m}

        if passes:
            # ✅ 누적 포착 횟수 증가 (과거부터 스노우볼처럼 쌓임)
            ticker_cumulative_counts[t] = ticker_cumulative_counts.get(t, 0) + 1
            cnt, b1, vr = ticker_cumulative_counts[t], fm['b1'], fm['vr']
            
            grade = ""
            if cnt >= 19 and b1 >= 2.7: grade = "💎 초거대 대장주 (3개월 농사 종목)"
            elif cnt <= 2 and vr > 2.0: grade = "⚠️ 설거지 회피 (거래량 과열, 매수 보류)"
            elif cnt <= 2: grade = "🔥 1. 초기 포착 (수익률 158%~)"
            elif cnt >= 10: grade = "🛡️ 2. 안전 제일주의 (수익률 65%~)"
            else: grade = "🏆 3. 황금 밸런스 (승률 92% 이상 대장주!)"
            
            stock_row = {
                '포착일자': date_str, '티커': t, '누적 포착횟수': f"{cnt}회", 'AI 매매 등급': grade,
                '상세 테마': ('🚀[초강세] ' if fm['is_m'] else '') + ticker_info[t]['industry'],
                '소속 지수': ticker_info[t]['index'], '매수가': round(fm['p'], 2), '현재가': round(series.iloc[-1], 2),
                '단기수익률(%)': round(((series.iloc[-1] / fm['p']) - 1) * 100, 2), '1M 베타': round(b1, 2), '6M 베타': round(fm['b6'], 2),
                '전고점 대비(%)': round(fm['px'], 2), '최대거래량(5일)': round(vr, 2)
            }
            # 일일 포트폴리오에는 항상 기록
            day_portfolio.append(stock_row)
            
            # ✅ 결과 엑셀에는 '최근 1년 치' 데이터만 깔끔하게 저장
            if trade_date >= target_start_dt:
                all_caught_stocks.append(stock_row)

    # [요약 통계 저장 - 최근 1년 치만 저장]
    if trade_date >= target_start_dt:
        sig = "❌ 매수 금지" if len(day_portfolio) >= 15 else "⚠️ 휩소 경계" if "❄️" in net_str and len(day_portfolio) >= 8 else "🎯 강력 매수" if "🔥" in net_str and 1 <= len(day_portfolio) <= 5 else "👀 개별주 장세" if len(day_portfolio) > 0 else "💤 신호 없음"
        sum_row = {
            '매수 날짜': date_str, '유동성 연속성': streak_text, '유동성 증감(7일)': net_str, 
            '총 유동성 잔고': net_bal_str, '전략 시그널': sig, 
            '연준 잔고(WALCL)': fed_bal_str, '재무부 잔고(TGA+RRP)': gov_bal_str, '타격수': len(day_portfolio)
        }
        if day_portfolio:
            top_t, top_c = Counter([item['상세 테마'].replace('🚀[초강세] ', '') for item in day_portfolio]).most_common(1)[0]
            sum_row.update({'주도 테마': f"{top_t} ({top_c})", '평균수익(%)': round(pd.DataFrame(day_portfolio)['단기수익률(%)'].mean(), 2)})
        else: 
            sum_row.update({'주도 테마': '-', '평균수익(%)': 0.0})
        summary_stats.append(sum_row)

# ==============================================================================
# 💾 엑셀 작성
# ==============================================================================
file_name = '1Year_Master_Scanner_Final.xlsx'
instruction = "(당일종가 50% 매수, 3일뒤 종가 50%매수, -9.5%도달시 손절)"
summary_df, all_stocks_df = pd.DataFrame(summary_stats), pd.DataFrame(all_caught_stocks)

if not all_stocks_df.empty:
    all_stocks_df['일일 베타순위'] = all_stocks_df.groupby('포착일자')['1M 베타'].rank(method='min', ascending=False).astype(int).astype(str) + "위"
    cols = all_stocks_df.columns.tolist()
    cols.insert(cols.index('1M 베타'), cols.pop(cols.index('일일 베타순위')))
    all_stocks_df = all_stocks_df[cols]

with pd.ExcelWriter(file_name, engine='xlsxwriter') as writer:
    summary_df.to_excel(writer, sheet_name='📊 1년 시그널 요약', index=False, startrow=1)
    all_stocks_df.to_excel(writer, sheet_name='🎯 전체 포착 종목', index=False, startrow=1)
    
    wb = writer.book
    ws1 = writer.sheets['📊 1년 시그널 요약']
    ws2 = writer.sheets['🎯 전체 포착 종목']
    
    fmt_inst = wb.add_format({'bold': True, 'font_color': 'blue'})
    ws1.write('A1', instruction, fmt_inst)
    ws2.write('A1', instruction, fmt_inst)
    
    ws1.set_column('A:B', 15); ws1.set_column('C:C', 26); ws1.set_column('D:G', 20); ws1.set_column('H:K', 16)
    
    f_red = wb.add_format({'font_color': '#FF0000', 'bold': True})
    f_blue = wb.add_format({'font_color': '#0000FF', 'bold': True})
    f_mblue = wb.add_format({'bg_color': '#00008B', 'font_color': '#FFFFFF', 'bold': True})
    
    ws1.conditional_format('C3:C5000', {'type': 'text', 'criteria': 'containing', 'value': '🔥', 'format': f_red})
    ws1.conditional_format('C3:C5000', {'type': 'text', 'criteria': 'containing', 'value': '❄️', 'format': f_blue})
    ws1.conditional_format('B3:B5000', {'type': 'formula', 'criteria': 'OR(ISNUMBER(SEARCH("3주",B3)),ISNUMBER(SEARCH("4주",B3)),ISNUMBER(SEARCH("5주",B3)),ISNUMBER(SEARCH("6주",B3)))', 'format': f_mblue})
    
    ws2.freeze_panes(2, 1)
    ws2.set_column('A:A', 14); ws2.set_column('B:C', 12); ws2.set_column('D:D', 45); ws2.set_column('E:E', 30); ws2.set_column('F:N', 12)
    
    f_good = wb.add_format({'font_color': '#006400', 'bold': True})
    f_bad = wb.add_format({'font_color': '#8B0000'})
    f_warn = wb.add_format({'font_color': '#B71C1C', 'bold': True, 'bg_color': '#FFCDD2'}) 
    f_best = wb.add_format({'font_color': '#1A237E', 'bold': True, 'bg_color': '#C5CAE9'}) 
    f_mega = wb.add_format({'bg_color': '#1C2833', 'font_color': '#FFD700', 'bold': True})
    
    ws2.conditional_format('I3:I5000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': f_good})
    ws2.conditional_format('I3:I5000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': f_bad})
    ws2.conditional_format('D3:D5000', {'type': 'text', 'criteria': 'containing', 'value': '설거지', 'format': f_warn})
    ws2.conditional_format('D3:D5000', {'type': 'text', 'criteria': 'containing', 'value': '🏆', 'format': f_best})
    ws2.conditional_format('D3:D5000', {'type': 'text', 'criteria': 'containing', 'value': '💎', 'format': f_mega})

    pastel_colors = ['#F9EBEA', '#EBF5FB', '#E8F8F5', '#FEF9E7', '#F4ECF7']
    unique_dates = all_stocks_df['포착일자'].unique() if not all_stocks_df.empty else []
    for k, date_val in enumerate(unique_dates):
        fmt = wb.add_format({'bg_color': pastel_colors[k % len(pastel_colors)]})
        ws2.conditional_format('A3:N5000', {'type': 'formula', 'criteria': f'=$A3="{date_val}"', 'format': fmt})

print(f"✅ 1년 백테스트 파일 생성 완료!")

# ==============================================================================
# 📲 깃허브 자동화 (텔레그램 발송) 로직
# ==============================================================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if TELEGRAM_TOKEN and CHAT_ID:
    print("📲 텔레그램으로 엑셀 결과를 전송합니다...")
    today_str = datetime.today().strftime('%Y-%m-%d')
    msg = f"🚀 [{today_str}] 1년 마스터 스캐너 분석 결과\n\n오늘의 대장주 판독 및 유동성 분석이 완료되었습니다. 첨부된 엑셀 파일을 확인하세요."
    
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={'chat_id': CHAT_ID, 'text': msg})
        with open(file_name, 'rb') as f:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument", data={'chat_id': CHAT_ID}, files={'document': f})
        print("✅ 텔레그램 전송 완벽 성공!")
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")
else:
    print("⚠️ 텔레그램 토큰이 설정되지 않아 파일 전송은 생략합니다. (깃허브 세팅을 진행해 주세요!)")
