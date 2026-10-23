"""ピックルボール練習会 参加状況ボード (Streamlit + Google スプレッドシート)

起動:  streamlit run app.py
設定:  .streamlit/secrets.toml (secrets.toml.example を参照)
  - admin_password        管理者パスワード
  - [gsheets] spreadsheet  スプレッドシートのURLまたはキー
  - [gcp_service_account]  サービスアカウントのJSONキーの中身
"""

from __future__ import annotations

import csv
import html
import io
import os
import uuid
from datetime import date, datetime, timedelta

import gspread
import streamlit as st

WEEKDAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
SOURCES = ["家族", "友人の紹介", "Instagram/SNS", "Web検索", "チラシ・ポスター", "体験会", "その他"]
ICONS = ["なし", "🏓", "😊", "🔥", "💪", "🎾", "⭐", "🌸", "🐶", "🐱", "🍀", "👶", "🎉", "☕"]

EVENT_COLS = ["id", "date", "title", "time", "place", "capacity", "fee", "description"]
PART_COLS = ["id", "event_id", "name", "first_time", "source", "icon", "sub", "status", "created_at"]
SHEETS = {"events": EVENT_COLS, "participants": PART_COLS}

CACHE_TTL = 15  # 秒。他の人の申込が画面に反映されるまでの最大遅延


def admin_password() -> str:
    return str(st.secrets.get("admin_password", os.environ.get("ADMIN_PASSWORD", "admin")))


# ---------------------------------------------------------------------------
# データ層 (Google スプレッドシート)
#   シート "events"       : 1行 = 1日程
#   シート "participants" : 1行 = 1申込 (event_id で日程に紐づく)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _spreadsheet() -> gspread.Spreadsheet:
    client = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    target = st.secrets["gsheets"]["spreadsheet"]
    sh = client.open_by_url(target) if target.startswith("http") else client.open_by_key(target)
    _ensure_sheets(sh)
    return sh


def _ensure_sheets(sh: gspread.Spreadsheet) -> None:
    """必要なシートとヘッダー行がなければ作り、両方空ならサンプルを入れる。"""
    existing = {ws.title: ws for ws in sh.worksheets()}
    created = False
    for title, cols in SHEETS.items():
        ws = existing.get(title) or sh.add_worksheet(title=title, rows=200, cols=len(cols))
        if ws.row_values(1) != cols:
            ws.update(values=[cols], range_name="A1", value_input_option="RAW")
            created = True
    if created and len(sh.worksheet("events").get_all_values()) <= 1:
        _seed(sh)


def _ws(name: str) -> gspread.Worksheet:
    return _spreadsheet().worksheet(name)


def _to_row(rec: dict, cols: list[str]) -> list:
    return [rec.get(c, "") for c in cols]


def _read(name: str) -> list[dict]:
    """全行を文字列のまま読み込む (get_all_records は数値っぽいIDを変換してしまうため使わない)。"""
    values = _ws(name).get_all_values()
    if not values:
        return []
    header = values[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:] if any(row)]


def _parse_event(r: dict) -> dict:
    try:
        cap = int(float(r.get("capacity") or 0))
    except ValueError:
        cap = 0
    return {**r, "capacity": cap}


def _parse_participant(r: dict) -> dict:
    return {**r, "first_time": str(r.get("first_time")).upper() == "TRUE",
            "status": r.get("status") or "attending"}


def _fresh_data() -> dict:
    events = [_parse_event(r) for r in _read("events") if r.get("id")]
    parts = [_parse_participant(r) for r in _read("participants") if r.get("id")]
    for e in events:
        e["participants"] = sorted((p for p in parts if p["event_id"] == e["id"]), key=lambda p: p["created_at"])
    return {"events": events}


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_data() -> dict:
    return _fresh_data()


def _invalidate() -> None:
    load_data.clear()


