import streamlit as st
import sqlite3
import pandas as pd
import os

# ページ基本設定
st.set_page_config(
    page_title="ピックルボール練習会 案内・集計",
    page_icon="🏓",
    layout="centered"
)

# データベース初期化（自動作成）
DB_FILE = "pickleball.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 練習会テーブル
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            title TEXT,
            location TEXT,
            capacity INTEGER,
            note TEXT
        )
    ''')
    # 参加者テーブル
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            date TEXT,
            name TEXT,
            comment TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# DB操作関数
def get_events():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM events ORDER BY id DESC", conn)
    conn.close()
    return df

def get_participants():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM participants ORDER BY id DESC", conn)
    conn.close()
    return df

def add_participant(event_id, date, name, comment):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO participants (event_id, date, name, comment) VALUES (?, ?, ?, ?)",
              (event_id, date, name, comment))
    conn.commit()
    conn.close()

def add_event(date, time, title, location, capacity, note):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO events (date, time, title, location, capacity, note) VALUES (?, ?, ?, ?, ?, ?)",
              (date, time, title, location, capacity, note))
    conn.commit()
    conn.close()

# デザイン設定
st.markdown("""
    <style>
    .main-header { font-size: 2rem; color: #1E3A8A; text-align: center; font-weight: bold; margin-bottom: 1rem; }
    .event-card { background-color: #F3F4F6; padding: 1.2rem; border-radius: 10px; border-left: 5px solid #2563EB; margin-bottom: 1rem; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏓 ピックルボール練習会 案内・集計</div>', unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📅 練習日程・参加申込", "📊 参加集計一覧", "⚙️ 管理者画面"])

# タブ1: 練習日程・申込
with tab1:
    st.subheader("📢 開催予定の練習会")
    df_events = get_events()
    
    if df_events.empty:
        st.info("現在予定されている練習会はありません。「管理者画面」タブから日程を追加してください。")
    else:
        for idx, row in df_events.iterrows():
            with st.container():
                st.markdown(f"""
                <div class="event-card">
                    <h3>{row['title']}</h3>
                    <p><b>日時:</b> {row['date']} {row['time']}</p>
                    <p><b>場所:</b> {row['location']}</p>
                    <p><b>定員:</b> {row['capacity']} 名</p>
                    <p><b>備考:</b> {row['note']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander(f"👉 この練習会（{row['date']}）に申し込む"):
                    with st.form(key=f"form_{row['id']}"):
                        name = st.text_input("お名前 *")
                        comment = st.text_input("コメント・連絡事項")
                        submit = st.form_submit_button("参加を申し込む")
                        
                        if submit:
                            if not name:
                                st.warning("お名前を入力してください。")
                            else:
                                add_participant(row['id'], row['date'], name, comment)
                                st.success(f"{name} 様の申し込みを受け付けました！")
                                st.rerun()

# タブ2: 参加集計一覧
with tab2:
    st.subheader("👥 参加集計状況")
    df_parts = get_participants()
    
    if df_parts.empty:
        st.info("まだ参加申込はありません。")
    else:
        st.metric("現在の総参加申込数", f"{len(df_parts)} 名")
        st.dataframe(df_parts[['date', 'name', 'comment']], use_container_width=True, hide_index=True)
        
        # CSVダウンロード機能（手動で保存・エクセル閲覧したい場合用）
        csv = df_parts.to_csv(index=False).encode('utf-8_sig')
        st.download_button(
            label="📥 参加者一覧をCSVでダウンロード",
            data=csv,
            file_name="pickleball_participants.csv",
            mime="text/csv"
        )

# タブ3: 日程追加（管理者用）
with tab3:
    st.subheader("⚙️ 新しい練習会日程の追加")
    with st.form("add_event_form"):
        title = st.text_input("タイトル", value="ピックルボール練習会")
        date = st.text_input("日付 (例: 2026/11/01)")
        time = st.text_input("時間 (例: 10:00〜12:00)")
        location = st.text_input("場所", value="体育館")
        capacity = st.number_input("定員 (名)", value=16, step=1)
        note = st.text_input("備考", value="ラケット貸出あり")
        
        submit_event = st.form_submit_button("日程を公開・追加する")
        if submit_event:
            if not date:
                st.warning("日付を入力してください。")
            else:
                add_event(date, time, title, location, capacity, note)
                st.success("新しい練習会日程を追加しました！")
                st.rerun()
