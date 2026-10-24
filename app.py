import streamlit as st
import pandas as pd
import datetime
import time  # ★追加：タイムラグを調整するための機能
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


# --- アプリ全体のパスワード認証（リロード保持対応） ---
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

@st.cache_data(ttl=15)
def load_data():
    df = conn.read(worksheet="Data", ttl=0)
    
    if df is None or len(df) == 0:
        raise ValueError("データが取得できませんでした")
        
    if 'No' in df.columns:
        df['No'] = pd.to_numeric(df['No'], errors='coerce').fillna(0).astype(int)
    else:
        raise ValueError("シートに 'No' 列が存在しません")

    df['Start_Check'] = df['Start_Check'].fillna(False).astype(bool)
    df['Finish_Check'] = df['Finish_Check'].fillna(False).astype(bool)
    df['Finish_Check_Time'] = df['Finish_Check_Time'].fillna("").astype(str)
    
    if 'DNF' not in df.columns:
        df['DNF'] = False
    else:
        df['DNF'] = df['DNF'].fillna(False).astype(bool)
    
    if 'Key' not in df.columns:
        df['Key'] = ""
    if 'Value' not in df.columns:
        df['Value'] = ""
        
    df['Key'] = df['Key'].fillna("").astype(str)
    df['Value'] = df['Value'].fillna("").astype(str)
    
    return df


def safe_update_data(new_df):
    if new_df is None or len(new_df) == 0:
        st.error("データが空のため、書き込み中止")
        return False
    if 'No' not in new_df.columns:
        st.error("不正なデータ構造のため、書き込み中止")
        return False
        
    save_df = new_df.copy()
    save_df['Key'] = save_df['Key'].fillna("").astype(str)
    save_df['Value'] = save_df['Value'].fillna("").astype(str)
    save_df['Finish_Check_Time'] = save_df['Finish_Check_Time'].fillna("").astype(str)
    
    conn.update(worksheet="Data", data=save_df)
    time.sleep(2.0)  # ★超重要：Google側が最新状態に更新されるのを確実に2秒待つ
    return True


try:
    df = load_data()
    settings_dict = dict(zip(df['Key'], df['Value']))
    finish_enabled = str(settings_dict.get('finish_enabled', 'False')).lower() == 'true'
    
    start_time_str = str(settings_dict.get('start_time', ''))
    if start_time_str and start_time_str.lower() != 'nan':
        start_time_val = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
    else:
        start_time_val = None
        
except Exception as e:
    if "429" in str(e) or "RATE_LIMIT_EXCEEDED" in str(e):
        st.error("⚠️ アクセス集中によるAPI制限中です。")
        st.warning("約1分ほど待ってから再読み込みしてください。")
    else:
        st.error(f"データ読み込みエラー: {e}")
    st.stop()


# --- サイドバー：管理者設定 ---
st.sidebar.header("管理者メニュー")
admin_pass = st.sidebar.text_input("管理者パスワードを入力", type="password")
is_admin = False

# 確実な書き換え処理に変更
def upsert_setting(target_df, key, value):
    mask = target_df['Key'] == key
    if mask.any():
        target_df.loc[mask, 'Value'] = str(value)
    else:
        new_row = {c: "" for c in target_df.columns}
        new_row['Key'] = key
        new_row['Value'] = str(value)
        target_df = pd.concat([target_df, pd.DataFrame([new_row])], ignore_index=True)
    return target_df

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
            load_data.clear()
            latest_df = load_data()
            latest_df = upsert_setting(latest_df, 'finish_enabled', new_status)
            if safe_update_data(latest_df):
                load_data.clear()
                st.rerun()
        except Exception as e:
            st.sidebar.error("通信エラー")
    
    st.sidebar.subheader("⏱️ スタート時刻設定")
    if st.sidebar.button("現在時刻(JST)をスタートに設定"):
        try:
            load_data.clear()
            latest_df = load_data()
            new_time = datetime.datetime.now(JST)
            latest_df = upsert_setting(latest_df, 'start_time', new_time.strftime('%Y-%m-%d %H:%M:%S'))
            if safe_update_data(latest_df):
                load_data.clear()
                st.rerun()
        except Exception as e:
            st.sidebar.error("通信エラー")
    
    st.sidebar.markdown("---")
    default_time = start_time_val.time() if start_time_val else datetime.datetime.now(JST).time()
    manual_time = st.sidebar.time_input("手動設定 (時:分:秒)", value=default_time, step=1)
    
    if st.sidebar.button("手動入力した時刻をセット"):
        try:
            load_data.clear()
            latest_df = load_data()
            today_date = start_time_val.date() if start_time_val else datetime.datetime.now(JST).date()
            new_manual_datetime = datetime.datetime.combine(today_date, manual_time, tzinfo=JST)
            latest_df = upsert_setting(latest_df, 'start_time', new_manual_datetime.strftime('%Y-%m-%d %H:%M:%S'))
            if safe_update_data(latest_df):
                load_data.clear()
                st.rerun()
        except Exception as e:
            st.sidebar.error("通信エラー")
        
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
        load_data.clear()
        st.rerun()
        
    filter_start = st.radio("フィルター(スタート)", ["すべて", "未チェック", "チェック済"], horizontal=True, label_visibility="collapsed", key="f_start")
    
    if filter_start == "未チェック":
        view_df = df[~df['Start_Check']]
    elif filter_start == "チェック済":
        view_df = df[df['Start_Check']]
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
        col1, col2 = st.columns([1, 2.5])
        col1.markdown(f"**No.{t_no:03d}**")
        
        if row['Start_Check']:
            if is_admin:
                if col2.button("❌ 取消", key=f"start_{t_no}", type="secondary"):
                    try:
                        load_data.clear()
                        latest_df = load_data()
                        latest_df.loc[latest_df['No'] == t_no, 'Start_Check'] = False
                        if safe_update_data(latest_df):
                            load_data.clear()
                            st.rerun()
                    except Exception:
                        st.error("通信エラー")
            else:
                col2.button("✅ 済", key=f"start_{t_no}", disabled=True)
                
        else:
            if col2.button("チェック", key=f"start_{t_no}", type="primary"):
                try:
                    load_data.clear()
                    latest_df = load_data()
                    match_row = latest_df[latest_df['No'] == t_no]
                    if not match_row.empty and not match_row['Start_Check'].values[0]:
                        latest_df.loc[latest_df['No'] == t_no, 'Start_Check'] = True
                        if safe_update_data(latest_df):
                            load_data.clear()
                            st.rerun()
                    else:
                        load_data.clear()
                        st.rerun()
                except Exception:
                    st.error("通信エラー")