def _row_index(name: str, rec_id: str) -> int | None:
    """id (A列) から 1始まりの行番号を返す。"""
    ids = _ws(name).col_values(1)
    return ids.index(rec_id) + 1 if rec_id in ids else None


def _append(name: str, rec: dict) -> None:
    _ws(name).append_row(_to_row(rec, SHEETS[name]), value_input_option="RAW")
    _invalidate()


def _update(name: str, rec_id: str, changes: dict) -> None:
    ws = _ws(name)
    idx = _row_index(name, rec_id)
    if idx is None:
        return
    header = SHEETS[name]
    row = ws.row_values(idx)
    current = dict(zip(header, row + [""] * (len(header) - len(row))))
    current.update(changes)
    ws.update(values=[_to_row(current, header)], range_name=f"A{idx}", value_input_option="RAW")
    _invalidate()


def _delete_rows(name: str, rec_ids: set[str], col: int = 1) -> None:
    ws = _ws(name)
    keys = ws.col_values(col)
    # 下から消すと行番号がずれない
    for idx in sorted((i + 1 for i, k in enumerate(keys) if i > 0 and k in rec_ids), reverse=True):
        ws.delete_rows(idx)
    _invalidate()


def _new_participant(name, first_time, source, icon, sub, status="attending") -> dict:
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name.strip(),
        "first_time": bool(first_time),
        "source": source if first_time else "",
        "icon": "" if icon in ("", "なし") else icon,
        "sub": sub.strip(),
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def add_participant(event_id: str, name, first_time, source, icon, sub) -> str:
    """申込。最新データで満員・重複を確認してから書き込む。'ok' / 'dup' / 'full' / 'notfound'"""
    data = _fresh_data()
    ev = find_event(data, event_id)
    if ev is None:
        return "notfound"
    name = name.strip()
    if any(p["name"] == name for p in attending(ev)):
        return "dup"
    if ev["capacity"] and len(attending(ev)) >= ev["capacity"]:
        return "full"
    new = _new_participant(name, first_time, source, icon, sub)
    # 以前キャンセルした同名の人は同じ行を復帰させる
    prev = next((p for p in cancelled(ev) if p["name"] == name), None)
    if prev:
        _update("participants", prev["id"], {k: v for k, v in new.items() if k != "id"})
    else:
        _append("participants", new | {"event_id": event_id})
    return "ok"


def update_participant(pid: str, **changes) -> None:
    _update("participants", pid, changes)


def delete_participant(pid: str) -> None:
    _delete_rows("participants", {pid})


def create_event(values: dict) -> str:
    eid = uuid.uuid4().hex[:8]
    _append("events", values | {"id": eid})
    return eid


def update_event(event_id: str, values: dict) -> None:
    _update("events", event_id, values)


def delete_event(event_id: str) -> None:
    _delete_rows("participants", {event_id}, col=PART_COLS.index("event_id") + 1)
    _delete_rows("events", {event_id})


def _seed(sh: gspread.Spreadsheet) -> None:
    """初回のみ投入するサンプルデータ。"""
    eid = uuid.uuid4().hex[:8]
    ev = {
        "id": eid, "date": "2026-10-31", "title": "エンジョイDAY", "time": "13:00〜16:00",
        "place": "市民体育館 第2アリーナ", "capacity": 20, "fee": "500円",
        "description": "初心者大歓迎！🔰 ラケットの貸し出しもあります🏓\n動きやすい服装と室内シューズでお越しください👟",
    }
    names = [
        ("田中", False, "", "🏓", ""), ("佐藤 花子", False, "", "", "コーチ"), ("鈴木", False, "", "🔥", ""),
        ("しほ", True, "家族", "", ""), ("高橋", False, "", "", ""), ("大場 誠博", True, "Instagram/SNS", "", ""),
        ("伊藤", False, "", "😊", ""), ("渡辺", False, "", "", "15時〜"), ("山本", True, "友人の紹介", "", ""),
        ("中村", False, "", "💪", ""), ("小林", False, "", "", ""), ("加藤 ゆい", True, "家族", "🌸", ""),
        ("吉田", False, "", "", ""), ("山田", False, "", "⭐", ""), ("佐々木", True, "Web検索", "", ""),
        ("山口", False, "", "", "見学"), ("松本", False, "", "", ""), ("井上", True, "体験会", "🎾", ""),
        ("木村", False, "", "", ""), ("林", False, "", "☕", ""),
    ]
    parts = [_new_participant(*n) for n in names] + [_new_participant("清水", False, "", "", "", status="cancelled")]
    sh.worksheet("events").append_row(_to_row(ev, EVENT_COLS), value_input_option="RAW")
    sh.worksheet("participants").append_rows(
        [_to_row(p | {"event_id": eid}, PART_COLS) for p in parts], value_input_option="RAW")


