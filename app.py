import streamlit as st
import sqlite3
import pandas as pd

# ページ基本設定
st.set_page_config(
    page_title="ピックルボール練習会 案内・集計",
    page_icon="🏓",
    layout="centered"
)

# データベース初期化
DB_FILE = "pickleball.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            date TEXT,
            nickname TEXT,
            comment TEXT
        )
    ''')
    
    c.execute("PRAGMA table_info(participants)")
    columns = [column[1] for column in c.fetchall()]
    if "nickname" not in columns:
        c.execute("ALTER TABLE participants ADD COLUMN nickname TEXT")
        
    conn.commit()
    conn.close()

init_db()

# DB操作関数
def get_events():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM events ORDER BY id DESC", conn)
    conn.close()
    return df

def get_latest_event():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT title, location, capacity, note, time FROM events ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row

def get_participants_by_event(event_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT nickname, comment FROM participants WHERE event_id = ? ORDER BY id ASC", conn, params=(event_id,))
    conn.close()
    return df

def get_all_participants():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM participants ORDER BY id DESC", conn)
    conn.close()
    return df

def add_participant(event_id, date, nickname, comment):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO participants (event_id, date, nickname, comment) VALUES (?, ?, ?, ?)",
              (event_id, date, nickname, comment))
    conn.commit()
    conn.close()

def add_event(date, time, title, location, capacity, note):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO events (date, time, title, location, capacity, note) VALUES (?, ?, ?, ?, ?, ?)",
              (date, time, title, location, capacity, note))
    conn.commit()
    conn.close()

def delete_event(event_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM events WHERE id = ?", (event_id,))
    c.execute("DELETE FROM participants WHERE event_id = ?", (event_id,))
    conn.commit()
    conn.close()

# デザイン設定（黄色グラデーション）
st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(135deg, #FFEB3B 0%, #FBC02D 100%);
        color: #212121;
    }
    .main-header {
        font-size: 2.2rem;
        color: #3E2723;
        text-align: center;
        font-weight: bold;
        margin-bottom: 1.5rem;
        text-shadow: 1px 1px 2px rgba(255,255,255,0.8);
    }
    .event-card {
        background-color: #FFFFFF;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.12);
        margin-bottom: 1.5rem;
        border-left: 8px solid #F57F17;
    }
    .event-title {
        color: #F57F17;
        margin-top: 0;
        font-size: 1.4rem;
        border-bottom: 2px solid #FFF59D;
        padding-bottom: 0.3rem;
    }
    .participant-badge {
        display: inline-block;
        background-color: #FFFDE7;
        color: #E65100;
        padding: 0.38rem 0.85rem;
        border-radius: 20px;
        margin: 0.2rem;
        font-weight: bold;
        border: 1px solid #FBC02D;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏓 ピックルボール練習会 案内・参加状況</div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📅 練習日程・参加申し込み", "⚙️ 管理者画面（日程追加・削除）"])

# タブ1: 練習日程・参加申込
with tab1:
    df_events = get_events()
    
    if df_events.empty:
        st.info("現在予定されている練習会はありません。「管理者画面」タブから日程を追加してください。")
    else:
        for idx, row in df_events.iterrows():
            event_id = row['id']
            df_parts = get_participants_by_event(event_id)
            current_count = len(df_parts)
            capacity = row['capacity']
            
            st.markdown(f"""
            <div class="event-card">
                <h3 class="event-title">🏓 {row['title']}（{row['date']}）</h3>
                <p><b>⏰ 時間:</b> {row['time']}</p>
                <p><b>📍 場所:</b> {row['location']}</p>
                <p><b>👥 参加人数:</b> {current_count} / {capacity} 名</p>
                <p><b>📝 備考:</b> {row['note']}</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.write("▼ **現在の参加メンバー（ニックネーム）**")
            if df_parts.empty:
                st.caption("（まだ参加申込はありません。一番乗りで申し込みましょう！）")
            else:
                badges_html = ""
                for _, p_row in df_parts.iterrows():
                    nickname_val = p_row['nickname'] if pd.notna(p_row['nickname']) else "匿名"
                    comment_text = f" ({p_row['comment']})" if pd.notna(p_row['comment']) and p_row['comment'] else ""
                    badges_html += f'<span class="participant-badge">👤 {nickname_val}{comment_text}</span> '
                st.markdown(badges_html, unsafe_allow_html=True)
            
            st.write("")
            
            with st.expander(f"👉 この練習会（{row['date']}）に申込する"):
                with st.form(key=f"form_{event_id}"):
                    nickname = st.text_input("ニックネーム（表示名） *", placeholder="例: ピックル太郎")
                    comment = st.text_input("一言コメント・連絡事項", placeholder="例: 初心者です！道具貸出希望")
                    submit = st.form_submit_button("参加を申し込む！")
                    
                    if submit:
                        if not nickname:
                            st.warning("ニックネームを入力してください。")
                        else:
                            add_participant(event_id, row['date'], nickname, comment)
                            st.success(f"「{nickname}」様 の参加を受け付けました！")
                            st.rerun()
            
            st.divider()

# タブ2: 管理者画面
with tab2:
    # 1. 登録済み日程の削除（上部に配置してすぐ見えるように修正）
    st.subheader("🗑️ 登録済み日程の削除")
    df_events_del = get_events()
    
    if df_events_del.empty:
        st.info("現在登録されている日程はありません。")
    else:
        for _, del_row in df_events_del.iterrows():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"<b>{del_row['date']}</b> - {del_row['title']} ({del_row['time']})", unsafe_allow_html=True)
            with col2:
                if st.button("🗑️ 削除", key=f"del_{del_row['id']}"):
                    delete_event(del_row['id'])
                    st.success(f"{del_row['date']} の日程を削除しました。")
                    st.rerun()
    
    st.write("---")
    
    # 2. 新しい練習会日程の追加
    st.subheader("⚙️ 新しい練習会日程の追加")
    latest = get_latest_event()
    default_title = latest[0] if latest else "ピックルボール練習会"
    default_location = latest[1] if latest else "体育館"
    default_capacity = int(latest[2]) if latest else 16
    default_note = latest[3] if latest else "ラケット貸出あり / 参加費500円"
    default_time = latest[4] if latest else "10:00〜12:00"
    
    with st.form("add_event_form"):
        title = st.text_input("タイトル", value=default_title)
        date = st.text_input("日付 *", placeholder="例: 11/15(土)")
        time = st.text_input("時間", value=default_time)
        location = st.text_input("場所", value=default_location)
        capacity = st.number_input("定員 (名)", value=default_capacity, step=1)
        note = st.text_input("備考", value=default_note)
        
        submit_event = st.form_submit_button("日程を追加・公開する")
        if submit_event:
            if not date:
                st.warning("日付を入力してください。")
            else:
                add_event(date, time, title, location, capacity, note)
                st.success("新しい練習会日程を追加しました！")
                st.rerun()

    # 3. CSV出力機能
    st.write("---")
    st.subheader("📊 参加者データ出力")
    all_parts = get_all_participants()
    if not all_parts.empty:
        csv = all_parts.to_csv(index=False).encode('utf-8_sig')
        st.download_button(
            label="📥 全参加者リスト（CSV）をダウンロード",
            data=csv,
            file_name="pickleball_participants.csv",
            mime="text/csv"
        )
