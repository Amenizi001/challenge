import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import time
import gspread

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

JST = ZoneInfo("Asia/Tokyo")

# --- UI最適化CSS ---
st.markdown("""
<style>
    /* ---------------------------------------------------
       ★ 3列グリッド（st.columns(3)）の中にあるボタンだけを狙って「特大（35px）」にする
    ---------------------------------------------------- */
    div[data-testid="stHorizontalBlock"] > div:first-child:nth-last-child(3) div.stButton > button,
    div[data-testid="stHorizontalBlock"] > div:first-child:nth-last-child(3) ~ div div.stButton > button {
        padding: 15px 20px !important; 
        height: auto !important; 
    }
    div[data-testid="stHorizontalBlock"] > div:first-child:nth-last-child(3) div.stButton > button p,
    div[data-testid="stHorizontalBlock"] > div:first-child:nth-last-child(3) ~ div div.stButton > button p {
        font-size: 35px !important; 
        font-weight: bold !important; 
        margin: 0 !important;
    }
    
    /* ---------------------------------------------------
       レイアウト調整用設定
    ---------------------------------------------------- */
    .title-box div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
    }
    .title-box div[data-testid="column"]:nth-child(1) {
        width: 70% !important; flex: 1 1 70% !important; min-width: 70% !important;
    }
    .title-box div[data-testid="column"]:nth-child(2) {
        width: 30% !important; flex: 1 1 30% !important; min-width: 30% !important;
        text-align: right;
    }
    .grid-box div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 6px !important;
    }
    .grid-box div[data-testid="column"] {
        width: calc(33.333% - 4px) !important; flex: 1 1 calc(33.333% - 4px) !important;
        min-width: calc(33.333% - 4px) !important; max-width: calc(33.333% - 4px) !important;
    }
    .finish-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px;
        padding: 10px 8px; margin-bottom: 6px; display: flex; justify-content: space-between;
        align-items: center; width: 100%; box-sizing: border-box;
    }
    .finish-no { font-weight: bold; color: #212529; font-size: 1.8rem; }
    .finish-time { color: #0f5132; font-weight: bold; font-size: 1.05rem; }
    .finish-clock { color: #6c757d; font-size: 0.95rem; }
    .dnf-card {
        background-color: #fff3cd; border: 1px solid #ffe69c; border-radius: 6px;
        padding: 10px 8px; margin-bottom: 6px; display: flex; justify-content: space-between;
        align-items: center; color: #664d03; font-weight: bold; font-size: 1.8rem;
        width: 100%; box-sizing: border-box;
    }
</style>
""", unsafe_allow_html=True)

