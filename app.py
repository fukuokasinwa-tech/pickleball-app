import html
import os
import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

# ページ基本設定
st.set_page_config(
    page_title="ピックルボール練習会 案内・集計",
    page_icon="🏓",
    layout="centered"
)

# データベース初期化
DB_FILE = "pickleball.db"
WEEKDAYS = "月火水木金土日"


def admin_password():
    # 【改善1】管理者パスワード（Streamlit Cloud の Secrets に admin_password を設定）
    try:
        return st.secrets["1234"]
    except (KeyError, FileNotFoundError):
        return os.environ.get("1234", "admin")


def connect():
    # 【改善10】with closing(...) で例外時も確実に接続を閉じる
    return closing(sqlite3.connect(DB_FILE))


def init_db():
    with connect() as conn:
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
        # 古いDB（nickname列がない）向けの移行処理
        c.execute("PRAGMA table_info(participants)")
        columns = [column[1] for column in c.fetchall()]
        if "nickname" not in columns:
            c.execute("ALTER TABLE participants ADD COLUMN nickname TEXT")
        conn.commit()


init_db()


# DB操作関数
def get_events(include_past=True):
    # 【改善8】日付順に並べ、終了した日程は除外できるようにする
    with connect() as conn:
        df = pd.read_sql_query("SELECT * FROM events ORDER BY date ASC, id ASC", conn)
    if not include_past:
        today = date.today().isoformat()
        # ISO形式（2026-11-15）の日付だけ比較。旧形式（11/15(土)）は残す
        is_iso = df["date"].str.match(r"^\d{4}-\d{2}-\d{2}$")
        df = df[~is_iso | (df["date"] >= today)]
    return df


def get_latest_event():
    with connect() as conn:
        c = conn.cursor()
        c.execute("SELECT title, location, capacity, note, time FROM events ORDER BY id DESC LIMIT 1")
        return c.fetchone()


def get_participants_by_event(event_id):
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT id, nickname, comment FROM participants WHERE event_id = ? ORDER BY id ASC",
            conn, params=(int(event_id),))


def get_all_participants():
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT p.id, e.date, e.title, p.nickname, p.comment "
            "FROM participants p LEFT JOIN events e ON p.event_id = e.id ORDER BY e.date, p.id", conn)


def add_participant(event_id, date_text, nickname, comment):
    """【改善3・7】定員と二重申込をチェックしてから登録。'ok' / 'full' / 'dup' を返す"""
    with connect() as conn:
        c = conn.cursor()
        c.execute("SELECT capacity FROM events WHERE id = ?", (int(event_id),))
        row = c.fetchone()
        if row is None:
            return "notfound"
        c.execute("SELECT nickname FROM participants WHERE event_id = ?", (int(event_id),))
        names = [r[0] for r in c.fetchall()]
        if nickname in names:
            return "dup"
        if row[0] and len(names) >= row[0]:
            return "full"
        c.execute("INSERT INTO participants (event_id, date, nickname, comment) VALUES (?, ?, ?, ?)",
                  (int(event_id), date_text, nickname, comment))
        conn.commit()
        return "ok"


def delete_participant(participant_id):
    # 【改善7】管理者が参加者を1人だけ取り消せるように
    with connect() as conn:
        conn.execute("DELETE FROM participants WHERE id = ?", (int(participant_id),))
        conn.commit()


def add_event(date_text, time, title, location, capacity, note):
    with connect() as conn:
        conn.execute("INSERT INTO events (date, time, title, location, capacity, note) VALUES (?, ?, ?, ?, ?, ?)",
                     (date_text, time, title, location, int(capacity), note))
        conn.commit()


def delete_event(event_id):
    with connect() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (int(event_id),))
        conn.execute("DELETE FROM participants WHERE event_id = ?", (int(event_id),))
        conn.commit()


def fmt_date(text):
    """ISO形式なら「11/15(土)」表示に。旧形式の文字列はそのまま"""
    try:
        d = date.fromisoformat(text)
        return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"
    except (TypeError, ValueError):
        return text


def esc(value):
    # 【改善4】HTMLに埋め込む値は必ずエスケープ
    return html.escape("" if pd.isna(value) else str(value))


