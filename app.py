import streamlit as st
import pandas as pd
import datetime
import time
from zoneinfo import ZoneInfo
import gspread

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

JST = ZoneInfo("Asia/Tokyo")

# --- UI最適化CSS（スマホでの縦落ちを強制解除・横スクロール化） ---
st.markdown("""
<style>
/* 1. タブ上部の空白を極限まで詰める */
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 2rem !important;
    padding-left: 0.5rem !important;
    padding-right: 0.5rem !important;
}
header[data-testid="stHeader"] {
    display: none !important;
}

/* 2. Streamlit標準のカラム自動折り返し（縦並び化）をスマホでも強制解除 */
div[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 4px !important;
    margin-bottom: 3px !important;
}
div[data-testid="column"] {
    min-width: 0 !important;
    flex: 1 1 0% !important;
    margin-bottom: 0px !important;
}

/* 3. 番号帯フィルター専用の横スクロールラッパー */
.range-scroll-box div[data-testid="stHorizontalBlock"] {
    overflow-x: auto !important;
    white-space: nowrap !important;
    padding-bottom: 6px !important;
    -webkit-overflow-scrolling: touch;
}
.range-scroll-box div[data-testid="column"] {
    flex: 0 0 58px !important; /* ボタンの幅を固定して横スクロールさせる */
    min-width: 58px !important;
}

/* 4. ボタンのコンパクト化と2行表示対応 */
div[data-testid="column"] button {
    padding: 2px 2px !important;
    font-size: 0.72rem !important;
    line-height: 1.15 !important;
    width: 100% !important;
    min-height: 38px !important;
    height: 38px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    white-space: normal !important;
    text-align: center !important;
}

/* 5. ゴールタイム表示枠の高さをボタン（38px）に完全に一致させる */
.time-badge {
    background-color: #d1e7dd;
    color: #0f5132;
    border: 1px solid #badbcc;
    border-radius: 4px;
    height: 38px !important;
    min-height: 38px !important;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    font-size: 0.65rem;
    line-height: 1.15;
    text-align: center;
    width: 100%;
    padding: 0 1px;
}
.dnf-badge {
    background-color: #f8d7da;
    color: #842029;
    border: 1px solid #f5c2c7;
    border-radius: 4px;
    height: 38px !important;
    min-height: 38px !important;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: bold;
    width: 100%;
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
if "selected_range_start" not in st.session_state: st.session_state.selected_range_start = "すべて"
if "selected_range_finish" not in st.session_state: st.session_state.selected_range_finish = "すべて"

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
        
    expected_cols = ['No', 'Start_Check', 'Finish_Check', 'Finish_Check_Time', 'DNF', 'DNS', 'Key', 'Value']
    current_cols = list(df.columns)
    if current_cols[:8] != expected_cols:
        st.error("⚠️ スプレッドシートの列構成が正しくありません。")
        st.stop()
        
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
# サイドバー：管理者メニュー
# ==========================================
st.sidebar.header("管理者メニュー")
admin_pass = st.sidebar.text_input("管理者パスワードを入力", type="password", key="admin_pwd_input")
is_admin = False

if admin_pass == st.secrets["admin_password"]:
    st.sidebar.success("管理者認証成功")
    is_admin = True
    
    if st.sidebar.button("🚪 管理者メニューから抜ける"):
        st.session_state.admin_pwd_input = ""
        st.rerun()
    
    st.sidebar.subheader("🏁 ゴールチェック設定")
    if finish_enabled:
        st.sidebar.success("状態: 🔓 一般開放中")
        btn_label = "🔒 ゴールチェックをロックする"
        new_status = False
    else:
        st.sidebar.warning("状態: 🔒 ロック中")
        btn_label = "🔓 ゴールチェックを一般開放する"
        new_status = True
        
    if st.sidebar.button(btn_label):
        try:
            update_setting_cell('finish_enabled', new_status)
            time.sleep(2.0)
            load_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"更新エラーが発生しました: {e}")
    
    st.sidebar.subheader("⏱️ スタート時刻設定")
    if st.sidebar.button("現在時刻(JST)をスタートに設定"):
        try:
            new_time = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
            update_setting_cell('start_time', new_time)
            time.sleep(2.0)
            load_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"更新エラーが発生しました: {e}")
            
    st.sidebar.markdown("---")
    default_time = start_time_val.time() if start_time_val else datetime.datetime.now(JST).time()
    manual_time = st.sidebar.time_input("手動設定 (時:分:秒)", value=default_time, step=1)
    
    if st.sidebar.button("手動入力した時刻をセット"):
        try:
            today_date = start_time_val.date() if start_time_val else datetime.datetime.now(JST).date()
            new_manual_datetime = datetime.datetime.combine(today_date, manual_time, tzinfo=JST)
            update_setting_cell('start_time', new_manual_datetime.strftime('%Y-%m-%d %H:%M:%S'))
            time.sleep(2.0)
            load_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"更新エラーが発生しました: {e}")

    st.sidebar.markdown("---")
    if start_time_val:
        st.sidebar.info(f"設定済:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")
    else:
        st.sidebar.info("設定済:\n未設定")


# ==========================================
# メイン画面（タブ）
# ==========================================
tab1, tab2 = st.tabs(["スタートチェック", "ゴールチェック"])

# --- タブ1：スタートチェック ---
with tab1:
    t_col1, t_col2 = st.columns([3, 1])
    t_col1.markdown("<h4 style='margin:0; padding:4px 0;'>🚩 スタート</h4>", unsafe_allow_html=True)
    if t_col2.button("🔄 更新", key="upd_start"):
        st.session_state.local_updates.clear()
        if time.time() - global_sync["last_read_time"] >= 5.0:
            load_data.clear()
            st.rerun()
        else:
            st.toast("⏳ 直前に最新化されたため、最新キャッシュを表示しました", icon="ℹ️")
            st.rerun()
        
    filter_start = st.radio("状態フィルター(スタート)", ["すべて", "未チェック", "チェック済", "DNS(棄権)"], horizontal=True, label_visibility="collapsed", key="f_start")
    
    if filter_start == "未チェック": view_df = df[(~df['Start_Check']) & (~df['DNS'])]
    elif filter_start == "チェック済": view_df = df[df['Start_Check']]
    elif filter_start == "DNS(棄権)": view_df = df[df['DNS']]
    else: view_df = df
        
    if not df.empty:
        max_no = int(df['No'].max())
        ranges = ["すべて"] + [f"{i}～\n{i+9}" for i in range(1, max_no + 1, 10)]
        
        cols = st.columns(len(ranges))
        for idx, r in enumerate(ranges):
            is_active = (st.session_state.selected_range_start == r)
            btn_type = "primary" if is_active else "secondary"
            btn_label = "全\n部" if r == "すべて" else r
            if cols[idx].button(btn_label, key=f"r_btn_start_{idx}", type=btn_type):
                st.session_state.selected_range_start = r
                st.rerun()
                
        if st.session_state.selected_range_start != "すべて":
            s_num, e_num = map(int, st.session_state.selected_range_start.replace("\n", "").split("～"))
            view_df = view_df[(view_df['No'] >= s_num) & (view_df['No'] <= e_num)]

    for _, row in view_df.iterrows():
        t_no = int(row['No'])
        no_str = f"{t_no:03d}"  # No. プレフィックスを削除
        
        is_start = row['Start_Check']
        is_dns = row['DNS']
        if f"start_{t_no}" in st.session_state.local_updates: is_start = st.session_state.local_updates[f"start_{t_no}"]
        if f"dns_{t_no}" in st.session_state.local_updates: is_dns = st.session_state.local_updates[f"dns_{t_no}"]
        
        if is_admin:
            c1, c2 = st.columns([1.2, 1.8])
        else:
            c1 = st.columns([1])[0]
            c2 = None

        if is_dns:
            c1.button(f"{no_str}:DNS", key=f"dns_done_{t_no}", disabled=True)
            if is_admin and c2:
                if c2.button("↩️ 棄権取消", key=f"dns_cancel_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, False)
                        st.session_state.local_updates[f"dns_{t_no}"] = False
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                
        elif is_start:
            c1.button(f"{no_str}:済", key=f"start_done_{t_no}", disabled=True)
            if is_admin and c2:
                if c2.button("❌ チェック取消", key=f"start_cancel_{t_no}", type="secondary"):
                    try:
                        update_start_cell(t_no, False)
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                
        else:
            if is_admin:
                c1_a, c1_b = st.columns([1.2, 1.0])
                if c1_a.button(f"{no_str}:未", key=f"start_btn_{t_no}", type="primary"):
                    try:
                        update_start_cell(t_no, True)
                        st.session_state.local_updates[f"start_{t_no}"] = True
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                if c1_b.button("🚫 棄権", key=f"dns_btn_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, True)
                        st.session_state.local_updates[f"dns_{t_no}"] = True
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
            else:
                if c1.button(f"{no_str}:未", key=f"start_btn_{t_no}", type="primary"):
                    try:
                        update_start_cell(t_no, True)
                        st.session_state.local_updates[f"start_{t_no}"] = True
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")


# --- タブ2：ゴールチェック ---
with tab2:
    t_col3, t_col4 = st.columns([3, 1])
    t_col3.markdown("<h4 style='margin:0; padding:4px 0;'>🏁 ゴール</h4>", unsafe_allow_html=True)
    if t_col4.button("🔄 更新", key="upd_finish"):
        st.session_state.local_updates.clear()
        if time.time() - global_sync["last_read_time"] >= 5.0:
            load_data.clear()
            st.rerun()
        else:
            st.toast("⏳ 直前に最新化されたため、最新キャッシュを表示しました", icon="ℹ️")
            st.rerun()
    
    if not finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。")
    else:
        started_df = df[df['Start_Check'] & (~df['DNS'])]
        filter_finish = st.radio("状態フィルター(ゴール)", ["すべて", "未ゴール", "ゴール済 (DNF含)"], horizontal=True, label_visibility="collapsed", key="f_finish")
        
        if filter_finish == "未ゴール": view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済 (DNF含)": view_df2 = started_df[started_df['Finish_Check']]
        else: view_df2 = started_df
            
        if not df.empty:
            max_no2 = int(df['No'].max())
            ranges2 = ["すべて"] + [f"{i}～\n{i+9}" for i in range(1, max_no2 + 1, 10)]
            
            cols2 = st.columns(len(ranges2))
            for idx, r in enumerate(ranges2):
                is_active2 = (st.session_state.selected_range_finish == r)
                btn_type2 = "primary" if is_active2 else "secondary"
                btn_label2 = "全\n部" if r == "すべて" else r
                if cols2[idx].button(btn_label2, key=f"r_btn_finish_{idx}", type=btn_type2):
                    st.session_state.selected_range_finish = r
                    st.rerun()
                    
            if st.session_state.selected_range_finish != "すべて":
                s_num, e_num = map(int, st.session_state.selected_range_finish.replace("\n", "").split("～"))
                view_df2 = view_df2[(view_df2['No'] >= s_num) & (view_df2['No'] <= e_num)]
            
        for _, row in view_df2.iterrows():
            t_no = int(row['No'])
            no_str = f"{t_no:03d}"  # No. プレフィックスを削除
            
            is_dnf = row['DNF']
            is_finished = row['Finish_Check']
            f_time_str = str(row['Finish_Check_Time'])
            
            if f"dnf_{t_no}" in st.session_state.local_updates: is_dnf = st.session_state.local_updates[f"dnf_{t_no}"]
            if f"finish_{t_no}" in st.session_state.local_updates: is_finished = st.session_state.local_updates[f"finish_{t_no}"]
            if f"time_{t_no}" in st.session_state.local_updates: f_time_str = st.session_state.local_updates[f"time_{t_no}"]

            time_display_html = ""
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

                        time_display_html = f"<div class='time-badge'><span>タイム: {net_jp}</span><span>(着 {time_jp})</span></div>"
                    else:
                        time_display_html = f"<div class='time-badge'><span>着 {time_jp}</span></div>"
                except Exception:
                    time_display_html = f"<div class='time-badge'><span>{f_time_str}</span></div>"

            if is_admin:
                c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
            else:
                c1, c3 = st.columns([1.2, 1.8])
                c2 = None
            
            if is_dnf:
                c1.button(f"{no_str}:棄権済", key=f"dnf_done_{t_no}", disabled=True)
                if is_admin and c2:
                    if c2.button("↩️ DNF取消", key=f"undnf_cancel_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, False, False, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = False
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                c3.markdown("<div class='dnf-badge'>DNF</div>", unsafe_allow_html=True)
                
            elif is_finished:
                c1.button(f"{no_str}:ゴール済", key=f"finish_done_{t_no}", disabled=True)
                if is_admin and c2:
                    if c2.button("❌ ゴール取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            update_finish_cells(t_no, False, "")
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                c3.markdown(time_display_html, unsafe_allow_html=True)

            else:
                if is_admin:
                    if c1.button(f"{no_str}:未", key=f"finish_btn_{t_no}", type="primary"):
                        try:
                            now_str = datetime.datetime.now(JST).strftime('%H:%M:%S')
                            update_finish_cells(t_no, True, now_str)
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = now_str
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                    if c2.button("⚠️ 棄権", key=f"dnf_btn_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, True, True, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = True
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                    c3.empty()
                else:
                    if c1.button(f"{no_str}:未", key=f"finish_btn_{t_no}", type="primary"):
                        try:
                            now_str = datetime.datetime.now(JST).strftime('%H:%M:%S')
                            update_finish_cells(t_no, True, now_str)
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = now_str
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                    c3.empty()