def check_password():
    query_auth = st.query_params.get("auth")
    if query_auth == st.secrets["app_password"]: return True
    def password_entered():
        if st.session_state["app_pwd"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.query_params["auth"] = st.secrets["app_password"]
            del st.session_state["app_pwd"]
        else:
            st.session_state["password_correct"] = False
    if st.session_state.get("password_correct", False): return True
    st.text_input("アプリ利用パスワード", type="password", on_change=password_entered, key="app_pwd")
    if st.session_state.get("password_correct") is False: st.error("パスワードが正しくありません")
    return False

if not check_password(): st.stop()

if "local_updates" not in st.session_state: st.session_state.local_updates = {}
if "last_valid_df" not in st.session_state: st.session_state.last_valid_df = None

@st.cache_resource(show_spinner=False)
def get_global_sync_manager(): return {"last_read_time": 0.0}
global_sync = get_global_sync_manager()

@st.cache_resource(show_spinner=False)
def get_gspread_client():
    creds_dict = dict(st.secrets.connections.gsheets)
    url = creds_dict.pop("spreadsheet", None)
    if url is None:
        url = st.secrets.connections.gsheets.spreadsheet
    client = gspread.service_account_from_dict(creds_dict)
    return client, url

def get_worksheet():
    client, url = get_gspread_client()
    return client.open_by_url(url).worksheet("Data")

def update_start_cell(no: int, checked: bool):
    ws = get_worksheet()
    ws.update_cell(no + 1, 2, checked)
    return True

def update_dns_cells(no: int, dns: bool):
    ws = get_worksheet()
    ws.update_cell(no + 1, 2, False)
    ws.update_cell(no + 1, 6, dns)
    return True

def update_finish_cells(no: int, checked: bool, time_str: str):
    ws = get_worksheet()
    ws.update(range_name=f"C{no + 1}:D{no + 1}", values=[[checked, time_str]])
    return True

def update_dnf_cells(no: int, dnf: bool, finish_check: bool, time_str: str):
    ws = get_worksheet()
    ws.update(range_name=f"C{no + 1}:E{no + 1}", values=[[finish_check, time_str, dnf]])
    return True

def update_setting_cell(key: str, value: str):
    ws = get_worksheet()
    headers = ws.row_values(1)
    key_col_idx = headers.index('Key') + 1 if 'Key' in headers else 7
    val_col_idx = key_col_idx + 1
    keys = ws.col_values(key_col_idx)
    if key in keys:
        row_idx = keys.index(key) + 1
        ws.update_cell(row_idx, val_col_idx, str(value))
    else:
        next_row = len(keys) + 1
        ws.update_cell(next_row, key_col_idx, key)
        ws.update_cell(next_row, val_col_idx, str(value))
    return True

@st.cache_data(ttl=15, show_spinner=False)
def load_data():
    ws = get_worksheet()
    data = ws.get_all_values() 
    if not data or len(data) < 2:
        raise ValueError("データが取得できませんでした")
    headers = data[0]
    df = pd.DataFrame(data[1:], columns=headers)
    if 'No' in df.columns: 
        df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    def str_to_bool(val):
        return str(val).strip().upper() == 'TRUE'
    df['Start_Check'] = df['Start_Check'].apply(str_to_bool)
    df['Finish_Check'] = df['Finish_Check'].apply(str_to_bool)
    df['DNF'] = df['DNF'].apply(str_to_bool)
    df['DNS'] = df['DNS'].apply(str_to_bool)
    df['Finish_Check_Time'] = df['Finish_Check_Time'].fillna("").astype(str)
    df['Key'] = df['Key'].fillna("").astype(str).str.strip()
    df['Value'] = df['Value'].fillna("").astype(str).str.strip()
    global_sync["last_read_time"] = time.time()
    return df

api_limit_mode = False
try:
    df = load_data()
    st.session_state.last_valid_df = df.copy()
except Exception:
    if st.session_state.last_valid_df is not None:
        df = st.session_state.last_valid_df.copy()
        api_limit_mode = True
    else:
        st.error("⚠️ 読込エラー。約1分待って再読み込みしてください。")
        st.stop()

settings_dict = {k: v for k, v in zip(df['Key'], df['Value']) if k != ""}
finish_enabled = str(settings_dict.get('finish_enabled', 'False')).strip().lower() == 'true'

start_time_str = str(settings_dict.get('start_time', '')).lstrip("'").strip()
if start_time_str and start_time_str.lower() != 'nan':
    try:
        start_time_val = datetime.datetime.strptime(start_time_str[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
    except Exception:
        start_time_val = None
else:
    start_time_val = None

def parse_time(time_str, start_time_val):
    """ ゴール時刻文字列から datetime オブジェクトをパースする """
    if not time_str or str(time_str).lower() == "nan": return None
    time_str = str(time_str).lstrip("'").strip()
    if len(time_str) >= 19:
        try:
            return datetime.datetime.strptime(time_str[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
        except: return None
    else:
        try:
            f_parts = [int(p) for p in time_str.split(':')]
            time_obj = datetime.time(f_parts[0], f_parts[1], f_parts[2])
            if start_time_val:
                return datetime.datetime.combine(start_time_val.date(), time_obj, tzinfo=JST)
            else:
                return datetime.datetime.combine(datetime.datetime.now(JST).date(), time_obj, tzinfo=JST)
        except: return None


if api_limit_mode: st.warning("⚠️ API通信制限中のため、直前のデータを表示しています")

# ==========================================
# 管理者認証（状態管理）
# ==========================================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

is_admin = st.session_state.is_admin

# ==========================================
# メイン画面（4タブ構成）
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["🚩 スタート", "🏁 ゴール", "⏱️ 同着・僅差", "⚙️ 管理者"])

# --- タブ1：スタートチェック ---
with tab1:
    st.markdown('<div class="title-box">', unsafe_allow_html=True)
    t_col1, t_col2 = st.columns([3, 1])
    t_col1.markdown("<h4 style='margin:0; padding:2px 0;'>🚩 スタート</h4>", unsafe_allow_html=True)
    
    with t_col2:
        if st.button("🔄 更新", key="upd_start"):
            st.session_state.local_updates.clear()
            if time.time() - global_sync["last_read_time"] >= 5.0:
                load_data.clear()
                st.rerun()
            else:
                st.toast("⏳ 最新キャッシュを表示", icon="ℹ️")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
        
    filter_start = st.radio("状態フィルター(スタート)", ["すべて", "未チェック", "チェック済", "DNS(棄権)"], horizontal=True, label_visibility="collapsed", key="f_start")
    
    df_start_view = df.copy()
    for idx_row, row in df_start_view.iterrows():
        t_no = int(row['No'])
        if f"start_{t_no}" in st.session_state.local_updates:
            df_start_view.at[idx_row, 'Start_Check'] = st.session_state.local_updates[f"start_{t_no}"]
        if f"dns_{t_no}" in st.session_state.local_updates:
            df_start_view.at[idx_row, 'DNS'] = st.session_state.local_updates[f"dns_{t_no}"]

    if filter_start == "未チェック":
        view_df = df_start_view[(~df_start_view['Start_Check']) & (~df_start_view['DNS'])]
    elif filter_start == "チェック済":
        view_df = df_start_view[df_start_view['Start_Check']]
    elif filter_start == "DNS(棄権)":
        view_df = df_start_view[df_start_view['DNS']]
    else:
        view_df = df_start_view
        
    if not df.empty:
        max_no = int(df['No'].max())
        range_options = ["すべて"] + [f"{i}～{i+9}" for i in range(1, max_no + 1, 10)]
        selected_range_start = st.radio("番号帯(スタート)", range_options, horizontal=True, label_visibility="collapsed", key="r_start_radio")
        if selected_range_start != "すべて":
            s_num, e_num = map(int, selected_range_start.split("～"))
            view_df = view_df[(view_df['No'] >= s_num) & (view_df['No'] <= e_num)]

    view_df = view_df.sort_values(by="No")

    # 総合一覧（スタート）
    if not view_df.empty:
        st.caption("【スタートチェック】")
        st.markdown('<div class="grid-box">', unsafe_allow_html=True)
        grid_cols = 3
        for i in range(0, len(view_df), grid_cols):
            cols = st.columns(grid_cols)
            batch = view_df.iloc[i:i+grid_cols]
            for idx, (_, row) in enumerate(batch.iterrows()):
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                is_start = row['Start_Check']
                is_dns = row['DNS']

                if is_dns:
                    cols[idx].button(f"{no_str}:DNS", key=f"main_dns_{t_no}", disabled=True, use_container_width=True)
                elif is_start:
                    cols[idx].button(f"{no_str}:済", key=f"main_done_{t_no}", disabled=True, use_container_width=True)
                else:
                    if cols[idx].button(f"{no_str}:未", key=f"start_btn_{t_no}", type="primary", use_container_width=True):
                        try:
                            update_start_cell(t_no, True)
                            st.session_state.local_updates[f"start_{t_no}"] = True
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    # 管理者用リセット（スタート）
    if is_admin:
        st.markdown("---")
        st.markdown("#### 🛠 管理者用メニュー")

        uncheck_df = view_df[(~view_df['Start_Check']) & (~view_df['DNS'])]
        if not uncheck_df.empty:
            st.caption("【出走前棄権(DNS)登録】タップして棄権登録")
            st.markdown('<div class="grid-box">', unsafe_allow_html=True)
            grid_cols = 3
            for i in range(0, len(uncheck_df), grid_cols):
                cols = st.columns(grid_cols)
                batch = uncheck_df.iloc[i:i+grid_cols]
                for idx, (_, row) in enumerate(batch.iterrows()):
                    t_no = int(row['No'])
                    no_str = f"{t_no:03d}"
                    if cols[idx].button(f"🚫 {no_str}:棄権", key=f"dns_btn_{t_no}", type="secondary", use_container_width=True):
                        try:
                            update_dns_cells(t_no, True)
                            st.session_state.local_updates[f"dns_{t_no}"] = True
                            st.session_state.local_updates[f"start_{t_no}"] = False
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        done_df = view_df[view_df['Start_Check'] | view_df['DNS']]
        if not done_df.empty:
            st.caption("【状態リセット (スタート/DNS取消)】タップしてリセット")
            st.markdown('<div class="grid-box">', unsafe_allow_html=True)
            grid_cols = 3
            for i in range(0, len(done_df), grid_cols):
                cols = st.columns(grid_cols)
                batch = done_df.iloc[i:i+grid_cols]
                for idx, (_, row) in enumerate(batch.iterrows()):
                    t_no = int(row['No'])
                    no_str = f"{t_no:03d}"
                    is_start = row['Start_Check']
                    is_dns = row['DNS']

                    if is_dns:
                        if cols[idx].button(f" {no_str}:取消", key=f"dns_cancel_{t_no}", type="secondary", use_container_width=True):
                            try:
                                update_dns_cells(t_no, False)
                                st.session_state.local_updates[f"dns_{t_no}"] = False
                                st.session_state.local_updates[f"start_{t_no}"] = False
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
                    elif is_start:
                        if cols[idx].button(f" {no_str}:取消", key=f"start_cancel_{t_no}", type="secondary", use_container_width=True):
                            try:
                                update_start_cell(t_no, False)
                                st.session_state.local_updates[f"start_{t_no}"] = False
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
            st.markdown('</div>', unsafe_allow_html=True)


# --- タブ2：ゴールチェック ---
with tab2:
    st.markdown('<div class="title-box">', unsafe_allow_html=True)
    t_col3, t_col4 = st.columns([3, 1])
    t_col3.markdown("<h4 style='margin:0; padding:2px 0;'>🏁 ゴール</h4>", unsafe_allow_html=True)
    
    with t_col4:
        if st.button("🔄 更新", key="upd_finish"):
            st.session_state.local_updates.clear()
            if time.time() - global_sync["last_read_time"] >= 5.0:
                load_data.clear()
                st.rerun()
            else:
                st.toast("⏳ 最新キャッシュを表示", icon="ℹ️")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    if not finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。")
    else:
        df_finish_view = df.copy()
        for idx_row, row in df_finish_view.iterrows():
            t_no = int(row['No'])
            if f"start_{t_no}" in st.session_state.local_updates:
                df_finish_view.at[idx_row, 'Start_Check'] = st.session_state.local_updates[f"start_{t_no}"]
            if f"dns_{t_no}" in st.session_state.local_updates:
                df_finish_view.at[idx_row, 'DNS'] = st.session_state.local_updates[f"dns_{t_no}"]
            if f"finish_{t_no}" in st.session_state.local_updates:
                df_finish_view.at[idx_row, 'Finish_Check'] = st.session_state.local_updates[f"finish_{t_no}"]
            if f"dnf_{t_no}" in st.session_state.local_updates:
                df_finish_view.at[idx_row, 'DNF'] = st.session_state.local_updates[f"dnf_{t_no}"]
            if f"time_{t_no}" in st.session_state.local_updates:
                df_finish_view.at[idx_row, 'Finish_Check_Time'] = st.session_state.local_updates[f"time_{t_no}"]

        started_df = df_finish_view[df_finish_view['Start_Check'] & (~df_finish_view['DNS'])]
        filter_finish = st.radio("状態フィルター(ゴール)", ["すべて", "未ゴール", "ゴール済 (DNF含)"], horizontal=True, label_visibility="collapsed", key="f_finish")
        
        if filter_finish == "未ゴール":
            view_df2 = started_df[(~started_df['Finish_Check']) & (~started_df['DNF'])]
        elif filter_finish == "ゴール済 (DNF含)":
            view_df2 = started_df[started_df['Finish_Check'] | started_df['DNF']]
        else:
            view_df2 = started_df
            
        if not df.empty:
            max_no2 = int(df['No'].max())
            range_options2 = ["すべて"] + [f"{i}～{i+9}" for i in range(1, max_no2 + 1, 10)]
            selected_range_finish = st.radio("番号帯(ゴール)", range_options2, horizontal=True, label_visibility="collapsed", key="r_finish_radio")
            if selected_range_finish != "すべて":
                s_num, e_num = map(int, selected_range_finish.split("～"))
                view_df2 = view_df2[(view_df2['No'] >= s_num) & (view_df2['No'] <= e_num)]

        view_df2 = view_df2.sort_values(by="No")

        # 総合一覧（ゴール）- タイムなしのグリッド表示
        if not view_df2.empty:
            st.caption("【ゴールチェック】")
            st.markdown('<div class="grid-box">', unsafe_allow_html=True)
            grid_cols = 3
            for i in range(0, len(view_df2), grid_cols):
                cols = st.columns(grid_cols)
                batch = view_df2.iloc[i:i+grid_cols]
                for idx, (_, row) in enumerate(batch.iterrows()):
                    t_no = int(row['No'])
                    no_str = f"{t_no:03d}"
                    is_fin = row['Finish_Check']
                    is_dnf = row['DNF']

                    if is_dnf:
                        cols[idx].button(f"{no_str}:DNF", key=f"main_fin_dnf_{t_no}", disabled=True, use_container_width=True)
                    elif is_fin:
                        cols[idx].button(f"{no_str}:済", key=f"main_fin_done_{t_no}", disabled=True, use_container_width=True)
                    else:
                        if cols[idx].button(f"{no_str}:ゴール", key=f"finish_btn_{t_no}", type="primary", use_container_width=True):
                            try:
                                now_str = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
                                update_finish_cells(t_no, True, f"'{now_str}")
                                st.session_state.local_updates[f"finish_{t_no}"] = True
                                st.session_state.local_updates[f"time_{t_no}"] = f"'{now_str}"
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        # 詳細一覧（ゴール済み・DNF）
        done_list_df = view_df2[view_df2['Finish_Check'] | view_df2['DNF']]
        if not done_list_df.empty and filter_finish in ["すべて", "ゴール済 (DNF含)"]:
            st.markdown("---")
            st.caption("【ゴール済み・DNF詳細一覧】")
            
            for _, row in done_list_df.iterrows():
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                is_dnf = row['DNF']

                if is_dnf:
                    st.markdown(f"<div class='dnf-card'><span>No.{no_str}</span><span>DNF確定</span></div>", unsafe_allow_html=True)
                else:
                    f_time_str = str(row['Finish_Check_Time']).lstrip("'").strip()
                    net_jp = ""
                    time_jp = ""
                    
                    if f_time_str and f_time_str != "nan":
                        try:
                            if len(f_time_str) >= 19:
                                f_datetime = datetime.datetime.strptime(f_time_str[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
                            else:
                                f_parts = [int(p) for p in f_time_str.split(':')]
                                time_obj = datetime.time(f_parts[0], f_parts[1], f_parts[2])
                                if start_time_val:
                                    f_datetime = datetime.datetime.combine(start_time_val.date(), time_obj, tzinfo=JST)
                                else:
                                    f_datetime = datetime.datetime.combine(datetime.datetime.now(JST).date(), time_obj, tzinfo=JST)
                            
                            time_jp = f_datetime.strftime('%Y-%m-%d %H:%M:%S')
                            
                            if start_time_val:
                                net_seconds = int((f_datetime - start_time_val).total_seconds())
                                if net_seconds < 0:
                                    abs_s = abs(net_seconds)
                                    h = abs_s // 3600
                                    m = (abs_s % 3600) // 60
                                    s = abs_s % 60
                                    net_jp = f"-(マイナス){h}時間{m:02d}分{s:02d}秒" if h > 0 else f"-(マイナス){m:02d}分{s:02d}秒"
                                else:
                                    h = net_seconds // 3600
                                    m = (net_seconds % 3600) // 60
                                    s = net_seconds % 60
                                    net_jp = f"{h}時間{m:02d}分{s:02d}秒" if h > 0 else f"{m:02d}分{s:02d}秒"
                        except Exception:
                            time_jp = "時刻エラー"
                    
                    time_info = f"<div style='text-align: right; line-height: 1.4;'><span class='finish-time'>タイム: {net_jp}</span><br><span class='finish-clock'>(着 {time_jp})</span></div>" if net_jp else f"<div style='text-align: right;'><span class='finish-clock'>着 {time_jp}</span></div>"
                    card_html = f"<div class='finish-card'><span class='finish-no'>No.{no_str}</span>{time_info}</div>"
                    
                    st.markdown(card_html, unsafe_allow_html=True)

        # 管理者用リセット・DNF登録（ゴールタブ）
        if is_admin:
            st.markdown("---")
            st.markdown("#### 🛠 管理者用メニュー")
            
            unfinish_df = view_df2[(~view_df2['Finish_Check']) & (~view_df2['DNF'])]
            if not unfinish_df.empty:
                st.caption("【途中棄権(DNF)登録】タップして棄権登録")
                st.markdown('<div class="grid-box">', unsafe_allow_html=True)
                grid_cols = 3
                for i in range(0, len(unfinish_df), grid_cols):
                    cols = st.columns(grid_cols)
                    batch = unfinish_df.iloc[i:i+grid_cols]
                    for idx, (_, row) in enumerate(batch.iterrows()):
                        t_no = int(row['No'])
                        no_str = f"{t_no:03d}"
                        if cols[idx].button(f" {no_str}:棄権", key=f"dnf_reg_btn_{t_no}", type="secondary", use_container_width=True):
                            try:
                                update_dnf_cells(t_no, True, True, "")
                                st.session_state.local_updates[f"dnf_{t_no}"] = True
                                st.session_state.local_updates[f"finish_{t_no}"] = True
                                st.session_state.local_updates[f"time_{t_no}"] = ""
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
                st.markdown('</div>', unsafe_allow_html=True)

            done_finish_df = view_df2[view_df2['Finish_Check'] | view_df2['DNF']]
            if not done_finish_df.empty:
                st.caption("【状態リセット (ゴール/DNF取消)】")
                st.markdown('<div class="grid-box">', unsafe_allow_html=True)
                grid_cols = 3
                for i in range(0, len(done_finish_df), grid_cols):
                    cols = st.columns(grid_cols)
                    batch = done_finish_df.iloc[i:i+grid_cols]
                    for idx, (_, row) in enumerate(batch.iterrows()):
                        t_no = int(row['No'])
                        no_str = f"{t_no:03d}"
                        is_fin = row['Finish_Check']
                        is_dnf = row['DNF']

                        if is_dnf:
                            if cols[idx].button(f" {no_str}:取消", key=f"dnf_cancel_{t_no}", type="secondary", use_container_width=True):
                                try:
                                    update_dnf_cells(t_no, False, False, "")
                                    st.session_state.local_updates[f"dnf_{t_no}"] = False
                                    st.session_state.local_updates[f"finish_{t_no}"] = False
                                    st.session_state.local_updates[f"time_{t_no}"] = ""
                                    st.rerun()
                                except Exception as e: st.error(f"エラー: {e}")
                        elif is_fin:
                            if cols[idx].button(f" {no_str}:取消", key=f"finish_cancel_{t_no}", type="secondary", use_container_width=True):
                                try:
                                    update_finish_cells(t_no, False, "")
                                    st.session_state.local_updates[f"finish_{t_no}"] = False
                                    st.session_state.local_updates[f"time_{t_no}"] = ""
                                    st.rerun()
                                except Exception as e: st.error(f"エラー: {e}")
                st.markdown('</div>', unsafe_allow_html=True)

# --- タブ3：同着・僅差 ---
with tab3:
    st.markdown("<h4 style='margin:0; padding:2px 0;'>⏱️ 同着・僅差設定</h4>", unsafe_allow_html=True)
    st.markdown("2つの番号を入力して時刻調整・ゴール処理を行います。")
    
    c_col1, c_col2 = st.columns(2)
    close_no1 = c_col1.number_input("対象番号 1", min_value=0, step=1, value=0, key="close_no1")
    close_no2 = c_col2.number_input("対象番号 2", min_value=0, step=1, value=0, key="close_no2")
    
    if close_no1 > 0 and close_no2 > 0:
        if close_no1 == close_no2:
            st.warning("⚠️ 異なる番号を入力してください。")
        else:
            # 最新状態を取得（対象となる2つの番号のみ更新反映）
            df_close = df.copy()
            for idx_row, row in df_close.iterrows():
                t_no = int(row['No'])
                if t_no in (close_no1, close_no2):
                    if f"start_{t_no}" in st.session_state.local_updates: df_close.at[idx_row, 'Start_Check'] = st.session_state.local_updates[f"start_{t_no}"]
                    if f"dns_{t_no}" in st.session_state.local_updates: df_close.at[idx_row, 'DNS'] = st.session_state.local_updates[f"dns_{t_no}"]
                    if f"finish_{t_no}" in st.session_state.local_updates: df_close.at[idx_row, 'Finish_Check'] = st.session_state.local_updates[f"finish_{t_no}"]
                    if f"dnf_{t_no}" in st.session_state.local_updates: df_close.at[idx_row, 'DNF'] = st.session_state.local_updates[f"dnf_{t_no}"]
                    if f"time_{t_no}" in st.session_state.local_updates: df_close.at[idx_row, 'Finish_Check_Time'] = st.session_state.local_updates[f"time_{t_no}"]

            row1 = df_close[df_close['No'] == close_no1]
            row2 = df_close[df_close['No'] == close_no2]
            
            if row1.empty or row2.empty:
                st.error("⚠️ 入力された番号が存在しません。本部に連絡して下さい。")
            else:
                row1 = row1.iloc[0]
                row2 = row2.iloc[0]
                
                if row1['DNS'] or row1['DNF'] or row2['DNS'] or row2['DNF']:
                    st.error("⚠️ 棄権（DNS/DNF）の番号が含まれています。本部スタッフにて対応するため内容を本部に連絡して下さい。")
                elif not row1['Start_Check'] or not row2['Start_Check']:
                    st.error("⚠️ 未スタートの番号が含まれています。本部に連絡して下さい。")
                else:
                    is_fin1 = row1['Finish_Check']
                    is_fin2 = row2['Finish_Check']
                    
                    def perform_time_update(target_no, new_dt, success_msg=""):
                        new_time_str = f"'{new_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                        try:
                            update_finish_cells(target_no, True, new_time_str)
                            st.session_state.local_updates[f"finish_{target_no}"] = True
                            st.session_state.local_updates[f"time_{target_no}"] = new_time_str
                            st.success(success_msg)
                            st.rerun()
                        except Exception as e:
                            st.error(f"更新エラー: {e}")
                    
                    # 【パターン1】両方とも未ゴール
                    if not is_fin1 and not is_fin2:
                        st.info("💡 どちらか一方はゴール済の番号を選択（入力）して下さい。")
                    
                    # 【パターン2】両方ともゴール済
                    elif is_fin1 and is_fin2:
                        t1 = parse_time(row1['Finish_Check_Time'], start_time_val)
                        t2 = parse_time(row2['Finish_Check_Time'], start_time_val)
                        
                        if t1 is None or t2 is None:
                            st.error("⚠️ ゴール時刻データの取得に失敗しました。本部に連絡して下さい。")
                        else:
                            diff_sec = abs((t1 - t2).total_seconds())
                            
                            if diff_sec >= 10:
                                st.error("⚠️ 2つともゴール済みでゴール時刻に10秒以上差がある場合は、本部スタッフにて対応するため内容を本部に連絡して下さい。")
                            else:
                                if t1 > t2:
                                    late_no, late_time = close_no1, t1
                                    base_no, base_time = close_no2, t2
                                else:
                                    late_no, late_time = close_no2, t2
                                    base_no, base_time = close_no1, t1
                                
                                st.markdown(f"**No.{late_no}** の時刻を **No.{base_no}** の時刻（{base_time.strftime('%H:%M:%S')}）を基準に修正します。")
                                
                                if st.button(f"No.{late_no} を No.{base_no} より1秒早い", use_container_width=True):
                                    perform_time_update(late_no, base_time - datetime.timedelta(seconds=1), f"No.{late_no} の時刻を修正しました。")
                                if st.button(f"No.{late_no} を No.{base_no} と同時刻着", use_container_width=True):
                                    perform_time_update(late_no, base_time, f"No.{late_no} の時刻を修正しました。")
                                if st.button(f"No.{late_no} を No.{base_no} より1秒遅い", use_container_width=True):
                                    perform_time_update(late_no, base_time + datetime.timedelta(seconds=1), f"No.{late_no} の時刻を修正しました。")
                                if st.button(f"No.{late_no} を No.{base_no} より2秒遅い", use_container_width=True):
                                    perform_time_update(late_no, base_time + datetime.timedelta(seconds=2), f"No.{late_no} の時刻を修正しました。")
                                if st.button(f"No.{late_no} を No.{base_no} より3秒遅い", use_container_width=True):
                                    perform_time_update(late_no, base_time + datetime.timedelta(seconds=3), f"No.{late_no} の時刻を修正しました。")

                    # 【パターン3】片方が未ゴール・片方がゴール済
                    elif is_fin1 != is_fin2:
                        unfin_no = close_no1 if not is_fin1 else close_no2
                        fin_no = close_no2 if not is_fin1 else close_no1
                        fin_time_raw = row2['Finish_Check_Time'] if not is_fin1 else row1['Finish_Check_Time']
                        
                        base_time = parse_time(fin_time_raw, start_time_val)
                        if base_time is None:
                            st.error("⚠️ ゴール済番号の時刻データの取得に失敗しました。本部に連絡して下さい。")
                        else:
                            st.markdown(f"未ゴールの **No.{unfin_no}** を、ゴール済の **No.{fin_no}** の時刻（{base_time.strftime('%H:%M:%S')}）を基準にゴール処理します。")
                            
                            if st.button(f"No.{unfin_no} を No.{fin_no} より1秒早い", use_container_width=True):
                                perform_time_update(unfin_no, base_time - datetime.timedelta(seconds=1), f"No.{unfin_no} をゴール処理しました。")
                            if st.button(f"No.{unfin_no} を No.{fin_no} と同時刻着", use_container_width=True):
                                perform_time_update(unfin_no, base_time, f"No.{unfin_no} をゴール処理しました。")
                            if st.button(f"No.{unfin_no} を No.{fin_no} より1秒遅い", use_container_width=True):
                                perform_time_update(unfin_no, base_time + datetime.timedelta(seconds=1), f"No.{unfin_no} をゴール処理しました。")


# --- タブ4：管理者メニュー ---
with tab4:
    st.markdown("<h4 style='margin:0; padding:2px 0;'>⚙️ 管理者メニュー</h4>", unsafe_allow_html=True)
    
    if not st.session_state.is_admin:
        admin_input = st.text_input("管理者パスワードを入力", type="password")
        if st.button("ログイン"):
            if admin_input == st.secrets["admin_password"]:
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("パスワードが正しくありません")
    else:
        st.success("管理者認証成功")
        if st.button("🚪 管理者メニューから抜ける"):
            st.session_state.is_admin = False
            st.rerun()
        
        st.markdown("#### 🏁 ゴールチェック設定")
        if finish_enabled:
            st.success("状態: 🔓 一般開放中")
            btn_label = "🔒 ゴールチェックをロックする"
            new_status = False
        else:
            st.warning("状態: 🔒 ロック中")
            btn_label = "🔓 ゴールチェックを一般開放する"
            new_status = True
            
        if st.button(btn_label):
            try:
                update_setting_cell('finish_enabled', new_status)
                time.sleep(2.0)
                load_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"更新エラーが発生しました: {e}")
        
        st.markdown("#### ⏱️ スタート時刻設定")
        if st.button("現在時刻(JST)をスタートに設定"):
            try:
                new_time = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
                update_setting_cell('start_time', f"'{new_time}")
                time.sleep(2.0)
                load_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"更新エラーが発生しました: {e}")
        
        st.markdown("---")
        default_datetime_str = start_time_val.strftime('%Y%m%d%H%M%S') if start_time_val else datetime.datetime.now(JST).strftime('%Y%m%d%H%M%S')
        manual_datetime_str = st.text_input("手動設定 (YYYYMMDDHHMMSS形式)", value=default_datetime_str, max_chars=14)
        
        if st.button("手動入力した時刻をセット"):
            try:
                if len(manual_datetime_str) != 14 or not manual_datetime_str.isdigit():
                    st.error("⚠️ 14桁の半角数字（例: 20241025093000）で入力してください。")
                else:
                    new_manual_datetime = datetime.datetime.strptime(manual_datetime_str, '%Y%m%d%H%M%S').replace(tzinfo=JST)
                    update_setting_cell('start_time', f"'{new_manual_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
                    time.sleep(2.0)
                    load_data.clear()
                    st.rerun()
            except ValueError:
                st.error("⚠️ 正しい日時（存在する年月日・時刻）を入力してください。")
            except Exception as e:
                st.error(f"更新エラーが発生しました: {e}")

        st.markdown("---")
        if start_time_val:
            st.info(f"スタート時刻:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")
        else:
            st.info("スタート時刻:\n未設定")
