import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="マラソン大会 チェックシステム")

# --- 日本時間のタイムゾーン設定 ---
JST = ZoneInfo("Asia/Tokyo")

# --- アプリ全体のパスワード認証 ---
def check_password():
    def password_entered():
        if st.session_state["app_pwd"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["app_pwd"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("アプリの利用パスワードを入力してください", type="password", on_change=password_entered, key="app_pwd")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("アプリの利用パスワードを入力してください", type="password", on_change=password_entered, key="app_pwd")
        st.error("パスワードが正しくありません")
        return False
    return True

if not check_password():
    st.stop()


# --- スプレッドシート接続 ---
conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# データ読み込み関数（1シート化で通信量を極小化）
# ==========================================
@st.cache_data(ttl=15)
def load_data():
    """参加者データと設定値(F列/G列)を同時に読み込む"""
    df = conn.read(worksheet="Data", ttl=15)
    
    # 参加者データ側の型整形
    df['Start_Check'] = df['Start_Check'].fillna(False).astype(bool)
    df['Finish_Check'] = df['Finish_Check'].fillna(False).astype(bool)
    df['Finish_Check_Time'] = df['Finish_Check_Time'].fillna("").astype(str)
    
    # DNF列の型整形（存在しない場合は自動生成）
    if 'DNF' not in df.columns:
        df['DNF'] = False
    else:
        df['DNF'] = df['DNF'].fillna(False).astype(bool)
    
    # 設定値側(F/G列)の型整形
    if 'Key' not in df.columns:
        df['Key'] = ""
    if 'Value' not in df.columns:
        df['Value'] = ""
        
    df['Key'] = df['Key'].fillna("").astype(str)
    df['Value'] = df['Value'].fillna("").astype(str)
    
    return df


# --- データの読み込みと設定値の抽出 ---
try:
    df = load_data()
    
    # F列(Key)とG列(Value)から設定辞書を作成
    settings_dict = dict(zip(df['Key'], df['Value']))
    finish_enabled = str(settings_dict.get('finish_enabled', 'False')).lower() == 'true'
    
    start_time_str = str(settings_dict.get('start_time', ''))
    if start_time_str and start_time_str.lower() != 'nan':
        start_time_val = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
    else:
        start_time_val = None
        
except Exception as e:
    if "429" in str(e) or "RATE_LIMIT_EXCEEDED" in str(e):
        st.error("⚠️ アクセスが集中しています（API通信制限）。")
        st.warning("約1分ほど待ってから、ブラウザをリロード（再読み込み）してください。")
    else:
        st.error(f"スプレッドシートの読み込みエラー: {e}")
    st.stop()


# --- サイドバー：管理者設定 ---
st.sidebar.header("管理者メニュー")
admin_pass = st.sidebar.text_input("管理者パスワードを入力", type="password")

is_admin = False

if admin_pass == st.secrets["admin_password"]:
    st.sidebar.success("管理者認証成功")
    is_admin = True
    
    st.sidebar.subheader("🏁 ゴールチェック設定")
    new_finish_enabled = st.sidebar.checkbox(
        "ゴールチェック機能を一般開放する", 
        value=finish_enabled
    )
    
    if new_finish_enabled != finish_enabled:
        try:
            load_data.clear()
            latest_df = load_data()
            latest_df.loc[latest_df['Key'] == 'finish_enabled', 'Value'] = str(new_finish_enabled)
            conn.update(worksheet="Data", data=latest_df)
            st.rerun()
        except Exception:
            st.sidebar.error("通信が混み合っています。少し待ってから再度お試しください。")
    
    st.sidebar.subheader("⏱️ スタート時刻設定")
    
    if st.sidebar.button("現在時刻(JST)をスタートに設定"):
        try:
            load_data.clear()
            latest_df = load_data()
            new_time = datetime.datetime.now(JST)
            latest_df.loc[latest_df['Key'] == 'start_time', 'Value'] = new_time.strftime('%Y-%m-%d %H:%M:%S')
            conn.update(worksheet="Data", data=latest_df)
            st.rerun()
        except Exception:
            st.sidebar.error("エラー: 数秒待ってから再度お試しください。")
    
    st.sidebar.markdown("---")
    
    st.sidebar.write("または手動で設定：")
    default_time = start_time_val.time() if start_time_val else datetime.datetime.now(JST).time()
    manual_time = st.sidebar.time_input("時刻を入力 (時:分:秒)", value=default_time, step=1)
    
    if st.sidebar.button("手動入力した時刻をセット"):
        try:
            load_data.clear()
            latest_df = load_data()
            today_date = start_time_val.date() if start_time_val else datetime.datetime.now(JST).date()
            new_manual_datetime = datetime.datetime.combine(today_date, manual_time, tzinfo=JST)
            latest_df.loc[latest_df['Key'] == 'start_time', 'Value'] = new_manual_datetime.strftime('%Y-%m-%d %H:%M:%S')
            conn.update(worksheet="Data", data=latest_df)
            st.rerun()
        except Exception:
            st.sidebar.error("エラー: 数秒待ってから再度お試しください。")
        
    st.sidebar.markdown("---")
    
    if start_time_val:
        st.sidebar.info(f"設定済スタート時刻:\n{start_time_val.strftime('%Y/%m/%d %H:%M:%S')}")
    else:
        st.sidebar.warning("スタート時刻：未設定")


# --- メイン画面：タブ切り替え ---
st.title("マラソン大会 チェックシステム")
tab1, tab2 = st.tabs(["スタートチェック", "ゴールチェック"])

# ==========================================
# タブ1：スタートチェック
# ==========================================
with tab1:
    st.header("スタートライン チェック")
    filter_start = st.radio("表示フィルター (スタート)", ["すべて", "未チェック", "チェック済み"], horizontal=True)
    
    if filter_start == "未チェック":
        view_df = df[~df['Start_Check']]
    elif filter_start == "チェック済み":
        view_df = df[df['Start_Check']]
    else:
        view_df = df
        
    st.write(f"表示件数: {len(view_df)} 件")
    
    for index, row in view_df.iterrows():
        col1, col2 = st.columns([1, 4])
        col1.markdown(f"**No: {row['No']}**")
        
        # チェック済みの場合
        if row['Start_Check']:
            if is_admin:
                if col2.button("❌ 取消", key=f"start_{row['No']}", type="secondary"):
                    try:
                        load_data.clear()
                        latest_df = load_data()
                        latest_df.at[index, 'Start_Check'] = False
                        conn.update(worksheet="Data", data=latest_df)
                        st.rerun()
                    except Exception:
                        st.error("通信エラー：アクセス集中。数秒待ってからもう一度押してください。")
            else:
                col2.button("✅ チェック済", key=f"start_{row['No']}", disabled=True)
                
        # 未チェックの場合
        else:
            if col2.button("✅ チェック", key=f"start_{row['No']}", type="primary"):
                try:
                    load_data.clear()
                    latest_df = load_data()
                    if not latest_df.at[index, 'Start_Check']:
                        latest_df.at[index, 'Start_Check'] = True
                        conn.update(worksheet="Data", data=latest_df)
                    st.rerun()
                except Exception:
                    st.error("通信エラー：アクセス集中。数秒待ってからもう一度押してください。")


# ==========================================
# タブ2：ゴールチェック
# ==========================================
with tab2:
    st.header("ゴール チェック")
    
    if not finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。（管理者が開放するまでお待ちください）")
    else:
        started_df = df[df['Start_Check']]
        filter_finish = st.radio("表示フィルター (ゴール)", ["すべて", "未ゴール", "ゴール済み (DNF含む)"], horizontal=True)
        
        if filter_finish == "未ゴール":
            view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済み (DNF含む)":
            view_df2 = started_df[started_df['Finish_Check']]
        else:
            view_df2 = started_df
            
        st.write(f"表示件数: {len(view_df2)} 件")
        
        for index, row in view_df2.iterrows():
            col1, col2, col3, col4 = st.columns([1, 2, 2, 3])
            col1.markdown(f"**No: {row['No']}**")
            
            is_dnf = row['DNF']
            is_finished = row['Finish_Check']
            
            # --- 途中棄権(DNF)済みの行 ---
            if is_dnf:
                if is_admin:
                    if col2.button("↩️ 棄権取消", key=f"undnf_{row['No']}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            latest_df.at[index, 'DNF'] = False
                            latest_df.at[index, 'Finish_Check'] = False
                            latest_df.at[index, 'Finish_Check_Time'] = ""
                            conn.update(worksheet="Data", data=latest_df)
                            st.rerun()
                        except Exception:
                            st.error("通信エラー：アクセス集中。")
                else:
                    col2.button("🚫 棄権済", key=f"dnf_dis_{row['No']}", disabled=True)
                
                col4.error("⚠️ DNF (途中棄権)")
                
            # --- 通常のゴール済みの行 ---
            elif is_finished:
                if is_admin:
                    if col2.button("❌ ゴール取消", key=f"finish_cancel_{row['No']}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            latest_df.at[index, 'Finish_Check'] = False
                            latest_df.at[index, 'Finish_Check_Time'] = ""
                            conn.update(worksheet="Data", data=latest_df)
                            st.rerun()
                        except Exception:
                            st.error("通信エラー：アクセス集中。")
                else:
                    col2.button("🏁 ゴール済", key=f"finish_done_{row['No']}", disabled=True)
                
                # ゴール時刻とタイムの表示
                f_time_str = str(row['Finish_Check_Time'])
                if start_time_val and f_time_str and f_time_str != "nan":
                    try:
                        f_time_obj = datetime.datetime.strptime(f_time_str, '%H:%M:%S').time()
                        f_datetime = datetime.datetime.combine(datetime.date.today(), f_time_obj, tzinfo=JST)
                        net_time = f_datetime - start_time_val
                        time_display = f"ゴール: {f_time_str} (タイム: {str(net_time).split('.')[0]})"
                    except Exception:
                        time_display = f"ゴール: {f_time_str}"
                else:
                    time_display = f"ゴール: {f_time_str} (スタート未設定)"
                    
                col4.success(time_display)

            # --- 未ゴール（チェック可能）の行 ---
            else:
                # 1. ゴールボタン
                if col2.button("🏁 ゴール！", key=f"finish_btn_{row['No']}", type="primary"):
                    try:
                        load_data.clear()
                        latest_df = load_data()
                        # 最新データで未ゴールの場合のみ記録
                        if not latest_df.at[index, 'Finish_Check']:
                            latest_df.at[index, 'Finish_Check'] = True
                            now_jst = datetime.datetime.now(JST)
                            latest_df.at[index, 'Finish_Check_Time'] = now_jst.strftime('%H:%M:%S')
                            conn.update(worksheet="Data", data=latest_df)
                        st.rerun()
                    except Exception:
                        st.error("通信エラー：アクセス集中。")
                
                # 2. 管理者限定：途中棄権ボタン
                if is_admin:
                    if col3.button("⚠️ 途中棄権", key=f"dnf_btn_{row['No']}", type="secondary"):
                        try:
                            load_data.clear()
                            latest_df = load_data()
                            if not latest_df.at[index, 'DNF']:
                                latest_df.at[index, 'DNF'] = True
                                latest_df.at[index, 'Finish_Check'] = True
                                latest_df.at[index, 'Finish_Check_Time'] = ""
                                conn.update(worksheet="Data", data=latest_df)
                            st.rerun()
                        except Exception:
                            st.error("通信エラー：アクセス集中。")
