import streamlit as st
import pandas as pd
import datetime
import time
from zoneinfo import ZoneInfo
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

# --- 日本時間のタイムゾーン設定 ---
JST = ZoneInfo("Asia/Tokyo")

# --- スマホでも強制的に横並び（1段）を維持するCSS ---
st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    align-items: center !important;
    gap: 6px !important;
}
div[data-testid="column"] {
    min-width: 0 !important;
    margin-bottom: 0px !important;
}
div[data-testid="column"] button {
    padding: 4px 6px !important;
    font-size: 0.85rem !important;
    width: 100% !important;
}
div[data-testid="column"] div[data-testid="stAlert"] {
    padding: 4px 8px !important;
    margin: 0px !important;
    font-size: 0.8rem !important;
}
</style>
""", unsafe_allow_html=True)


# --- アプリ全体のパスワード認証 ---
def check_password():
    query_auth = st.query_params.get("auth")
    if query_auth == st.secrets["app_password"]:
        return True

    def password_entered():
        if st.session_state["app_pwd"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.query_params["auth"] = st.secrets["app_password"]
            del st.session_state["app_pwd"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("アプリ利用パスワード", type="password", on_change=password_entered, key="app_pwd")
    if st.session_state.get("password_correct") is False:
        st.error("パスワードが正しくありません")
    return False

if not check_password():
    st.stop()


# --- スプレッドシート接続 ---
conn = st.connection("gsheets", type=GSheetsConnection)

# ★ ローカル一時記憶（即時UI反映用）
if "local_updates" not in st.session_state:
    st.session_state.local_updates = {}

# ★ エラー耐性用バックアップ
if "last_valid_df" not in st.session_state:
    st.session_state.last_valid_df = None

# ★ 全ユーザー共有の更新インターバル管理（5秒制限ガード）
@st.cache_resource
def get_global_sync_manager():
    return {"last_read_time": 0.0}

global_sync = get_global_sync_manager()


@st.cache_data(ttl=15)
def load_data():
    df = conn.read(worksheet="Data", ttl=0)
    
    if df is None or len(df) == 0:
        raise ValueError("データが取得できませんでした")
        
    # ★【安全装置】列の並び順チェック（ピンポイント更新によるデータ破壊を防ぐ）
    expected_cols = ['No', 'Start_Check', 'Finish_Check', 'Finish_Check_Time', 'DNF', 'DNS', 'Key', 'Value']
    current_cols = list(df.columns)
    
    # 最初の8列が期待通りの順番かチェック
    if current_cols[:8] != expected_cols:
        st.error("⚠️ スプレッドシートの列構成が正しくありません。")
        st.warning("【重要】ピンポイント更新を行うため、A列〜H列を以下の順序に修正してください。\n\n"
                   "1. `No`\n2. `Start_Check`\n3. `Finish_Check`\n4. `Finish_Check_Time`\n5. `DNF`\n**6. `DNS` （※今回追加）**\n7. `Key`\n8. `Value`")
        st.info("※E列(DNF)とF列(Key)の間に新しい列を挿入し、1行目に「DNS」と入力してください。")
        st.stop()
        
    if 'No' in df.columns:
        df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)

    df['Start_Check'] = df['Start_Check'].fillna(False).astype(bool)
    df['Finish_Check'] = df['Finish_Check'].fillna(False).astype(bool)
    df['Finish_Check_Time'] = df['Finish_Check_Time'].fillna("").astype(str)
    df['DNF'] = df['DNF'].fillna(False).astype(bool)
    df['DNS'] = df['DNS'].fillna(False).astype(bool)
    df['Key'] = df['Key'].fillna("").astype(str).str.strip()
    df['Value'] = df['Value'].fillna("").astype(str).str.strip()
    
    global_sync["last_read_time"] = time.time()
    return df


# --- セル単位ピンポイント更新関数群 ---
def get_worksheet():
    client = conn._instance
    spreadsheet = client.open_by_url(st.secrets.connections.gsheets.spreadsheet)
    return spreadsheet.worksheet("Data")

def update_start_cell(no: int, checked: bool):
    """Start_Check（B列）のみをピンポイント更新"""
    ws = get_worksheet()
    row = no + 1
    ws.update_cell(row, 2, checked)
    return True

def update_dns_cells(no: int, dns: bool):
    """DNS登録・取消（B列のStart_Check=False、F列のDNSを更新）"""
    ws = get_worksheet()
    row = no + 1
    # B列: Start_Check を False にリセット
    ws.update_cell(row, 2, False)
    # F列: DNS を更新 (6列目)
    ws.update_cell(row, 6, dns)
    return True

def update_finish_cells(no: int, checked: bool, time_str: str):
    """Finish_Check（C列）と Finish_Check_Time（D列）のみをピンポイント更新"""
    ws = get_worksheet()
    row = no + 1
    ws.update(f"C{row}:D{row}", [[checked, time_str]])
    return True

def update_dnf_cells(no: int, dnf: bool, finish_check: bool, time_str: str):
    """DNF関連（C列〜E列）のみをピンポイント更新"""
    ws = get_worksheet()
    row = no + 1
    ws.update(f"C{row}:E{row}", [[finish_check, time_str, dnf]])
    return True

def update_setting_cell(key: str, value: str):
    """設定値（Key/Value列）をピンポイント更新"""
    ws = get_worksheet()
    headers = ws.row_values(1)
    key_col_idx = headers.index('Key') + 1 if 'Key' in headers else 7
    val_col_idx = key_col_idx + 1

    cell = ws.find(key, in_column=key_col_idx)
    if cell:
        ws.update_cell(cell.row, val_col_idx, str(value))
    else:
        all_keys = ws.col_values(key_col_idx)
        next_row = len(all_keys) + 1
        ws.update_cell(next_row, key_col_idx, key)
        ws.update_cell(next_row, val_col_idx, str(value))
    return True


# --- データ取得 & エラー耐性 ---
api_limit_mode = False
try:
    df = load_data()
    st.session_state.last_valid_df = df.copy()
except Exception:
    if st.session_state.last_valid_df is not None:
        df = st.session_state.last_valid_df.copy()
        api_limit_mode = True
    else:
        st.error("⚠️ アクセス集中によるAPI制限中です。約1分待ってから再読み込みしてください。")
        st.stop()

settings_dict = dict(zip(df['Key'], df['Value']))
finish_enabled = str(settings_dict.get('finish_enabled', 'False')).strip().lower() == 'true'

start_time_str = str(settings_dict.get('start_time', ''))
if start_time_str and start_time_str.lower() != 'nan':
    start_time_val = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
else:
    start_time_val = None

if api_limit_mode:
    st.warning("⚠️ API通信制限中のため、直前のデータを表示しています（数分後に自動復旧します）")


# --- サイドバー：管理者設定 ---
st.sidebar.header("管理者メニュー")
admin_pass = st.sidebar.text_input("管理者パスワードを入力", type="password")
is_admin = False

if admin_pass == st.secrets["admin_password"]:
    st.sidebar.success("管理者認証成功")
    is_admin = True
    
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
        except Exception:
            st.toast("⚠️ 通信制限中です。少し待ってから再度お試しください", icon="⚠️")
    
    st.sidebar.subheader("⏱️ スタート時刻設定")
    if st.sidebar.button("現在時刻(JST)をスタートに設定"):
        try:
            new_time = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
            update_setting_cell('start_time', new_time)
            time.sleep(2.0)
            load_data.clear()
            st.rerun()
        except Exception:
            st.toast("⚠️ 通信制限中です。少し待ってから再度お試しください", icon="⚠️")
    
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
        except Exception:
            st.toast("⚠️ 通信制限中です。少し待ってから再度お試しください", icon="⚠️")
        
    st.sidebar.markdown("---")
    if start_time_val:
        st.sidebar.info(f"設定済:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")


# --- メイン画面 ---
tab1, tab2 = st.tabs(["スタートチェック", "ゴールチェック"])

# ==========================================
# タブ1：スタートチェック
# ==========================================
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
    
    if filter_start == "未チェック":
        view_df = df[(~df['Start_Check']) & (~df['DNS'])]
    elif filter_start == "チェック済":
        view_df = df[df['Start_Check']]
    elif filter_start == "DNS(棄権)":
        view_df = df[df['DNS']]
    else:
        view_df = df
        
    if not df.empty:
        max_no = int(df['No'].max())
        range_options = ["すべて"]
        for i in range(1, max_no + 1, 10):
            range_options.append(f"{i}～{i+9}")
            
        selected_range_start = st.radio("番号帯(スタート)", range_options, horizontal=True, label_visibility="collapsed", key="r_start")
        
        if selected_range_start != "すべて":
            s_num, e_num = map(int, selected_range_start.split("～"))
            view_df = view_df[(view_df['No'] >= s_num) & (view_df['No'] <= e_num)]

    for _, row in view_df.iterrows():
        t_no = int(row['No'])
        
        # ローカル一時記憶の優先適用
        is_start = row['Start_Check']
        is_dns = row['DNS']
        if f"start_{t_no}" in st.session_state.local_updates:
            is_start = st.session_state.local_updates[f"start_{t_no}"]
        if f"dns_{t_no}" in st.session_state.local_updates:
            is_dns = st.session_state.local_updates[f"dns_{t_no}"]
        
        # カラム配置（管理者かつ未スタートの場合はDNS登録ボタン用カラムを追加）
        if is_admin and (not is_start) and (not is_dns):
            col1, col2, col3 = st.columns([1, 1.8, 1.8])
        else:
            col1, col2 = st.columns([1, 2.5])
            col3 = None

        col1.markdown(f"**No.{t_no:03d}**")
        
        # 1. DNS（出走前棄権）状態
        if is_dns:
            if is_admin:
                if col2.button("↩️ 取消", key=f"dns_cancel_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, False)
                        st.session_state.local_updates[f"dns_{t_no}"] = False
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception:
                        st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
            else:
                col2.button("🚫 DNS", key=f"dns_done_{t_no}", disabled=True)
                
        # 2. スタートチェック済状態
        elif is_start:
            if is_admin:
                if col2.button("❌ 取消", key=f"start_cancel_{t_no}", type="secondary"):
                    try:
                        update_start_cell(t_no, False)
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception:
                        st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
            else:
                col2.button("✅ 済", key=f"start_done_{t_no}", disabled=True)
                
        # 3. 未チェック状態
        else:
            if col2.button("チェック", key=f"start_btn_{t_no}", type="primary"):
                try:
                    update_start_cell(t_no, True)
                    st.session_state.local_updates[f"start_{t_no}"] = True
                    st.rerun()
                except Exception:
                    st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
            
            # 管理者限定：出走前棄権（DNS）ボタン
            if is_admin and col3 is not None:
                if col3.button("🚫 棄権", key=f"dns_btn_{t_no}", type="secondary"):
                    try:
                        update_dns_cells(t_no, True)
                        st.session_state.local_updates[f"dns_{t_no}"] = True
                        st.session_state.local_updates[f"start_{t_no}"] = False
                        st.rerun()
                    except Exception:
                        st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")


# ==========================================
# タブ2：ゴールチェック
# ==========================================
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
        # DNS（出走前棄権）はスタートしていないためゴールチェックから除外
        started_df = df[df['Start_Check'] & (~df['DNS'])]
        
        filter_finish = st.radio("フィルター(ゴール)", ["すべて", "未ゴール", "ゴール済 (DNF含)"], horizontal=True, label_visibility="collapsed", key="f_finish")
        
        if filter_finish == "未ゴール":
            view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済 (DNF含)":
            view_df2 = started_df[started_df['Finish_Check']]
        else:
            view_df2 = started_df
            
        if not df.empty:
            max_no2 = int(df['No'].max())
            range_options2 = ["すべて"]
            for i in range(1, max_no2 + 1, 10):
                range_options2.append(f"{i}～{i+9}")
                
            selected_range_finish = st.radio("番号帯(ゴール)", range_options2, horizontal=True, label_visibility="collapsed", key="r_finish")
            
            if selected_range_finish != "すべて":
                s_num, e_num = map(int, selected_range_finish.split("～"))
                view_df2 = view_df2[(view_df2['No'] >= s_num) & (view_df2['No'] <= e_num)]
            
        for _, row in view_df2.iterrows():
            t_no = int(row['No'])
            
            is_dnf = row['DNF']
            is_finished = row['Finish_Check']
            f_time_str = str(row['Finish_Check_Time'])
            
            if f"dnf_{t_no}" in st.session_state.local_updates:
                is_dnf = st.session_state.local_updates[f"dnf_{t_no}"]
            if f"finish_{t_no}" in st.session_state.local_updates:
                is_finished = st.session_state.local_updates[f"finish_{t_no}"]
            if f"time_{t_no}" in st.session_state.local_updates:
                f_time_str = st.session_state.local_updates[f"time_{t_no}"]

            if is_admin and (not is_finished):
                col1, col2, col3, col4 = st.columns([1, 1.8, 1.8, 2.8])
            else:
                col1, col2, col4 = st.columns([1, 2.2, 3.2])
                col3 = None
            
            col1.markdown(f"**No.{t_no:03d}**")
            
            if is_dnf:
                if is_admin:
                    if col2.button("↩️ 取消", key=f"undnf_cancel_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, False, False, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = False
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception:
                            st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
                else:
                    col2.button("棄権済", key=f"dnf_done_{t_no}", disabled=True)
                
                col4.error("DNF")
                
            elif is_finished:
                if is_admin:
                    if col2.button("❌ 取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            update_finish_cells(t_no, False, "")
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception:
                            st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
                else:
                    col2.button("🏁 済", key=f"finish_done_{t_no}", disabled=True)
                
                if start_time_val and f_time_str and f_time_str != "nan":
                    try:
                        f_time_obj = datetime.datetime.strptime(f_time_str, '%H:%M:%S').time()
                        f_datetime = datetime.datetime.combine(datetime.date.today(), f_time_obj, tzinfo=JST)
                        net_time = f_datetime - start_time_val
                        time_display = f"{f_time_str} ({str(net_time).split('.')[0]})"
                    except Exception:
                        time_display = f"{f_time_str}"
                else:
                    time_display = f"{f_time_str}"
                    
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
                    except Exception:
                        st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
                
                # 管理者限定：競技途中棄権（DNF）ボタン
                if is_admin and col3 is not None:
                    if col3.button("⚠️ 棄権", key=f"dnf_btn_{t_no}", type="secondary"):
                        try:
                            update_dnf_cells(t_no, True, True, "")
                            st.session_state.local_updates[f"dnf_{t_no}"] = True
                            st.session_state.local_updates[f"finish_{t_no}"] = True
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception:
                            st.toast("⚠️ 通信制限中です。少し待ってから再度押してください", icon="⚠️")