# ==========================================
# タブ2：ゴールチェック
# ==========================================
with tab2:
    h_col3, h_col4 = st.columns([2.5, 1])
    h_col3.markdown("#### 🏁 ゴール")
    if h_col4.button("🔄 更新", key="upd_finish"):
        load_data.clear()
        st.rerun()
    
    if not finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。")
    else:
        started_df = df[df['Start_Check']]
        
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
            
            if is_admin and (not is_finished):
                col1, col2, col3, col4 = st.columns([1, 1.8, 1.8, 2.8])
            else:
                col1, col2, col4 = st.columns([1, 2.2, 3.2])
                col3 = None
            
            col1.markdown(f"**No.{t_no:03d}**")
            
            if is_dnf:
                if is_admin:
                    if col2.button("↩️ 取消", key=f"undnf_{t_no}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            latest_df.loc[latest_df['No'] == t_no, 'DNF'] = False
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check'] = False
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check_Time'] = ""
                            if safe_update_data(latest_df):
                                load_data.clear()
                                st.rerun()
                        except Exception:
                            st.error("通信エラー")
                else:
                    col2.button("棄権済", key=f"dnf_dis_{t_no}", disabled=True)
                
                col4.error("DNF")
                
            elif is_finished:
                if is_admin:
                    if col2.button("❌ 取消", key=f"finish_cancel_{t_no}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check'] = False
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check_Time'] = ""
                            if safe_update_data(latest_df):
                                load_data.clear()
                                st.rerun()
                        except Exception:
                            st.error("通信エラー")
                else:
                    col2.button("🏁 済", key=f"finish_done_{t_no}", disabled=True)
                
                f_time_str = str(row['Finish_Check_Time'])
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
                        load_data.clear()
                        latest_df = load_data()
                        match_row = latest_df[latest_df['No'] == t_no]
                        if not match_row.empty and not match_row['Finish_Check'].values[0]:
                            now_jst = datetime.datetime.now(JST)
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check'] = True
                            latest_df.loc[latest_df['No'] == t_no, 'Finish_Check_Time'] = now_jst.strftime('%H:%M:%S')
                            if safe_update_data(latest_df):
                                load_data.clear()
                                st.rerun()
                        else:
                            load_data.clear()
                            st.rerun()
                    except Exception:
                        st.error("通信エラー")
                
                if is_admin and col3 is not None:
                    if col3.button("⚠️ 棄権", key=f"dnf_btn_{t_no}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            match_row = latest_df[latest_df['No'] == t_no]
                            if not match_row.empty and not match_row['DNF'].values[0]:
                                latest_df.loc[latest_df['No'] == t_no, 'DNF'] = True
                                latest_df.loc[latest_df['No'] == t_no, 'Finish_Check'] = True
                                latest_df.loc[latest_df['No'] == t_no, 'Finish_Check_Time'] = ""
                                if safe_update_data(latest_df):
                                    load_data.clear()
                                    st.rerun()
                            else:
                                load_data.clear()
                                st.rerun()
                        except Exception:
                            st.error("通信エラー")
