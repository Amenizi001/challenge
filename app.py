import streamlit as st
import pandas as pd
import datetime
import time
from zoneinfo import ZoneInfo
import gspread

st.set_page_config(page_title="マラソン大会 チェックシステム", layout="centered")

JST = ZoneInfo("Asia/Tokyo")

# --- UI最適化CSS（スマホ強制3列横並び ＆ 文字サイズ拡大） ---
st.markdown("""
<style>
/* 1. 画面全体の余白調整と横スクロール防止 */
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 2rem !important;
    padding-left: 0.4rem !important;
    padding-right: 0.4rem !important;
    max-width: 100% !important;
    overflow-x: hidden !important;
}
header[data-testid="stHeader"] {
    display: none !important;
}

/* 2. スマホでの横並びカラムの縦落ち（幅100%化）を強制解除 */
div[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 4px !important;
    margin-bottom: 4px !important;
    width: 100% !important;
}

/* 3列カラムの横幅を均等に強制固定 */
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
    min-width: 0 !important;
    flex: 1 1 0% !important;
    margin-bottom: 0px !important;
}

/* 3. ボタンのスタイル（文字サイズを約2段階アップ: 0.75rem -> 0.95rem） */
div[data-testid="column"] button {
    padding: 2px 1px !important;
    font-size: 0.95rem !important;
    font-weight: bold !important;
    line-height: 1.15 !important;
    width: 100% !important;
    min-height: 44px !important;
    height: 44px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    white-space: normal !important;
    text-align: center !important;
    box-sizing: border-box !important;
}

/* 4. ゴール済カード（文字サイズを約2段階アップ） */
.finish-card {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 5px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    box-sizing: border-box;
}
.finish-no {
    font-weight: bold;
    color: #212529;
    font-size: 1.05rem; /* 拡大 */
}
.finish-time {
    color: #0f5132;
    font-weight: bold;
    font-size: 0.95rem; /* 拡大 */
}
.finish-clock {
    color: #6c757d;
    font-size: 0.85rem; /* 拡大 */
}
.dnf-card {
    background-color: #fff3cd;
    border: 1px solid #ffe69c;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 5px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: #664d03;
    font-weight: bold;
    font-size: 0.95rem; /* 拡大 */
    width: 100%;
    box-sizing: border-box;
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
    t_col1.markdown("<h4 style='margin:0; padding:2px 0;'>🚩 スタート</h4>", unsafe_allow_html=True)
    if t_col2.button("🔄 更新", key="upd_start"):
        st.session_state.local_updates.clear()
        if time.time() - global_sync["last_read_time"] >= 5.0:
            load_data.clear()
            st.rerun()
        else:
            st.toast("⏳ 直前に最新化されたため、最新キャッシュを表示しました", icon="ℹ️")
            st.rerun()
        
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

    # 1. 未チェック（上段に3列グリッド表示）
    uncheck_df = view_df[(~view_df['Start_Check']) & (~view_df['DNS'])].sort_values(by="No")
    if not uncheck_df.empty and filter_start in ["すべて", "未チェック"]:
        st.caption("【未チェック】タップしてスタート完了")
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

    # 管理者用：未チェックチームの棄権(DNS)登録
    if is_admin and not uncheck_df.empty and filter_start in ["すべて", "未チェック"]:
        st.caption("【管理者用：出走前棄権(DNS)登録】")
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

    # 2. チェック済み・DNSのチーム（下段に昇順表示）
    done_df = view_df[view_df['Start_Check'] | view_df['DNS']].sort_values(by="No")
    if not done_df.empty and filter_start in ["すべて", "チェック済", "DNS(棄権)"]:
        if filter_start == "すべて":
            st.markdown("---")
            st.caption("【スタート済・棄権一覧】")
        for _, row in done_df.iterrows():
            t_no = int(row['No'])
            no_str = f"{t_no:03d}"
            is_start = row['Start_Check']
            is_dns = row['DNS']

            if is_dns:
                if is_admin:
                    if st.button(f"↩️ {no_str}:棄権取消す", key=f"dns_cancel_{t_no}", type="secondary"):
                        try:
                            update_dns_cells(t_no, False)
                            st.session_state.local_updates[f"dns_{t_no}"] = False
                            st.session_state.local_updates[f"start_{t_no}"] = False
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                else:
                    st.button(f"{no_str}:DNS(棄権)", key=f"dns_done_{t_no}", disabled=True)
            elif is_start:
                if is_admin:
                    if st.button(f"❌ {no_str}:スタートチェック取消す", key=f"start_cancel_{t_no}", type="secondary"):
                        try:
                            update_start_cell(t_no, False)
                            st.session_state.local_updates[f"start_{t_no}"] = False
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                else:
                    st.button(f"{no_str}:済", key=f"start_done_{t_no}", disabled=True)


# --- タブ2：ゴールチェック ---
with tab2:
    t_col3, t_col4 = st.columns([3, 1])
    t_col3.markdown("<h4 style='margin:0; padding:2px 0;'>🏁 ゴール</h4>", unsafe_allow_html=True)
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
            view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済 (DNF含)":
            view_df2 = started_df[started_df['Finish_Check']]
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

        # --- ① 最上段：未ゴールチームの「001:ゴール」ボタン群（3列グリッド） ---
        unfinish_df = view_df2[~view_df2['Finish_Check']].sort_values(by="No")
        if not unfinish_df.empty and filter_finish in ["すべて", "未ゴール"]:
            st.caption("【未ゴール】タップしてゴール完了")
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

        # --- ② 中段：ゴール済みチームの一覧（1行1チーム表示・番号昇順） ---
        finished_df = view_df2[view_df2['Finish_Check'] & (~view_df2['DNF'])].sort_values(by="No")
        if not finished_df.empty and filter_finish in ["すべて", "ゴール済 (DNF含)"]:
            if filter_finish == "すべて":
                st.markdown("---")
            st.caption("【ゴール済みチーム一覧】")
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

                time_info = f"<span class='finish-time'>タイム: {net_jp}</span> <span class='finish-clock'>(着 {time_jp})</span>" if net_jp else f"<span class='finish-clock'>着 {time_jp}</span>"
                card_html = f"<div class='finish-card'><span class='finish-no'>No.{no_str}</span><span>{time_info}</span></div>"

                if is_admin:
                    col_card, col_btn = st.columns([3, 1])
                    col_card.markdown(card_html, unsafe_allow_html=True)
                    if col_btn.button("❌ ゴール取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            update_finish_cells(t_no, False, "")
                            st.session_state.local_updates[f"finish_{t_no}"] = False
                            st.session_state.local_updates[f"time_{t_no}"] = ""
                            st.rerun()
                        except Exception as e: st.error(f"エラー: {e}")
                else:
                    st.markdown(card_html, unsafe_allow_html=True)

        # --- ③ 下段（管理者限定）：未ゴールチームの「001:棄権(DNF)」ボタン群（3列グリッド） ---
        if is_admin and not unfinish_df.empty and filter_finish in ["すべて", "未ゴール"]:
            st.markdown("---")
            st.caption("【管理者用：途中棄権(DNF)登録】タップしてDNF登録")
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

        # --- ④ 最下段：すでにDNF（途中棄権）済みのチーム一覧 ---
        dnf_df = view_df2[view_df2['DNF']].sort_values(by="No")
        if not dnf_df.empty and filter_finish in ["すべて", "ゴール済 (DNF含)"]:
            st.markdown("---")
            st.caption("【途中棄権(DNF)一覧】")
            for _, row in dnf_df.iterrows():
                t_no = int(row['No'])
                no_str = f"{t_no:03d}"
                if is_admin:
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
                else:
                    st.markdown(f"<div class='dnf-card'><span>No.{no_str}</span><span>DNF (途中棄権)</span></div>", unsafe_allow_html=True)
