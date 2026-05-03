import sqlite3
import pandas as pd
import os
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pybaseball import playerid_reverse_lookup
import uvicorn

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "baseball_data.db") 

batter_name_map = {}
TABLE_NAME = "pitches" 

@app.on_event("startup")
async def startup_event():
    global batter_name_map, TABLE_NAME

    # 你的 Google Drive 檔案 ID
    FILE_ID = "1SAcDhIJhUwNxUtta5NibiLmqg8NQRJlM"
    
    if not os.path.exists(DB_PATH):
        print("正在從雲端下載大型資料庫 (1.15GB)，請稍候...")
        try:
            # 使用 Session 處理 Google Drive 的大檔案確認機制
            session = requests.Session()
            download_url = "https://docs.google.com/uc?export=download"
            
            # 第一步：嘗試獲取下載頁面，並從 cookie 中抓取確認 token
            response = session.get(download_url, params={'id': FILE_ID}, stream=True)
            token = None
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    token = value
                    break
            
            # 第二步：如果抓到 token，帶著 token 正式下載；否則直接下載
            params = {'id': FILE_ID}
            if token:
                params['confirm'] = token
                
            response = session.get(download_url, params=params, stream=True)
            
            # 開始寫入檔案
            with open(DB_PATH, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768): # 加大 chunk_size 加快速度
                    if chunk:
                        f.write(chunk)
            print("下載完成！")
            
        except Exception as e:
            print(f"下載失敗: {e}")
            return

    # --- 以下原本的邏輯完全不動 ---
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        if "pitches" in tables: TABLE_NAME = "pitches"
        elif tables: TABLE_NAME = tables[0]

        u_ids = pd.read_sql(f"SELECT DISTINCT batter FROM {TABLE_NAME} WHERE batter IS NOT NULL", conn)['batter'].tolist()
        conn.close()
        if u_ids:
            lookup_df = playerid_reverse_lookup(u_ids, key_type='mlbam')
            for _, row in lookup_df.iterrows():
                batter_name_map[str(row['key_mlbam'])] = f"{row['name_last'].title()}, {row['name_first'].title()}"
    except Exception as e:
        print(f"啟動出錯: {e}")
@app.get("/api/batters")
async def get_batters():
    return sorted([{"id": k, "name": v} for k, v in batter_name_map.items()], key=lambda x: x['name'])

@app.get("/api/pitchers")
async def get_pitchers():
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(f"SELECT DISTINCT pitcher, player_name FROM {TABLE_NAME} WHERE player_name IS NOT NULL", conn)
        conn.close()
        return [{"id": str(int(row['pitcher'])), "name": row['player_name']} for _, row in df.iterrows()]
    except:
        return []

@app.get("/api/pitches")
async def get_pitches(
    year: str = None, 
    pitcherId: str = None, 
    batterId: str = None, 
    pitcherRole: str = "All",
    zone: str = None,
    pitchType: str = None,  # ⚾ 新增：接收球種
    balls: str = None,      # ⚾ 新增：接收壞球數
    strikes: str = None     # ⚾ 新增：接收好球數
):
    try:
        y = str(year).strip() if year else "ALL"
        p_id = str(pitcherId).strip() if pitcherId else ""
        b_id = str(batterId).strip() if batterId else ""
        role = str(pitcherRole).strip() if pitcherRole else "All"
        z = str(zone).strip() if zone else ""
        pt = str(pitchType).strip() if pitchType else ""
        b = str(balls).strip() if balls else ""
        s = str(strikes).strip() if strikes else ""

        # 定義哪些字串代表「空值」
        null_vals = ["", "none", "null", "undefined", "all"]

        if p_id.lower() in null_vals and b_id.lower() in null_vals:
            return []

        conn = sqlite3.connect(DB_PATH)
        conds = []
        
        # 1. 基礎篩選
        if y.upper() != "ALL":
            conds.append(f"substr(game_date, 1, 4) = '{y}'")
        if p_id.lower() not in null_vals and p_id != "0":
            conds.append(f"pitcher = {p_id}")
        if b_id.lower() not in null_vals and b_id != "0":
            conds.append(f"batter = {b_id}")
        if role.lower() not in null_vals:
            conds.append(f"pitcher_role = '{role}'")
            
        # 2. 九宮格 Zone 篩選
        if z and z.lower() not in null_vals:
            valid_zones = [int(x) for x in z.split(',') if x.strip().isdigit()]
            if valid_zones:
                zones_str = ", ".join(map(str, valid_zones))
                conds.append(f"zone IN ({zones_str})")

        # 3. ⚾ 球種篩選 (支援多選，例如 'FF,SL')
        if pt and pt.lower() not in null_vals:
            valid_pts = [f"'{x.strip()}'" for x in pt.split(',') if x.strip()]
            if valid_pts:
                pt_str = ", ".join(valid_pts)
                conds.append(f"pitch_type IN ({pt_str})")

        # 4. ⚾ 球數篩選 (注意：0是合法的球數，所以不能擋掉 "0")
        if b and b.lower() not in null_vals:
            conds.append(f"balls = {b}")
        if s and s.lower() not in null_vals:
            conds.append(f"strikes = {s}")
        
        # 組裝 SQL
        where = " WHERE " + " AND ".join(conds) if conds else ""
        query = f"SELECT * FROM {TABLE_NAME}{where} ORDER BY game_date DESC"
        
        # 你可以看終端機印出的這行，確認有沒有成功加上條件！
        print(f"DEBUG SQL: {query}")
        
        df = pd.read_sql(query, conn)
        conn.close()

        if df.empty:
            return []

        col_map = {
            'pitch_type': 'pitchType', 
            'release_speed': 'speed', 
            'plate_x': 'plateX', 
            'plate_z': 'plateZ',
            'is_out': 'isOut'
        }
        for old, new in col_map.items():
            if old in df.columns:
                df[new] = df[old]
            
        # 清洗 NaN
        records = df.to_dict(orient='records')
        return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in records]

    except Exception as e:
        print(f"❌ API 錯誤: {e}")
        return []
    
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)