def find_event(data: dict, event_id: str) -> dict | None:
    return next((e for e in data["events"] if e["id"] == event_id), None)


def attending(ev: dict) -> list[dict]:
    return [p for p in ev["participants"] if p["status"] == "attending"]


def cancelled(ev: dict) -> list[dict]:
    return [p for p in ev["participants"] if p["status"] == "cancelled"]


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.month}月{d.day}日 {WEEKDAYS[d.weekday()]}"


def event_label(ev: dict) -> str:
    return f"{fmt_date(ev['date'])}｜{ev['title']}"


# ---------------------------------------------------------------------------
# スタイル
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700;800&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {
  font-family: 'M PLUS Rounded 1c', 'Hiragino Maru Gothic ProN', 'Hiragino Sans', sans-serif !important;
}
.stApp { background: #f6f5f0; }
.block-container { max-width: 760px; padding-top: 4rem; padding-bottom: 4rem; }
#MainMenu, footer { visibility: hidden; }

/* ---- イベントカード ---- */
.pb-event {
  background: #ffd84d;
  border: 3px solid #111;
  border-radius: 22px;
  padding: 22px 24px 20px;
  box-shadow: 6px 6px 0 #111;
  margin-bottom: 26px;
  color: #111;
}
.pb-date { font-size: 2.3rem; font-weight: 800; line-height: 1.15; letter-spacing: .02em; }
.pb-title {
  display: inline-block; margin-top: 8px; font-size: 1.35rem; font-weight: 800;
  background: #111; color: #ffd84d; padding: 2px 14px; border-radius: 999px;
}
.pb-meta { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin-top: 14px; font-size: 1rem; }
.pb-meta .k { font-weight: 700; white-space: nowrap; }
.pb-desc {
  margin-top: 14px; background: rgba(255,255,255,.65); border-radius: 14px;
  padding: 10px 14px; white-space: pre-wrap; line-height: 1.6;
}

/* ---- サマリー ---- */
.pb-summary {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px;
  background: #fff; border: 3px solid #111; border-radius: 20px; padding: 16px 22px; margin-bottom: 18px;
}
.pb-count { display: flex; align-items: baseline; gap: 6px; color: #111; }
.pb-count .n { font-size: 3.4rem; font-weight: 800; line-height: 1; }
.pb-count .cap { font-size: 1.5rem; font-weight: 700; color: #555; }
.pb-count .lbl { font-size: 1.2rem; font-weight: 700; margin-left: 4px; }
.pb-full {
  display: inline-block; margin-left: 10px; align-self: center;
  background: #e53935; color: #fff; font-weight: 800; font-size: 1rem;
  padding: 4px 14px; border-radius: 999px; transform: rotate(-4deg); border: 2px solid #111;
}
.pb-breakdown { display: flex; flex-wrap: wrap; gap: 8px; }
.pb-bd {
  display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: .98rem;
  border: 2px solid #111; border-radius: 999px; padding: 5px 14px; background: #fff; color: #111;
}
.pb-bd.first { background: #e53935; color: #fff; }
.pb-bd b { font-size: 1.15rem; }
.pb-bar { height: 10px; background: #eee; border-radius: 999px; overflow: hidden; margin: -6px 4px 22px; border: 2px solid #111; }
.pb-bar > div { height: 100%; background: #ffd84d; }

/* ---- 名簿 ---- */
.pb-roster { display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0 22px; }
.pb-tag {
  display: inline-flex; align-items: center; gap: 6px;
  background: #fff; color: #111; border: 2px solid #111; border-radius: 999px;
  padding: 7px 16px; font-size: 1.05rem; font-weight: 700; line-height: 1.2;
}
.pb-tag.first { background: #e53935; color: #fff; border-color: #e53935; }
.pb-tag .ic { font-size: 1.15rem; }
.pb-tag .sub { font-size: .78rem; font-weight: 700; opacity: .7; }
.pb-tag .hatsu {
  background: #111; color: #fff; font-size: .75rem; font-weight: 800;
  border-radius: 6px; padding: 2px 6px;
}
.pb-tag .src {
  background: #fff; color: #e53935; font-size: .75rem; font-weight: 800;
  border-radius: 999px; padding: 2px 8px;
}
.pb-empty { color: #888; padding: 10px 0 20px; }

/* ---- フッター ---- */
.pb-note {
  background: #fff1f0; border-left: 6px solid #e53935; border-radius: 10px;
  padding: 10px 14px; font-weight: 700; color: #111; margin-bottom: 12px;
}
.pb-cancel { color: #666; font-size: .95rem; }
.pb-cancel s { margin-right: 12px; text-decoration-thickness: 2px; }

/* ---- 日程一覧 ---- */
.pb-list-card {
  background: #fff; border: 3px solid #111; border-radius: 18px; padding: 14px 18px;
  margin: 4px 0 8px; color: #111; box-shadow: 4px 4px 0 #ffd84d;
}
.pb-list-card.past { opacity: .55; box-shadow: none; }
.pb-list-date { font-size: 1.35rem; font-weight: 800; }
.pb-list-title {
  display: inline-block; margin-left: 8px; font-size: .95rem; font-weight: 800;
  background: #ffd84d; border: 2px solid #111; padding: 0 10px; border-radius: 999px; vertical-align: middle;
}
.pb-list-meta { color: #444; font-size: .92rem; margin-top: 4px; }
.pb-list-stat { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; font-weight: 700; }
.pb-list-stat .num { font-size: 1.3rem; font-weight: 800; }
.pb-chip { border: 2px solid #111; border-radius: 999px; padding: 1px 10px; font-size: .85rem; font-weight: 800; background: #fff; }
.pb-chip.red { background: #e53935; color: #fff; }
.pb-chip.dark { background: #111; color: #fff; }

.pb-section { font-size: 1.15rem; font-weight: 800; margin: 4px 0 10px; color: #111; }

/* Streamlit ボタンを丸く */
.stButton > button, .stFormSubmitButton > button {
  border-radius: 999px !important; border: 2px solid #111 !important; font-weight: 700 !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #e53935 !important; color: #fff !important;
}

.stButton > button:disabled {
  background: #e6e6e6 !important; color: #888 !important; border-color: #bbb !important;
}

@media (max-width: 520px) {
  .pb-date { font-size: 1.8rem; }
  .pb-count .n { font-size: 2.7rem; }
}
</style>
"""


# ---------------------------------------------------------------------------
# HTML 描画
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(str(s or ""))


def render_event_card(ev: dict) -> None:
    rows = [("🕐 時間", ev.get("time")), ("📍 場所", ev.get("place")),
            ("👥 定員", f"{ev.get('capacity')}人"), ("💴 参加費", ev.get("fee"))]
    meta = "".join(f'<div class="k">{k}</div><div>{esc(v)}</div>' for k, v in rows if v)
    desc = f'<div class="pb-desc">{esc(ev["description"])}</div>' if ev.get("description") else ""
    st.markdown(
        f"""<div class="pb-event">
  <div class="pb-date">{esc(fmt_date(ev['date']))}</div>
  <div class="pb-title">{esc(ev['title'])}</div>
  <div class="pb-meta">{meta}</div>
  {desc}
</div>""",
        unsafe_allow_html=True,
    )


def render_summary(ev: dict) -> None:
    att = attending(ev)
    cap = int(ev.get("capacity") or 0)
    n = len(att)
    n_first = sum(p["first_time"] for p in att)
    full = cap > 0 and n >= cap
    badge = '<span class="pb-full">満員</span>' if full else ""
    pct = min(100, int(n / cap * 100)) if cap else 0
    st.markdown(
        f"""<div class="pb-summary">
  <div class="pb-count"><span class="n">{n}</span><span class="cap">/ {cap}人</span><span class="lbl">参加</span>{badge}</div>
  <div class="pb-breakdown">
    <span class="pb-bd first">🔰 初参加 <b>{n_first}</b>人</span>
    <span class="pb-bd">🔁 リピーター <b>{n - n_first}</b>人</span>
  </div>
</div>
<div class="pb-bar"><div style="width:{pct}%"></div></div>""",
        unsafe_allow_html=True,
    )


def tag_html(p: dict) -> str:
    parts = []
    if p.get("icon"):
        parts.append(f'<span class="ic">{esc(p["icon"])}</span>')
    parts.append(f'<span>{esc(p["name"])}</span>')
    if p["first_time"]:
        parts.append('<span class="hatsu">初</span>')
        if p.get("source"):
            parts.append(f'<span class="src">{esc(p["source"])}</span>')
    if p.get("sub"):
        parts.append(f'<span class="sub">{esc(p["sub"])}</span>')
    cls = "pb-tag first" if p["first_time"] else "pb-tag"
    return f'<span class="{cls}">{"".join(parts)}</span>'


def render_roster(ev: dict) -> None:
    att = attending(ev)
    st.markdown('<div class="pb-section">参加者</div>', unsafe_allow_html=True)
    if not att:
        st.markdown('<div class="pb-empty">まだ申込はありません。一番乗りをどうぞ！🏓</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="pb-roster">{"".join(tag_html(p) for p in att)}</div>', unsafe_allow_html=True)


def render_footer(ev: dict) -> None:
    html_parts = []
    if any(p["first_time"] for p in attending(ev)):
        html_parts.append('<div class="pb-note">🔴 赤いお名前 ＝ 今回が初参加の方です。みんなで歓迎しましょう！</div>')
    can = cancelled(ev)
    if can:
        names = "".join(f"<s>{esc(p['name'])}</s>" for p in can)
        html_parts.append(f'<div class="pb-cancel">不参加：{names}</div>')
    if html_parts:
        st.markdown("".join(html_parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# ページ
# ---------------------------------------------------------------------------

def page_board(ev: dict) -> None:
    render_event_card(ev)
    render_summary(ev)
    render_roster(ev)
    render_footer(ev)


def page_list(events: list[dict]) -> None:
    today = date.today().isoformat()
    show_past = st.toggle("終了した日程も表示", value=False)
    shown = [e for e in events if show_past or e["date"] >= today]
    if not shown:
        st.info("今後の日程はまだありません。")
        return
    st.markdown('<div class="pb-section">📅 練習会の日程</div>', unsafe_allow_html=True)
    for e in shown:
        n = len(attending(e))
        cap = e["capacity"]
        n_first = sum(p["first_time"] for p in attending(e))
        past = e["date"] < today
        if past:
            status = '<span class="pb-chip dark">終了</span>'
        elif cap and n >= cap:
            status = '<span class="pb-chip red">満員</span>'
        else:
            status = f'<span class="pb-chip">残り {cap - n}席</span>' if cap else ""
        first = f'<span class="pb-chip red">🔰 初参加 {n_first}人</span>' if n_first else ""
        meta = "　".join(esc(v) for v in (e.get("time"), e.get("place"), e.get("fee")) if v)
        st.markdown(
            f"""<div class="pb-list-card{' past' if past else ''}">
  <span class="pb-list-date">{esc(fmt_date(e['date']))}</span><span class="pb-list-title">{esc(e['title'])}</span>
  <div class="pb-list-meta">{meta}</div>
  <div class="pb-list-stat"><span><span class="num">{n}</span> / {cap}人</span>{status}{first}</div>
</div>""",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        if c1.button("参加状況を見る", key=f"view_{e['id']}", use_container_width=True):
            st.session_state["_next_event"] = e["id"]
            st.session_state["_next_page"] = "📋 参加状況"
            st.rerun()
        full = bool(past or (cap and n >= cap))
        label = "終了しました" if past else "満員です" if full else "申し込む 🏓"
        if c2.button(label, key=f"join_{e['id']}", type="primary", disabled=full, use_container_width=True):
            st.session_state["_next_event"] = e["id"]
            st.session_state["_next_page"] = "✍️ 申し込む"
            st.rerun()


def page_signup(ev: dict) -> None:
    render_event_card(ev)
    render_summary(ev)

    st.markdown('<div class="pb-section">✍️ 参加申込</div>', unsafe_allow_html=True)
    cap = int(ev.get("capacity") or 0)
    if cap and len(attending(ev)) >= cap:
        st.error("申し訳ありません、この回は満員です。")
        return

    name = st.text_input("お名前（表示名）", max_chars=20, placeholder="例: しほ")
    first = st.radio("今回が初参加ですか？", ["いいえ（リピーター）", "はい（初参加）"], horizontal=True) == "はい（初参加）"
    source = ""
    if first:
        source = st.selectbox("どこで知りましたか？", SOURCES)
    icon = st.radio("アイコン（任意）", ICONS, horizontal=True)
    sub = st.text_input("ひとこと・補足（任意）", max_chars=12, placeholder="例: 15時〜 / 見学")

    preview = _new_participant(name or "お名前", first, source, icon, sub)
    st.caption("表示イメージ")
    st.markdown(f'<div class="pb-roster">{tag_html(preview)}</div>', unsafe_allow_html=True)

    if st.button("この内容で申し込む 🏓", type="primary", use_container_width=True):
        if not name.strip():
            st.warning("お名前を入力してください。")
            return

        res = add_participant(ev["id"], name, first, source, icon, sub)
        if res == "ok":
            st.session_state["flash"] = f"{name.strip()} さんの申込を受け付けました！当日お待ちしています 🎉"
            st.session_state["_next_page"] = "📋 参加状況"
            st.rerun()
        elif res == "dup":
            st.warning("同じお名前ですでに申込済みです。")
        elif res == "full":
            st.error("タッチの差で満員になりました…🙏")
        else:
            st.error("イベントが見つかりません。")


def page_admin(data: dict, ev: dict | None) -> None:
    if not st.session_state.get("is_admin"):
        with st.form("login"):
            pw = st.text_input("管理者パスワード", type="password")
            if st.form_submit_button("ログイン", type="primary"):
                if pw == admin_password():
                    st.session_state["is_admin"] = True
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
        return

    tab_p, tab_e, tab_new, tab_csv = st.tabs(["👥 参加者管理", "📝 日程の編集", "➕ 日程の作成", "📊 CSV出力"])

    with tab_p:
        if ev is None:
            st.info("日程がありません。「日程の作成」から追加してください。")
        else:
            admin_participants(ev)

    with tab_e:
        if ev is None:
            st.info("日程がありません。")
        else:
            admin_edit_event(ev)

    with tab_new:
        admin_new_event(data)

    with tab_csv:
        admin_csv(data, ev)

    st.divider()
    if st.button("ログアウト"):
        st.session_state["is_admin"] = False
        st.rerun()


def admin_participants(ev: dict) -> None:
    st.markdown(f"**{esc(event_label(ev))}**　参加 {len(attending(ev))} / {ev['capacity']}人")

    for p in ev["participants"]:
        c1, c2, c3, c4 = st.columns([4, 1.4, 1.4, 1])
        with c1:
            if p["status"] == "attending":
                st.markdown(tag_html(p), unsafe_allow_html=True)
            else:
                st.markdown(f'<span class="pb-cancel"><s>{esc(p["name"])}</s>（不参加）</span>', unsafe_allow_html=True)
        with c2:
            if p["status"] == "attending":
                if st.button("不参加に", key=f"cx_{p['id']}"):
                    update_participant(p["id"], status="cancelled")
                    st.rerun()
            elif st.button("参加に戻す", key=f"rs_{p['id']}"):
                update_participant(p["id"], status="attending")
                st.rerun()
        with c3:
            label = "初参加を解除" if p["first_time"] else "初参加にする"
            if st.button(label, key=f"ft_{p['id']}"):
                update_participant(p["id"], first_time=not p["first_time"])
                st.rerun()
        with c4:
            if st.button("🗑", key=f"del_{p['id']}", help="名簿から完全に削除"):
                delete_participant(p["id"])
                st.rerun()

    st.markdown("---")
    st.markdown("**代理で参加者を追加**")
    with st.form("admin_add", clear_on_submit=True):
        a1, a2 = st.columns(2)
        name = a1.text_input("名前")
        sub = a2.text_input("サブテキスト（任意）")
        b1, b2, b3 = st.columns(3)
        first = b1.checkbox("初参加")
        source = b2.selectbox("流入元（初参加時）", [""] + SOURCES)
        icon = b3.selectbox("アイコン", ICONS)
        if st.form_submit_button("追加", type="primary") and name.strip():
            _append("participants", _new_participant(name, first, source, icon, sub) | {"event_id": ev["id"]})
            st.rerun()


def _event_form(prefix: str, ev: dict | None = None) -> dict | None:
    ev = ev or {}
    with st.form(f"{prefix}_event"):
        d = st.date_input("日付", value=date.fromisoformat(ev["date"]) if ev.get("date") else date.today())
        title = st.text_input("タイトル", value=ev.get("title", "エンジョイDAY"))
        c1, c2 = st.columns(2)
        time_ = c1.text_input("時間", value=ev.get("time", "13:00〜16:00"))
        place = c2.text_input("場所", value=ev.get("place", ""))
        c3, c4 = st.columns(2)
        capacity = c3.number_input("定員", min_value=1, max_value=500, value=int(ev.get("capacity", 20)))
        fee = c4.text_input("参加費", value=ev.get("fee", "500円"))
        desc = st.text_area("説明文（絵文字OK）", value=ev.get("description", ""), height=110)
        if st.form_submit_button("保存", type="primary"):
            return {"date": d.isoformat(), "title": title.strip() or "練習会", "time": time_,
                    "place": place, "capacity": int(capacity), "fee": fee, "description": desc}
    return None


def admin_edit_event(ev: dict) -> None:
    values = _event_form("edit", ev)
    if values:
        update_event(ev["id"], values)
        st.session_state["flash"] = "日程を更新しました。"
        st.rerun()

    with st.expander("⚠️ この日程を削除"):
        if st.checkbox("参加者データも含めて削除することを確認しました"):
            if st.button("削除する", type="primary"):
                delete_event(ev["id"])
                st.session_state["_next_event"] = None
                st.rerun()


def admin_new_event(data: dict) -> None:
    template = None
    if data["events"]:
        # 直近（日付が最も新しい）日程の内容を初期値にし、日付はその1週間後（過去なら今日以降の同じ曜日）
        latest = max(data["events"], key=lambda e: e["date"])
        d = date.fromisoformat(latest["date"]) + timedelta(days=7)
        while d < date.today():
            d += timedelta(days=7)
        template = {**latest, "date": d.isoformat()}
        st.caption(f"前回「{event_label(latest)}」の内容を初期値にしています。")
    values = _event_form("new", template)
    if values:
        st.session_state["_next_event"] = create_event(values)
        st.session_state["flash"] = "日程を作成しました。"
        st.rerun()


CSV_COLS = ["日付", "タイトル", "名前", "状態", "初参加", "流入元", "アイコン", "ひとこと", "申込日時"]


def participants_csv(events: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLS)
    for e in sorted(events, key=lambda e: e["date"]):
        for p in e["participants"]:
            w.writerow([e["date"], e["title"], p["name"],
                        "参加" if p["status"] == "attending" else "不参加",
                        "○" if p["first_time"] else "", p.get("source", ""), p.get("icon", ""),
                        p.get("sub", ""), p.get("created_at", "")])
    return buf.getvalue().encode("utf-8-sig")  # Excel で文字化けしないよう BOM 付き


def admin_csv(data: dict, ev: dict | None) -> None:
    st.caption("Excel でそのまま開ける形式（UTF-8 BOM付き）です。")
    if ev is not None:
        st.download_button(f"📥 この日程（{event_label(ev)}）の参加者", participants_csv([ev]),
                           file_name=f"pickleball_{ev['date']}.csv", mime="text/csv", use_container_width=True)
    if data["events"]:
        st.download_button("📥 全日程の参加者", participants_csv(data["events"]),
                           file_name="pickleball_participants_all.csv", mime="text/csv", use_container_width=True)
    else:
        st.info("日程がありません。")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="ピックルボール練習会", page_icon="🏓", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)

    try:
        data = load_data()
    except (KeyError, FileNotFoundError):
        st.error("Google スプレッドシートの設定が見つかりません。`.streamlit/secrets.toml` を確認してください（secrets.toml.example 参照）。")
        st.stop()
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("スプレッドシートが見つかりません。URL/キーと、サービスアカウントへの共有（編集者）を確認してください。")
        st.stop()
    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API エラー: {e}")
        st.stop()
    events = sorted(data["events"], key=lambda e: e["date"])

    # ウィジェット描画前に、前回の操作で予約された遷移を反映
    if "_next_page" in st.session_state:
        st.session_state["page"] = st.session_state.pop("_next_page")
    if "_next_event" in st.session_state:
        st.session_state["event_id"] = st.session_state.pop("_next_event")

    with st.sidebar:
        st.markdown("## 🏓 ピックルボール練習会")
        pages = ["📋 参加状況", "📅 日程一覧", "✍️ 申し込む", "🔧 管理"]
        page = st.radio("メニュー", pages, key="page", label_visibility="collapsed")

        ev = None
        if events:
            ids = [e["id"] for e in events]
            if st.session_state.get("event_id") not in ids:
                # 今日以降で最も近い日程をデフォルトに
                today = date.today().isoformat()
                upcoming = [e for e in events if e["date"] >= today]
                st.session_state["event_id"] = (upcoming[0] if upcoming else events[-1])["id"]
            labels = {e["id"]: event_label(e) for e in events}
            st.selectbox("日程", ids, key="event_id", format_func=labels.get)
            ev = find_event(data, st.session_state["event_id"])

    if msg := st.session_state.pop("flash", None):
        st.success(msg)

    if page == "🔧 管理":
        page_admin(data, ev)
    elif page == "📅 日程一覧":
        page_list(events)
    elif ev is None:
        st.info("公開中の日程はまだありません。")
    elif page == "✍️ 申し込む":
        page_signup(ev)
    else:
        page_board(ev)


if __name__ == "__main__":
    main()
