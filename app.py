import streamlit as st
import pandas as pd
import datetime
import time
from zoneinfo import ZoneInfo
import gspread

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

JST = ZoneInfo("Asia/Tokyo")

st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] { display: flex !important; flex-direction: row !important; align-items: center !important; gap: 6px !important; }
div[data-testid="column"] { min-width: 0 !important; margin-bottom: 0px !important; }
div[data-testid="column"] button { padding: 4px 6px !important; font-size: 0.85rem !important; width: 100% !important; }
div[data-testid="column"] div[data-testid="stAlert"] { padding: 4px 8px !important; margin: 0px !important; font-size: 0.8rem !important; }
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
    
    # ★ 管理者メニューから抜けるボタン
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
            
    # ★ 手動時刻入力の復活
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

    # ★ 設定時刻の表示（未設定対応）
    st.sidebar.markdown("---")
    if start_time_val:
        st.sidebar.info(f"設定済:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")
    else:
        st.sidebar.info("設定済:\n未設定")


# ==========================================
# メイン画面（タブ）
# ==========================================
tab1, tab2 = st.tabs(["スタートチェック", "ゴールチェック"])

with tab1:
    h_col1, h_col2 = st.columns([2.5, 1])
    h_col1.markdown("#### 🚩 スタート")
    
    if h_col2.button("🔄 更新", key="upd_start"):
        st.session_state.local_updates.clear()
        now_ts = time.time()
        if now_ts - global_sync["last_read_time"] >= 5.0:
            load_data.clear()
            st.rerun()
        else:
            st.toast("⏳ 直前に最新化されたため、最新キャッシュを表示しました", icon="ℹ️")
            st.rerun()
        
    filter_start = st.radio("フィルター(スタート)", ["すべて", "未チェック", "チェック済", "DNS(棄権)"], horizontal=True, label_visibility="collapsed", key="f_start")
    
    if filter_start == "未チェック": view_df = df[(~df['Start_Check']) & (~df['DNS'])]
    elif filter_start == "チェック済": view_df = df[df['Start_Check']]
    elif filter_start == "DNS(棄権)": view_df = df[df['DNS']]
    else: view_df = df
        
    if not df.empty:
        max_no = int(df['No'].max())
        range_options = ["すべて"]
        for i in range(1, max_no + 1, 10): range_options.append(f"{i}～{i+9}")
            
        selected_range_start = st.radio("番号帯(スタート)", range_options, horizontal=True, label_visibility="collapsed", key="r_start")
        if selected_range_start != "すべて":
            s_num, e_num = map(int, selected_range_start.split("～"))
            view_df = view_df[(view_df['No'] >= s_num) & (view_df['No'] <= e_num)]

    for _, row in view_df.iterrows():
        t_no = int(row['No'])
        
        is_start = row['Start_Check']
        is_dns = row['DNS']
        if f"start_{t_no}" in st.session_state.local_updates: is_start = st.session_state.local_updates[f"start_{t_no}"]
        if f"dns_{t_no}" in st.session_state.local_updates: is_dns = st.session_state.local_updates[f"dns_{t_no}"]
        
        if is_admin:
            col1, col2, col3 = st.columns([1, 1.5, 3.0])
        else:
            col1, col2 = st.columns([1, 2.5])
            col3 = None

        col1.markdown(f"**No.{t_no:03d}**")
        
        if is_dns:
            col2.button("🚫 DNS", key=f"dns_done_{t_no}", disabled=True)
            if is_admin:
                if col3.button("↩️ 棄権取消", key=f"dns_cancel_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, False)
                        st.session_state.local_updates[f"dns_{t_no}"] = False
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                
        elif is_start:
            col2.button("✅ 済", key=f"start_done_{t_no}", disabled=True)
            if is_admin:
                if col3.button("❌ スタートチェック取消", key=f"start_cancel_{t_no}", type="secondary"):
                    try:
                        update_start_cell(t_no, False)
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                
        else:
            if col2.button("チェック", key=f"start_btn_{t_no}", type="primary"):
                try:
                    update_start_cell(t_no, True)
                    st.session_state.local_updates[f"start_{t_no}"] = True
                    st.rerun()
                except Exception as e: st.error(f"エラー: {e}")
            
            if is_admin and col3 is not None:
                if col3.button("🚫 棄権", key=f"dns_btn_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, True)
                        st.session_state.local_updates[f"dns_{t_no}"] = True
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")


with tab2:
    h_col3, h_col4 = st.columns([2.5, 1])
    h_col3.markdown("#### 🏁 ゴール")
    
    if h_col4.button("🔄 更新", key="upd_finish"):
        st.session_state.local_updates.clear()
        now_ts = time.time()
        if now_ts - global_sync["last_read_time"] >= 5.0:
            load_data.clear()
            st.rerun()
        else:
            st.toast("⏳ 直前に最新化されたため、最新キャッシュを表示しました", icon="ℹ️")
            st.rerun()
    
    if not finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。")
    else:
        started_df = df[df['Start_Check'] & (~df['DNS'])]
        filter_finish = st.radio("フィルター(ゴール)", ["すべて", "未ゴール", "ゴール済 (DNF含)"], horizontal=True, label_visibility="collapsed", key="f_finish")
        
        if filter_finish == "未ゴール": view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済 (DNF含)": view_df2 = started_df[started_df['Finish_Check']]
        else: view_df2 = started_df
            
        if not df.empty:
            max_no2 = int(df['No'].max())
            range_options2 = ["すべて"]
            for i in range(1, max_no2 + 1, 10): range_options2.append(f"{i}～{i+9}")
                
            selected_range_finish = st.radio("番号帯(ゴール)", range_options2, horizontal=True, label_visibility="collapsed", key="r_finish")
            if selected_range_finish != "すべて":
                s_num, e_num = map(int, selected_range_finish.split("～"))
                view_df2 = view_df2[(view_df2['No'] >= s_num) & (view_df2['No'] <= e_num)]
            
        for _, row in view_df2.iterrows():
            t_no = int(row['No'])
            
            is_dnf = row['DNF']
            is_finished = row['Finish_Check']
            f_time_str = str(row['Finish_Check_Time'])
            
            if f"dnf_{t_no}" in st.session_state.local_updates: is_dnf = st.session_state.local_updates[f"dnf_{t_no}"]
            if f"finish_{t_no}" in st.session_state.local_updates: is_finished = st.session_state.local_updates[f"finish_{t_no}"]
            if f"time_{t_no}" in st.session_state.local_updates: f_time_str = st.session_state.local_updates[f"time_{t_no}"]

            if is_admin:
                col1, col2, col3, col4 = st.columns([1, 1.5, 2.5, 2.5])
            else:
                col1, col2, col4 = st.columns([1, 2.0, 3.0])
                col3 = None
            
            col1.markdown(f"**No.{t_no:03d}**")
            
            if is_dnf:
                col2.button("棄権済", key=f"dnf_done_{t_no}", disabled=True)
                if is_admin:
                    if col3.button("↩️ DNF取消", key=f"undnf_cancel_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, False, False, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = False
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                col4.error("DNF")
                
            elif is_finished:
                col2.button("🏁 済", key=f"finish_done_{t_no}", disabled=True)
                if is_admin:
                    if col3.button("❌ ゴール取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            update_finish_cells(t_no, False, "")
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                
                if start_time_val and f_time_str and f_time_str != "nan":
                    try:
                        f_time_obj = datetime.datetime.strptime(f_time_str, '%H:%M:%S').time()
                        f_datetime = datetime.datetime.combine(datetime.date.today(), f_time_obj, tzinfo=JST)
                        net_time = f_datetime - start_time_val
                        time_display = f"{f_time_str} ({str(net_time).split('.')[0]})"
                    except Exception: time_display = f"{f_time_str}"
                else: time_display = f"{f_time_str}"
                col4.success(time_display)

            else:
                if col2.button("🏁 ゴール", key=f"finish_btn_{t_no}", type="primary"):
                    try:
                        now_jst = datetime.datetime.now(JST)
                        now_str = now_jst.strftime('%H:%M:%S')
                        update_finish_cells(t_no, True, now_str)
                        st.session_state.local_updates[f"finish_{t_no}"] = True
                        st.session_state.local_updates[f"time_{t_no}"] = now_str
                        st.rerun()
                    except Exception as e: st.error(f"エラー: {e}")
                
                if is_admin and col3 is not None:
                    if col3.button("⚠️ 棄権", key=f"dnf_btn_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, True, True, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = True
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