def flash(message):
    # 【改善5】st.rerun() 後に表示するメッセージを予約
    st.session_state["flash"] = message


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
    .full-badge {
        display: inline-block;
        background: #E53935;
        color: #fff;
        font-size: 0.9rem;
        padding: 0.1rem 0.7rem;
        border-radius: 20px;
        margin-left: 0.4rem;
        vertical-align: middle;
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

if msg := st.session_state.pop("flash", None):
    st.success(msg)

tab1, tab2 = st.tabs(["📅 練習日程・参加申し込み", "⚙️ 管理者画面（日程追加・削除）"])

# タブ1: 練習日程・参加申込
with tab1:
    show_past = st.toggle("終了した練習会も表示", value=False)
    df_events = get_events(include_past=show_past)

    if df_events.empty:
        st.info("現在予定されている練習会はありません。")
    else:
        for _, row in df_events.iterrows():
            event_id = row['id']
            df_parts = get_participants_by_event(event_id)
            current_count = len(df_parts)
            capacity = int(row['capacity'] or 0)
            is_full = capacity > 0 and current_count >= capacity
            full_badge = '<span class="full-badge">満員</span>' if is_full else ""

            st.markdown(f"""
            <div class="event-card">
                <h3 class="event-title">🏓 {esc(row['title'])}（{esc(fmt_date(row['date']))}）{full_badge}</h3>
                <p><b>⏰ 時間:</b> {esc(row['time'])}</p>
                <p><b>📍 場所:</b> {esc(row['location'])}</p>
                <p><b>👥 参加人数:</b> {current_count} / {capacity} 名</p>
                <p><b>📝 備考:</b> {esc(row['note'])}</p>
            </div>
            """, unsafe_allow_html=True)

            st.write("▼ **現在の参加メンバー（ニックネーム）**")
            if df_parts.empty:
                st.caption("（まだ参加申込はありません。一番乗りで申し込みましょう！）")
            else:
                badges_html = ""
                for _, p_row in df_parts.iterrows():
                    nickname_val = esc(p_row['nickname']) or "匿名"
                    comment_text = f" ({esc(p_row['comment'])})" if esc(p_row['comment']) else ""
                    badges_html += f'<span class="participant-badge">👤 {nickname_val}{comment_text}</span> '
                st.markdown(badges_html, unsafe_allow_html=True)

            st.write("")

            if is_full:
                st.info("この練習会は満員です。")
            else:
                with st.expander(f"👉 この練習会（{fmt_date(row['date'])}）に申込する"):
                    with st.form(key=f"form_{event_id}", clear_on_submit=True):
                        nickname = st.text_input("ニックネーム（表示名） *", max_chars=20, placeholder="例: ピックル太郎")
                        comment = st.text_input("一言コメント・連絡事項", max_chars=40, placeholder="例: 初心者です！道具貸出希望")
                        submit = st.form_submit_button("参加を申し込む！")

                        if submit:
                            nickname = nickname.strip()
                            if not nickname:
                                st.warning("ニックネームを入力してください。")
                            else:
                                result = add_participant(event_id, row['date'], nickname, comment.strip())
                                if result == "ok":
                                    flash(f"「{nickname}」様 の参加を受け付けました！")
                                    st.rerun()
                                elif result == "dup":
                                    st.warning("同じニックネームですでに申込済みです。")
                                elif result == "full":
                                    st.error("申し訳ありません、満員になりました。")
                                else:
                                    st.error("この練習会は見つかりませんでした。")

            st.divider()

# タブ2: 管理者画面
with tab2:
    # 【改善1】パスワードを入力しないと管理機能を表示しない
    if not st.session_state.get("is_admin"):
        pw = st.text_input("管理者パスワード", type="password")
        if st.button("ログイン"):
            if pw == admin_password():
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("パスワードが違います。")
        st.stop()

    # 1. 登録済み日程・参加者の管理
    st.subheader("🗑️ 登録済み日程・参加者の管理")
    df_events_del = get_events()

    if df_events_del.empty:
        st.info("現在登録されている日程はありません。")
    else:
        for _, del_row in df_events_del.iterrows():
            eid = del_row['id']
            with st.expander(f"{fmt_date(del_row['date'])} - {del_row['title']} ({del_row['time']})"):
                # 参加者を1人ずつ取り消し
                for _, p in get_participants_by_event(eid).iterrows():
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"👤 {p['nickname']}")
                    if c2.button("取消", key=f"delp_{p['id']}"):
                        delete_participant(p['id'])
                        flash(f"{p['nickname']} さんの申込を取り消しました。")
                        st.rerun()

                # 【改善6】確認チェックを入れないと削除できない
                confirm = st.checkbox("参加者も含めて削除することを確認しました", key=f"confirm_{eid}")
                if st.button("🗑️ この日程を削除", key=f"del_{eid}", disabled=not confirm):
                    delete_event(eid)
                    flash(f"{fmt_date(del_row['date'])} の日程を削除しました。")
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
        # 【改善8】日付はカレンダー入力（ISO形式で保存されるので並び替え・過去判定ができる）
        event_date = st.date_input("日付 *", value=date.today(), min_value=date.today())
        time = st.text_input("時間", value=default_time)
        location = st.text_input("場所", value=default_location)
        # 【改善9】定員は1以上
        capacity = st.number_input("定員 (名)", min_value=1, max_value=200, value=default_capacity, step=1)
        note = st.text_input("備考", value=default_note)

        if st.form_submit_button("日程を追加・公開する"):
            add_event(event_date.isoformat(), time, title, location, capacity, note)
            flash("新しい練習会日程を追加しました！")
            st.rerun()

    # 3. CSV出力機能
    st.write("---")
    st.subheader("📊 参加者データ出力")
    all_parts = get_all_participants()
    if not all_parts.empty:
        csv = all_parts.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 全参加者リスト（CSV）をダウンロード",
            data=csv,
            file_name="pickleball_participants.csv",
            mime="text/csv"
        )

    st.write("---")
    if st.button("ログアウト"):
        st.session_state["is_admin"] = False
        st.rerun()
