import sqlite3
import pandas as pd
from pybaseball import statcast
import pybaseball
import datetime
import time
import os

# 開啟緩存，減少重複抓取負擔
pybaseball.cache.enable()

def create_database():
    db_file = "baseball_data.db"
    
    # 💡 專業建議：如果你發現舊資料沒名字或沒出局標記，建議刪除原有的 baseball_data.db 重新執行
    conn = sqlite3.connect(db_file)
    start_year = 2015
    current_year = datetime.date.today().year
    
    print(f"🚀 開始建立 2015-{current_year} 棒球資料庫 (含姓名、出局標記與篩選器索引)...")

    for year in range(start_year, current_year + 1):
        for month in range(3, 12):
            sub_periods = [
                (f"{year}-{month:02d}-01", f"{year}-{month:02d}-15"),
                (f"{year}-{month:02d}-16", f"{year}-{month:02d}-28")
            ]
            
            for start_d, end_d in sub_periods:
                if month == 3 and "01" in start_d: start_d = f"{year}-03-20"
                if start_d > datetime.date.today().strftime('%Y-%m-%d'): continue

                try:
                    # 檢查機制
                    check_query = f"SELECT count(*) FROM pitches WHERE game_date BETWEEN '{start_d}' AND '{end_d}'"
                    try:
                        count = pd.read_sql(check_query, conn).iloc[0, 0]
                        if count > 0:
                            print(f"⏩ 跳過 {start_d} (資料庫已有 {count} 筆)")
                            continue
                    except:
                        pass

                    print(f"📡 正在抓取 {start_d} ~ {end_d}...")
                    df = statcast(start_d, end_d)
                    
                    if df is None or df.empty:
                        continue

                    # 投手角色判斷
                    starters = df[df['inning'] == 1][['game_pk', 'pitcher']].drop_duplicates()
                    starters['pitcher_role_new'] = 'SP'
                    df = df.merge(starters, on=['game_pk', 'pitcher'], how='left')
                    df['pitcher_role'] = df['pitcher_role_new'].fillna('RP')

                    # 壘包處理 (轉為 0/1)
                    for col in ['on_1b', 'on_2b', 'on_3b']:
                        df[col] = df[col].notna().astype(int)

                    # 🎯 【核心欄位】：包含視覺化、統計、與搜尋所需的 ID/姓名
                    # balls, strikes (對應 COUNT), pitch_type (對應 PITCH TYPE) 已經在裡面了！
                    keep_cols = [
                        'game_date', 'pitch_type', 'balls', 'strikes', 'stand', 'p_throws', 
                        'on_1b', 'on_2b', 'on_3b', 'pitcher_role', 'inning',
                        'release_speed', 'plate_x', 'plate_z', 'description', 'type', 
                        'zone', 'player_name', 'pitcher', 'batter', 'events'
                    ]
                    
                    # 只選取存在的欄位
                    df_to_save = df[[c for c in keep_cols if c in df.columns]].copy()
                    
                    # 確保 player_name 沒名字時給 Unknown，避免 API 報錯
                    if 'player_name' in df_to_save.columns:
                        df_to_save['player_name'] = df_to_save['player_name'].fillna('Unknown')

                    # ✨ 【新增 1】加入 is_out 出局標記 (解決九宮格 Out% = 0 的問題)
                    out_events = [
                        'field_out', 'strikeout', 'force_out', 'grounded_into_double_play', 
                        'fielders_choice', 'fielders_choice_out', 'double_play', 
                        'sac_fly', 'sac_bunt', 'strikeout_double_play'
                    ]
                    if 'events' in df_to_save.columns:
                        df_to_save['is_out'] = df_to_save['events'].isin(out_events).astype(int)
                    else:
                        df_to_save['is_out'] = 0

                    # ✨ 【新增 2】把對應 COUNT 篩選器的 balls 和 strikes 加入空值排除名單
                    # 避免前端傳入 0-0 卻因為資料庫有空值而報錯
                    df_to_save = df_to_save.dropna(subset=['pitch_type', 'plate_x', 'plate_z', 'balls', 'strikes'])

                    # 強制將球數轉為整數
                    df_to_save['balls'] = df_to_save['balls'].astype(int)
                    df_to_save['strikes'] = df_to_save['strikes'].astype(int)

                    # 存入資料庫
                    df_to_save.to_sql("pitches", conn, if_exists="append", index=False)
                    print(f"✅ 成功儲存 {len(df_to_save)} 筆 (年份: {year})")
                    
                    # ⚡ 每一批寫入後建立/更新索引
                    # ✨ 【新增 3】幫篩選器的變數加上索引，點擊篩選時載入會變極快
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_pname ON pitches(player_name)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_gdate ON pitches(game_date)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_ptype ON pitches(pitch_type)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_count ON pitches(balls, strikes)")
                    
                    time.sleep(1)

                except KeyboardInterrupt:
                    print("\n🛑 手動停止。正在關閉資料庫...")
                    conn.close()
                    return
                except Exception as e:
                    print(f"⚠️ {start_d} 失敗: {e}")
                    time.sleep(5)

    conn.close()
    print("🎉 資料庫補完完畢！所有球員名字、出局標記與篩選器資料已就緒。")

if __name__ == "__main__":
    create_database()