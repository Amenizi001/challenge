import streamlit as st
import pandas as pd
import datetime
import time
from zoneinfo import ZoneInfo
import gspread

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

JST = ZoneInfo("Asia/Tokyo")

# --- UI最適化CSS ---
st.markdown("""
<style>
    /* ボタンの余白と高さを調整 */
    div.stButton > button {
        padding: 15px 20px !important; 
        height: auto !important; 
    }
    
    /* ボタン内部の文字サイズを強制的に大きくする */
    div.stButton > button p {
        font-size: 24px !important; 
        font-weight: bold !important; 
        margin: 0 !important;
    }
    
    /* レイアウト調整用設定 */
    .title-box div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
    }
    .title-box div[data-testid="column"]:nth-child(1) {
        width: 70% !important; flex: 1 1 70% !important; min-width: 70% !important;
    }
    .title-box div[data-testid="column"]:nth-child(2) {
        width: 30% !important; flex: 1 1 30% !important; min-width: 30% !important;
    }
    .grid-box div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 6px !important;
    }
    .grid-box div[data-testid="column"] {
        width: calc(33.333% - 4px) !important; flex: 1 1 calc(33.333% - 4px) !important;
        min-width: calc(33.333% - 4px) !important; max-width: calc(33.333% - 4px) !important;
    }
    .admin-card-box div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; align-items: center !important;
    }
    .admin-card-box div[data-testid="column"]:nth-child(1) {
        width: 75% !important; flex: 1 1 75% !important; min-width: 75% !important;
    }
    .admin-card-box div[data-testid="column"]:nth-child(2) {
        width: 25% !important; flex: 1 1 25% !important; min-width: 25% !important;
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
        align-items: center; color: #664d03; font-weight: bold; font-size: 1.15rem;
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

@st.cache_resource
def get_global_sync_manager(): return {"last_read_time": 0.0}
global_sync = get_global_sync_manager()

@st.cache_resource
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

@st.cache_data(ttl=15)
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

start_time_str = str(settings_dict.get('start_time', ''))
if start_time_str and start_time_str.lower() != 'nan':
    start_time_val = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
else:
    start_time_val = None

if api_limit_mode: st.warning("⚠️ API通信制限中のため、直前のデータを表示しています")

# ==========================================
# 管理者認証（状態管理）
# ==========================================
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

is_admin = st.session_state.is_admin

# ==========================================
# メイン画面（3タブ構成に変更）
# ==========================================
tab1, tab2, tab3 = st.tabs(["🚩 スタート", "🏁 ゴール", "⚙️ 管理者"])

# --- タブ1：スタートチェック済チェック ---
with tab1:
    st.markdown('<div class="title-box">', unsafe_allow_html=True)
    t_col1, t_col2 = st.columns([3, 1])
    t_col1.markdown("<h4 style='margin:0; padding:2px 0;'>🚩 スタート</h4>", unsafe_allow_html=True)
    if t_col2.button("🔄 更新", key="upd_start"):
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

    uncheck_df = view_df[(~view_df['Start_Check']) & (~view_df['DNS'])].sort_values(by="No")
    if not uncheck_df.empty and filter_start in ["すべて", "未チェック"]:
        st.caption("【スタート前_未チェック一覧】")
        st.markdown('<div class="grid-box">', unsafe_allow_html=True)
        grid_cols = 3
        for i in range(0, len(uncheck_df), grid_cols):
            cols = st.columns(grid_cols)
            batch = uncheck_df.iloc[i:i+grid_cols]
            for idx, (_, row) in enumerate(batch.iterrows()):
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                if cols[idx].button(f"{no_str}:未", key=f"start_btn_{t_no}", type="primary"):
                    try:
                        update_start_cell(t_no, True)
                        st.session_state.local_updates[f"start_{t_no}"] = True
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    if is_admin and not uncheck_df.empty and filter_start in ["すべて", "未チェック"]:
        st.caption("【管理者用：出走前棄権(DNS)登録】")
        st.markdown('<div class="grid-box">', unsafe_allow_html=True)
        grid_cols = 3
        for i in range(0, len(uncheck_df), grid_cols):
            cols = st.columns(grid_cols)
            batch = uncheck_df.iloc[i:i+grid_cols]
            for idx, (_, row) in enumerate(batch.iterrows()):
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                if cols[idx].button(f"🚫 {no_str}:棄権", key=f"dns_btn_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, True)
                        st.session_state.local_updates[f"dns_{t_no}"] = True
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

    done_df = view_df[view_df['Start_Check'] | view_df['DNS']].sort_values(by="No")
    if not done_df.empty and filter_start in ["すべて", "チェック済", "DNS(棄権)"]:
        if filter_start == "すべて":
            st.markdown("---")
        st.caption("【スタート前_チェック済・棄権一覧】")
        
        # ▼ここから変更：済・棄権のリストを横3列に並べる
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
                    if is_admin:
                        # 長いとレイアウトが崩れるため「取消」と短くしています
                        if cols[idx].button(f"↩️ {no_str}:取消", key=f"dns_cancel_{t_no}", type="secondary"):
                            try:
                                update_dns_cells(t_no, False)
                                st.session_state.local_updates[f"dns_{t_no}"] = False
                                st.session_state.local_updates[f"start_{t_no}"] = False
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
                    else:
                        cols[idx].button(f"{no_str}:DNS", key=f"dns_done_{t_no}", disabled=True)
                elif is_start:
                    if is_admin:
                        # 長いとレイアウトが崩れるため「取消」と短くしています
                        if cols[idx].button(f"❌ {no_str}:取消", key=f"start_cancel_{t_no}", type="secondary"):
                            try:
                                update_start_cell(t_no, False)
                                st.session_state.local_updates[f"start_{t_no}"] = False
                                st.rerun()
                            except Exception as e: st.error(f"エラー: {e}")
                    else:
                        cols[idx].button(f"{no_str}:済", key=f"start_done_{t_no}", disabled=True)
        st.markdown('</div>', unsafe_allow_html=True)


# --- タブ2：ゴールチェック ---
with tab2:
    st.markdown('<div class="title-box">', unsafe_allow_html=True)
    t_col3, t_col4 = st.columns([3, 1])
    t_col3.markdown("<h4 style='margin:0; padding:2px 0;'>🏁 ゴール</h4>", unsafe_allow_html=True)
    if t_col4.button("🔄 更新", key="upd_finish"):
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
        
        # ▼ここから変更：DNFが確実にゴール済に含まれるように修正
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

        unfinish_df = view_df2[(~view_df2['Finish_Check']) & (~view_df2['DNF'])].sort_values(by="No")
        if not unfinish_df.empty and filter_finish in ["すべて", "未ゴール"]:
            st.caption("【未ゴール】タップしてゴール完了")
            st.markdown('<div class="grid-box">', unsafe_allow_html=True)
            grid_cols = 3
            for i in range(0, len(unfinish_df), grid_cols):
                cols = st.columns(grid_cols)
                batch = unfinish_df.iloc[i:i+grid_cols]
                for idx, (_, row) in enumerate(batch.iterrows()):
                    t_no = int(row['No'])
                    no_str = f"{t_no:03d}"
                    if cols[idx].button(f"{no_str}:ゴール", key=f"finish_btn_{t_no}", type="primary"):
                        try:
                            now_str = datetime.datetime.now(JST).strftime('%H:%M:%S')
                            update_finish_cells(t_no, True, now_str)
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = now_str
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        finished_df = view_df2[view_df2['Finish_Check'] & (~view_df2['DNF'])].sort_values(by="No")
        if not finished_df.empty and filter_finish in ["すべて", "ゴール済 (DNF含)"]:
            if filter_finish == "すべて":
                st.markdown("---")
            st.caption("【ゴール済み一覧】")
            for _, row in finished_df.iterrows():
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                f_time_str = str(row['Finish_Check_Time'])
                net_jp = ""
                time_jp = ""
                if f_time_str and f_time_str != "nan":
                    try:
                        f_parts = [int(p) for p in f_time_str.split(':')]
                        time_jp = f"{f_parts[0]}時{f_parts[1]}分{f_parts[2]}秒"
                        if start_time_val:
                            f_time_obj = datetime.datetime.strptime(f_time_str, '%H:%M:%S').time()
                            f_datetime = datetime.datetime.combine(start_time_val.date(), f_time_obj, tzinfo=JST)
                            net_seconds = int((f_datetime - start_time_val).total_seconds())
                            h = net_seconds // 3600
                            m = (net_seconds % 3600) // 60
                            s = net_seconds % 60
                            net_jp = f"{h}時間{m}分{s}秒" if h > 0 else f"{m}分{s}秒"
                    except Exception:
                        pass
                
                # 改行（<br>）を入れ、2行が右揃えになるように div タグで囲む
                time_info = f"<div style='text-align: right; line-height: 1.4;'><span class='finish-time'>タイム: {net_jp}</span><br><span class='finish-clock'>(着 {time_jp})</span></div>" if net_jp else f"<div style='text-align: right;'><span class='finish-clock'>着 {time_jp}</span></div>"
                
                # 余分な <span> を外し、直接 time_info を入れる
                card_html = f"<div class='finish-card'><span class='finish-no'>No.{no_str}</span>{time_info}</div>"

                if is_admin:
                    st.markdown('<div class="admin-card-box">', unsafe_allow_html=True)
                    col_card, col_btn = st.columns([3, 1])
                    col_card.markdown(card_html, unsafe_allow_html=True)
                    if col_btn.button("❌ ゴール取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            update_finish_cells(t_no, False, "")
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.markdown(card_html, unsafe_allow_html=True)

        if is_admin and not unfinish_df.empty and filter_finish in ["すべて", "未ゴール"]:
            st.markdown("---")
            st.caption("【管理者用：途中棄権(DNF)登録】タップしてDNF登録")
            st.markdown('<div class="grid-box">', unsafe_allow_html=True)
            grid_cols = 3
            for i in range(0, len(unfinish_df), grid_cols):
                cols = st.columns(grid_cols)
                batch = unfinish_df.iloc[i:i+grid_cols]
                for idx, (_, row) in enumerate(batch.iterrows()):
                    t_no = int(row['No'])
                    no_str = f"{t_no:03d}"
                    if cols[idx].button(f"⚠️ {no_str}:棄権", key=f"dnf_btn_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, True, True, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = True
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

        dnf_df = view_df2[view_df2['DNF']].sort_values(by="No")
        if not dnf_df.empty and filter_finish in ["すべて", "ゴール済 (DNF含)"]:
            st.markdown("---")
            st.caption("【途中棄権(DNF)一覧】")
            for _, row in dnf_df.iterrows():
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                if is_admin:
                    st.markdown('<div class="admin-card-box">', unsafe_allow_html=True)
                    col_card, col_btn = st.columns([3, 1])
                    col_card.markdown(f"<div class='dnf-card'><span>No.{no_str}</span><span>DNF (途中棄権)</span></div>", unsafe_allow_html=True)
                    if col_btn.button("↩️ DNF取消", key=f"undnf_cancel_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, False, False, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = False
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='dnf-card'><span>No.{no_str}</span><span>DNF (途中棄権)</span></div>", unsafe_allow_html=True)

# --- タブ3：管理者メニュー（サイドバーを廃止してタブ化） ---
with tab3:
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
                update_setting_cell('start_time', new_time)
                time.sleep(2.0)
                load_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"更新エラーが発生しました: {e}")
                
        st.markdown("---")
        default_time = start_time_val.time() if start_time_val else datetime.datetime.now(JST).time()
        manual_time = st.time_input("手動設定 (時:分:秒)", value=default_time, step=1)
        
        if st.button("手動入力した時刻をセット"):
            try:
                today_date = start_time_val.date() if start_time_val else datetime.datetime.now(JST).date()
                new_manual_datetime = datetime.datetime.combine(today_date, manual_time, tzinfo=JST)
                update_setting_cell('start_time', new_manual_datetime.strftime('%Y-%m-%d %H:%M:%S'))
                time.sleep(2.0)
                load_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"更新エラーが発生しました: {e}")

        st.markdown("---")
        if start_time_val:
            st.info(f"設定済:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")
        else:
            st.info("設定済:\n未設定")
