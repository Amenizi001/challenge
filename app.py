import streamlit as st
import pandas as pd
import datetime
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="マラソン大会 チェックシステム")

# --- セッションステートの初期化 ---
if 'admin_finish_enabled' not in st.session_state:
    st.session_state.admin_finish_enabled = False
if 'start_time' not in st.session_state:
    st.session_state.start_time = None

# --- スプレッドシート接続とデータ読み込み ---
conn = st.connection("gsheets", type=GSheetsConnection)
try:
    df = conn.read(ttl=0) # ttl=0で常に最新データを取得
    # データ型の調整（空欄をFalseとして扱う）
    df['Start_Check'] = df['Start_Check'].fillna(False).astype(bool)
    df['Finish_Check'] = df['Finish_Check'].fillna(False).astype(bool)
except Exception as e:
    st.error("スプレッドシートの読み込みに失敗しました。設定を確認してください。")
    st.stop()

# --- サイドバー：管理者設定 ---
st.sidebar.header("管理者メニュー")
admin_pass = st.sidebar.text_input("管理者パスワードを入力", type="password")

if admin_pass == "admin123":
    st.sidebar.success("管理者認証成功")
    st.sidebar.subheader("ゴールチェック設定")
    st.session_state.admin_finish_enabled = st.sidebar.checkbox(
        "ゴールチェックを可能にする", 
        value=st.session_state.admin_finish_enabled
    )
    
    st.sidebar.subheader("スタート時刻設定")
    if st.sidebar.button("現在時刻をスタート時刻に設定"):
        st.session_state.start_time = datetime.datetime.now()
        
    if st.session_state.start_time:
        st.sidebar.write(f"設定済スタート時刻: {st.session_state.start_time.strftime('%H:%M:%S')}")
    else:
        st.sidebar.write("スタート時刻：未設定")

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
        
        btn_label = "❌ 取消" if row['Start_Check'] else "✅ チェック"
        btn_type = "secondary" if row['Start_Check'] else "primary"
        
        if col2.button(btn_label, key=f"start_{row['No']}", type=btn_type):
            df.at[index, 'Start_Check'] = not row['Start_Check']
            conn.update(data=df) # スプレッドシートを更新
            st.rerun()

# ==========================================
# タブ2：ゴールチェック
# ==========================================
with tab2:
    st.header("ゴール チェック")
    
    if not st.session_state.admin_finish_enabled:
        st.warning("現在、ゴールチェック機能はロックされています。")
    else:
        started_df = df[df['Start_Check']]
        filter_finish = st.radio("表示フィルター (ゴール)", ["すべて", "未ゴール", "ゴール済み"], horizontal=True)
        
        if filter_finish == "未ゴール":
            view_df2 = started_df[~started_df['Finish_Check']]
        elif filter_finish == "ゴール済み":
            view_df2 = started_df[started_df['Finish_Check']]
        else:
            view_df2 = started_df
            
        st.write(f"表示件数: {len(view_df2)} 件")
        
        for index, row in view_df2.iterrows():
            col1, col2, col3 = st.columns([1, 2, 3])
            col1.markdown(f"**No: {row['No']}**")
            
            btn_label2 = "❌ 取消" if row['Finish_Check'] else "🏁 ゴール！"
            btn_type2 = "secondary" if row['Finish_Check'] else "primary"
            
            if col2.button(btn_label2, key=f"finish_{row['No']}", type=btn_type2):
                if not row['Finish_Check']:
                    df.at[index, 'Finish_Check'] = True
                    df.at[index, 'Finish_Check_Time'] = datetime.datetime.now().strftime('%H:%M:%S')
                else:
                    df.at[index, 'Finish_Check'] = False
                    df.at[index, 'Finish_Check_Time'] = ""
                conn.update(data=df) # スプレッドシートを更新
                st.rerun()
                
            if row['Finish_Check']:
                f_time_str = str(row['Finish_Check_Time'])
                s_time = st.session_state.start_time
                
                if s_time and f_time_str:
                    try:
                        # 文字列から時刻オブジェクトに変換して計算
                        f_time_obj = datetime.datetime.strptime(f_time_str, '%H:%M:%S').time()
                        f_datetime = datetime.datetime.combine(datetime.date.today(), f_time_obj)
                        net_time = f_datetime - s_time
                        time_display = f"ゴール: {f_time_str} (タイム: {str(net_time).split('.')[0]})"
                    except:
                        time_display = f"ゴール: {f_time_str}"
                else:
                    time_display = f"ゴール: {f_time_str} (スタート未設定)"
                    
                col3.success(time_display)