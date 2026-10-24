"""YAME PICK 参加確認 (Streamlit + Google スプレッドシート)

起動:  streamlit run app.py
設定:  .streamlit/secrets.toml (secrets.toml.example を参照)
  - admin_password        管理者パスワード
  - [gsheets] spreadsheet  スプレッドシートのURLまたはキー
  - [gcp_service_account]  サービスアカウントのJSONキーの中身
"""

from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import os
import re
import time
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import gspread
import streamlit as st

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
SOURCES = ["友人・知人の紹介", "家族", "Instagram/SNS", "Web検索", "チラシ・ポスター", "体験会", "その他"]
# (必要な参加回数, レベル名, アイコン)
LEVELS = [(0, "ビギナー", "🌱"), (1, "ルーキー", "🥚"), (6, "プレイヤー", "🏓"), (15, "エース", "🔥"), (30, "レジェンド", "👑")]
# 練習会の時間の選択肢（30分おき・6:00〜22:00）
TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(6, 23) for m in (0, 30) if (h, m) <= (22, 0)]
NEWS_CATEGORIES = {"お知らせ": ("📣", "info"), "大会情報": ("🏆", "event"), "その他": ("📝", "other")}

SHEETS = {
    "members": ["id", "name", "pin_hash", "family_of", "source", "referrer", "created_at"],
    "events": ["id", "date", "title", "tag", "time", "place", "capacity", "fee", "description"],
    "attendance": ["id", "event_id", "member_id", "status", "updated_at"],
    "news": ["id", "date", "category", "title", "body"],
    "settings": ["id", "value"],  # id = 設定名（howto_title など）
}
# 「使い方はかんたん！」の初期の文。管理者メニューで書き換えると settings シートに保存される
HOWTO_DEFAULT = {
    "howto_title": "📖 使い方はかんたん！",
    "howto_steps": "お名前と好きな数字を登録\n行ける日の「🏓 参加する」をタップ\n予定が変わったら、もう一度タップで不参加に",
    "howto_note": "別のスマホやブラウザで開いても、同じお名前と数字でログインできます。右上の × でこの案内を閉じられます。",
}
# 「テーマ」欄の初期の文。管理者メニューで書き換えると settings シートに保存される
THEME_DEFAULT = {
    "theme_title": "🎯 テーマ",
    "theme_body": "八女でピックルボールを楽しもう‼️\n"
                  "初心者・未経験者・ちょっとやってみたい方も大歓迎🙌\n"
                  "テーマは「楽しむ」「つながる」「健康になる」\n"
                  "体験会・練習会の情報はここで発信🎵\n"
                  "※パドル無料貸出🆓",
}
CACHE_TTL = 15  # 秒。他の人の出欠が画面に反映されるまでの最大遅延


def now() -> datetime:
    return datetime.now(JST)


def today() -> str:
    return now().date().isoformat()


def secret(key: str, default: str = "") -> str:
    try:
        return str(st.secrets[key])
    except (KeyError, FileNotFoundError):
        return os.environ.get(key.upper(), default)


def admin_password() -> str:
    return secret("admin_password", "1234")


def new_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# データ層 (Google スプレッドシート)
# ---------------------------------------------------------------------------

def _service_account_info() -> dict:
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    # JSON キーファイルの中身をそのまま貼り付ける形式にも対応
    return json.loads(st.secrets["gcp_service_account_json"])


def missing_settings() -> list[str]:
    """Secrets に足りない設定項目の名前を返す。"""
    try:
        missing = []
        if "gsheets" not in st.secrets or "spreadsheet" not in st.secrets["gsheets"]:
            missing.append("[gsheets] spreadsheet（スプレッドシートのURL）")
        if "gcp_service_account" not in st.secrets and "gcp_service_account_json" not in st.secrets:
            missing.append("gcp_service_account_json（Google の鍵 JSON）")
        return missing
    except FileNotFoundError:
        return ["Secrets がまったく設定されていません"]


@st.cache_resource(show_spinner=False)
def _spreadsheet() -> gspread.Spreadsheet:
    client = gspread.service_account_from_dict(_service_account_info())
    target = st.secrets["gsheets"]["spreadsheet"]
    sh = client.open_by_url(target) if target.startswith("http") else client.open_by_key(target)
    _ensure_sheets(sh)
    return sh


def _ensure_sheets(sh: gspread.Spreadsheet) -> None:
    """必要なシートとヘッダー行がなければ作り、新規作成時はサンプルを入れる。"""
    existing = {ws.title: ws for ws in sh.worksheets()}
    created = False
    for title, cols in SHEETS.items():
        ws = existing.get(title) or sh.add_worksheet(title=title, rows=500, cols=len(cols))
        if ws.row_values(1) != cols:
            ws.update(values=[cols], range_name="A1", value_input_option="RAW")
            created = True
    if created and len(sh.worksheet("events").get_all_values()) <= 1:
        _seed(sh)


def _call(fn, *args, **kwargs):
    """Google の読み書き回数の上限（1分あたり）に当たったら、少し待って再試行する。"""
    for wait in (1, 2, 4, 8):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if e.response.status_code not in (429, 500, 502, 503):
                raise
            time.sleep(wait)
    return fn(*args, **kwargs)


@st.cache_resource(show_spinner=False)
def _worksheets() -> dict[str, gspread.Worksheet]:
    """シート名 → ワークシート。毎回 Google に問い合わせないよう覚えておく。"""
    return {ws.title: ws for ws in _call(_spreadsheet().worksheets)}


def _refresh_worksheets() -> None:
    # 接続はキャッシュされるので、アプリ更新でシートが増えたときや、
    # シートを消してしまったときはここで作り直す
    _ensure_sheets(_spreadsheet())
    _worksheets.clear()


def _ws(name: str) -> gspread.Worksheet:
    if name not in _worksheets():
        _refresh_worksheets()
    return _worksheets()[name]


def _to_row(rec: dict, name: str) -> list:
    return [rec.get(c, "") for c in SHEETS[name]]


def _read_all() -> dict[str, list[list[str]]]:
    """全シートを1回のリクエストでまとめて読む。"""
    names = list(SHEETS)
    for name in names:
        _ws(name)  # シートが無ければ作る（覚えている間は通信なし）
    ranges = [f"'{n}'" for n in names]
    try:
        resp = _call(_spreadsheet().values_batch_get, ranges)
    except gspread.exceptions.APIError as e:
        if e.response.status_code != 400:  # 400 = シートを手で消した等で範囲が見つからない
            raise
        _refresh_worksheets()
        resp = _call(_spreadsheet().values_batch_get, ranges)
    return {n: vr.get("values", []) for n, vr in zip(names, resp["valueRanges"])}


def _rows(values: list[list[str]]) -> list[dict]:
    """全行を文字列のまま辞書にする (get_all_records は数値っぽいIDを変換してしまうため使わない)。"""
    if not values:
        return []
    header = values[0]
    rows = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in values[1:]]
    return [r for r in rows if r.get("id")]


def _fresh_data() -> dict:
    data = {name: _rows(values) for name, values in _read_all().items()}
    for e in data["events"]:
        try:
            e["capacity"] = int(float(e.get("capacity") or 0))
        except ValueError:
            e["capacity"] = 0
    data["events"].sort(key=lambda e: e["date"])
    data["news"].sort(key=lambda n: n["date"], reverse=True)
    return data


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_data() -> dict:
    return _fresh_data()


def _append(name: str, rec: dict) -> None:
    _call(_ws(name).append_row, _to_row(rec, name), value_input_option="RAW")
    load_data.clear()


def _update(name: str, rec_id: str, changes: dict) -> None:
    ws = _ws(name)
    ids = _call(ws.col_values, 1)
    if rec_id not in ids:
        return
    idx = ids.index(rec_id) + 1
    header = SHEETS[name]
    row = _call(ws.row_values, idx)
    current = dict(zip(header, row + [""] * (len(header) - len(row)))) | changes
    _call(ws.update, values=[_to_row(current, name)], range_name=f"A{idx}", value_input_option="RAW")
    load_data.clear()


def _delete(name: str, values: set[str], col: str = "id") -> None:
    ws = _ws(name)
    keys = _call(ws.col_values, SHEETS[name].index(col) + 1)
    # 下から消すと行番号がずれない
    for idx in sorted((i + 1 for i, k in enumerate(keys) if i > 0 and k in values), reverse=True):
        _call(ws.delete_rows, idx)
    load_data.clear()


def _seed(sh: gspread.Spreadsheet) -> None:
    """初回のみ投入するサンプルデータ（管理者メニューから削除できます）。"""
    t = now().date()
    d1 = date.fromordinal(t.toordinal() + ((5 - t.weekday()) % 7 or 7))  # 次の土曜
    d2 = date.fromordinal(d1.toordinal() + 1)
    past = date.fromordinal(d1.toordinal() - 7)
    events = [
        {"id": new_id(), "date": past.isoformat(), "title": "エンジョイDAY", "tag": "", "time": "09:00〜11:00",
         "place": "北野体育館", "capacity": 20, "fee": "1,000円/人（2回目から500円/人）", "description": ""},
        {"id": new_id(), "date": d1.isoformat(), "title": "エンジョイDAY", "tag": "", "time": "09:00〜11:00",
         "place": "北野体育館", "capacity": 20, "fee": "1,000円/人（2回目から500円/人）",
         "description": "体験会あり！はじめての方・親子も大歓迎🏓"},
        {"id": new_id(), "date": d2.isoformat(), "title": "ガチDAY", "tag": "経験者メイン", "time": "09:00〜11:00",
         "place": "北野体育館", "capacity": 16, "fee": "500円/人", "description": "試合形式でがっつり練習します💪"},
    ]
    names = [("サンプル太郎", "", ""), ("サンプル花子", "", ""), ("サンプル次郎", "", ""),
             ("はじめて一郎", "友人・知人の紹介", "サンプル太郎"), ("おやすみ三郎", "", "")]
    members = [{"id": new_id(), "name": n, "pin_hash": "", "family_of": "", "source": s, "referrer": r,
                "created_at": now().isoformat(timespec="seconds")} for n, s, r in names]
    att = []
    for m in members[:3]:  # 3人は前回も参加 → リピーター
        att.append({"id": new_id(), "event_id": events[0]["id"], "member_id": m["id"], "status": "attending"})
    for m in members[:4]:
        att.append({"id": new_id(), "event_id": events[1]["id"], "member_id": m["id"], "status": "attending"})
    att.append({"id": new_id(), "event_id": events[1]["id"], "member_id": members[4]["id"], "status": "absent"})
    for a in att:
        a["updated_at"] = now().isoformat(timespec="seconds")
    news = [
        {"id": new_id(), "date": t.isoformat(), "category": "お知らせ",
         "title": "🏓 パドル（ラケット）試打できるようになりました！",
         "body": "練習の日に、いろいろなパドルを自由に試打できます。\n自分に合う1本を見つけてください！"},
        {"id": new_id(), "date": t.isoformat(), "category": "大会情報", "title": "🏆 第1回 大会 詳細決定！",
         "body": "日時：未定\n場所：未定\n参加費：1,000円\n\n⏰ 参加締切：未定"},
    ]
    for name, rows in (("events", events), ("members", members), ("attendance", att), ("news", news)):
        sh.worksheet(name).append_rows([_to_row(r, name) for r in rows], value_input_option="RAW")


# ---------------------------------------------------------------------------
# 集計ヘルパー
# ---------------------------------------------------------------------------

def norm(name: str) -> str:
    return name.strip().replace("　", " ").lower()


def find(rows: list[dict], rec_id: str) -> dict | None:
    return next((r for r in rows if r["id"] == rec_id), None)


def event_rows(data: dict, event_id: str, status: str) -> list[dict]:
    rows = [a for a in data["attendance"] if a["event_id"] == event_id and a["status"] == status]
    return sorted(rows, key=lambda a: a["updated_at"])


def status_of(data: dict, event_id: str, member_id: str) -> str | None:
    a = next((a for a in data["attendance"] if a["event_id"] == event_id and a["member_id"] == member_id), None)
    return a["status"] if a else None


def attended_dates(data: dict, member_id: str) -> list[str]:
    dates = {e["id"]: e["date"] for e in data["events"]}
    return [dates[a["event_id"]] for a in data["attendance"]
            if a["member_id"] == member_id and a["status"] == "attending" and a["event_id"] in dates]


def play_count(data: dict, member_id: str) -> int:
    """終了した練習会への参加回数。"""
    return sum(d < today() for d in attended_dates(data, member_id))


def is_first_time(data: dict, member_id: str, event: dict) -> bool:
    """この日より前の練習会に参加していなければ初参加。"""
    return not any(d < event["date"] for d in attended_dates(data, member_id))


def level_of(count: int) -> tuple[tuple, tuple | None]:
    cur = [lv for lv in LEVELS if count >= lv[0]][-1]
    nxt = next((lv for lv in LEVELS if lv[0] > count), None)
    return cur, nxt


def family_of(data: dict, member_id: str) -> list[dict]:
    return [m for m in data["members"] if m["family_of"] == member_id]


# ---------------------------------------------------------------------------
# 書き込み操作
# ---------------------------------------------------------------------------

def login_token(member: dict) -> str:
    key = secret("token_secret", admin_password())
    return hashlib.sha256(f"{key}:{member['id']}:{member['pin_hash']}".encode()).hexdigest()[:16]


def pin_hash(member_id: str, pin: str) -> str:
    return hashlib.sha256(f"{member_id}:{pin}".encode()).hexdigest()


def login_or_register(name: str, pin: str, source: str, referrer: str) -> tuple[str, dict | None]:
    """お名前と好きな数字でログイン。未登録なら新規登録する。

    'ok' / 'new' / 'badpin'（数字ちがい）/ 'family'（家族として登録済み）を返す。
    """
    data = _fresh_data()
    m = next((m for m in data["members"] if norm(m["name"]) == norm(name)), None)
    if m:
        if m["family_of"]:
            return "family", None
        if not m["pin_hash"]:
            # 数字なしで登録済みの人（数字機能が無かった頃の登録・管理者のリセット後）：今回の数字を設定
            h = pin_hash(m["id"], pin)
            _update("members", m["id"], {"pin_hash": h})
            return "ok", m | {"pin_hash": h}
        return ("ok", m) if m["pin_hash"] == pin_hash(m["id"], pin) else ("badpin", None)
    mid = new_id()
    m = {"id": mid, "name": name.strip(), "pin_hash": pin_hash(mid, pin), "family_of": "",
         "source": source, "referrer": referrer.strip() if source == "友人・知人の紹介" else "",
         "created_at": now().isoformat(timespec="seconds")}
    _append("members", m)
    return "new", m


def add_member(name: str, family_of: str = "", source: str = "", referrer: str = "") -> str | None:
    """家族・代理登録用。名前が重複したら None。"""
    if any(norm(m["name"]) == norm(name) for m in _fresh_data()["members"]):
        return None
    mid = new_id()
    _append("members", {"id": mid, "name": name.strip(), "pin_hash": "", "family_of": family_of,
                        "source": source, "referrer": referrer, "created_at": now().isoformat(timespec="seconds")})
    return mid


def set_status(event_id: str, member_id: str, status: str | None) -> str:
    """出欠を登録。status=None で未回答に戻す。'ok' / 'full' を返す。"""
    data = _fresh_data()
    ev = find(data["events"], event_id)
    if ev is None:
        return "notfound"
    if status == "attending" and ev["capacity"]:
        others = [a for a in event_rows(data, event_id, "attending") if a["member_id"] != member_id]
        if len(others) >= ev["capacity"]:
            return "full"
    row = next((a for a in data["attendance"] if a["event_id"] == event_id and a["member_id"] == member_id), None)
    stamp = now().isoformat(timespec="seconds")
    if status is None:
        if row:
            _delete("attendance", {row["id"]})
    elif row:
        _update("attendance", row["id"], {"status": status, "updated_at": stamp})
    else:
        _append("attendance", {"id": new_id(), "event_id": event_id, "member_id": member_id,
                               "status": status, "updated_at": stamp})
    return "ok"


# ---------------------------------------------------------------------------
# スタイル
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700;800;900&display=swap');
:root { --ink:#111; --brand:#FE971A; --brand-light:#FEDC5C; --red:#E60012; --bg:#F2F2EE; --pill:#F1F1EC; --sub:#555; }
.stApp, .stApp button, .stApp input, .stApp textarea, .stApp label {
  font-family: 'M PLUS Rounded 1c', 'Hiragino Maru Gothic ProN', sans-serif !important;
}
.stApp { background: var(--bg); color: var(--ink); }
header[data-testid="stHeader"], #MainMenu, footer { display: none !important; }
.block-container { max-width: 640px; padding: 0 16px 60px !important; }

/* ---- ヒーロー ---- */
.st-key-hero {
  background: var(--ink); margin: 0 -16px 26px !important; padding: 40px 22px 28px;
  width: auto !important; max-width: none !important; align-self: stretch;
  border-radius: 0 0 28px 28px; position: relative; overflow: hidden;
}
.pk-logo {
  position: absolute; top: 18px; right: 22px; width: 150px; height: 150px; z-index: 1;
  transform: rotate(-8deg); pointer-events: none;
  filter: drop-shadow(0 0 22px rgba(254, 151, 26, .45)) drop-shadow(4px 6px 0 rgba(0, 0, 0, .55));
}
.pk-glow {
  position: absolute; top: -120px; right: -120px; width: 300px; height: 300px; border-radius: 50%;
  background: radial-gradient(circle, rgba(254, 151, 26, .28) 0%, rgba(254, 151, 26, 0) 70%);
  pointer-events: none;
}
.pk-hero-text { position: relative; z-index: 1; }
.pk-kicker { color: var(--brand); font-weight: 900; letter-spacing: .2em; font-size: .85rem; }
.pk-title { color: #fff; font-weight: 900; font-size: 2.9rem; line-height: 1.12; margin-top: 10px; }
.pk-title .y { color: var(--brand); }
.pk-sub { color: #cfcfcf; margin-top: 14px; font-weight: 700; }
.st-key-hero_actions { position: relative; z-index: 1; margin-top: 6px; align-items: center; }
.pk-count-chip {
  display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
  color: #fff; font-weight: 800; font-size: .9rem; line-height: 1.4; padding: 0 2px;
}
.pk-count-chip b { color: var(--brand); font-size: 1.05rem; }
.st-key-hero_actions > div { align-self: center; }
.st-key-hero_actions [data-testid="stMarkdown"], .st-key-hero_actions [data-testid="stMarkdownContainer"] { margin: 0 !important; }
@media (max-width: 480px) {
  /* スマホでも「名前・家族を追加・メンバー人数」が1行に並ぶよう小さめにする（入りきらなければ折り返す） */
  .st-key-hero { padding-left: 12px !important; padding-right: 12px !important; }
  .st-key-hero_actions { gap: 5px !important; }
  .st-key-hero_actions > div { flex: 0 0 auto !important; width: auto !important; }
  .st-key-hero_actions button div:has(> span > [data-testid="stIconMaterial"]) { display: none; }  /* ⌄ の矢印 */
  .st-key-hero .st-key-hero_actions button { padding: 5px 8px !important; min-height: 0 !important; }
  .st-key-hero .st-key-hero_actions button p { font-size: .78rem !important; white-space: nowrap; }
  .pk-count-chip { font-size: .72rem; gap: 2px; padding: 0; }
  .pk-count-chip b { font-size: 1em; }
}

.st-key-hero button {
  background: #222 !important; color: #fff !important; border: 2px solid #555 !important;
  border-radius: 999px !important; font-weight: 800 !important; padding: 6px 18px !important;
}

/* ---- 白カード（レベル・使い方・ログイン） ---- */
.pk-card, .st-key-howto, .st-key-theme, .st-key-login {
  background: #fff; border: 3px solid var(--ink); border-radius: 22px; padding: 16px 20px;
  box-shadow: 5px 7px 0 0 var(--brand), 5px 7px 0 3px var(--ink);
  margin: 0 8px 26px 0; color: var(--ink); font-weight: 800;
}
.st-key-howto { position: relative; padding: 20px 22px; }
.st-key-howto_close { position: absolute !important; top: 8px; right: 10px; z-index: 2; width: auto !important; }
.st-key-howto_close button { border: none !important; background: transparent !important; color: #999 !important; font-size: 1.3rem !important; }
.pk-howto-title { font-size: 1.2rem; font-weight: 900; margin-bottom: 6px; }
.pk-step { display: flex; align-items: center; gap: 12px; font-weight: 900; font-size: 1.08rem; margin: 12px 0; }
.pk-step .n {
  flex: none; width: 34px; height: 34px; border-radius: 50%; background: var(--brand);
  border: 2.5px solid var(--ink); display: grid; place-items: center; font-size: .95rem;
}
.pk-howto-note { color: var(--sub); font-weight: 700; font-size: .92rem; line-height: 1.7; margin-top: 10px; }
.pk-login-title { font-size: 1.2rem; font-weight: 900; }
.st-key-theme { padding: 20px 22px; }
.pk-theme-body { font-weight: 800; font-size: 1.05rem; line-height: 1.95; margin-top: 4px; }
.pk-mark { background: linear-gradient(transparent 58%, rgba(254, 151, 26, .55) 58%); padding: 0 1px; white-space: nowrap; }

/* ---- 見出し ---- */
.pk-h { display: flex; align-items: center; gap: 14px; font-weight: 900; letter-spacing: .18em; font-size: 1.1rem; margin: 30px 0 16px; }
.pk-h::after { content: ""; flex: 1; height: 4px; background: var(--ink); border-radius: 2px; }

/* ---- ニュース ---- */
.pk-news {
  background: var(--ink); color: #fff; border-radius: 26px; padding: 22px 22px 18px; margin: 0 8px 26px 0;
  box-shadow: 5px 7px 0 0 var(--brand), 5px 7px 0 3px var(--ink);
}
.pk-badge { display: inline-block; font-weight: 900; font-size: .88rem; letter-spacing: .12em; padding: 5px 12px; border-radius: 6px; }
.pk-badge.info { background: var(--brand); color: var(--ink); }
.pk-badge.event { background: var(--red); color: #fff; }
.pk-badge.other { background: #fff; color: var(--ink); }
.pk-news-title { color: var(--brand); font-weight: 900; font-size: 1.35rem; line-height: 1.45; margin: 12px 0 10px; }
.pk-news-body { white-space: pre-wrap; line-height: 1.85; font-size: 1rem; }
.pk-news-date { color: #999; margin-top: 12px; font-weight: 700; }

/* ---- 練習会カード ---- */
[class*="st-key-evcard_"] {
  background: #fff; border: 3px solid var(--ink); border-radius: 24px; overflow: hidden;
  box-shadow: 5px 7px 0 0 var(--brand), 5px 7px 0 3px var(--ink);
  margin: 0 8px 30px 0; gap: 0 !important;
}
.ev-top { display: grid; grid-template-columns: 98px 1fr; border-bottom: 3px solid var(--ink); }
.ev-date { background: var(--brand); border-right: 3px solid var(--ink); display: flex; flex-direction: column;
  align-items: center; justify-content: center; font-weight: 900; padding: 14px 4px; }
.ev-date .m { font-size: 1rem; }
.ev-date .d { font-size: 3.1rem; line-height: 1; margin: 4px 0; }
.ev-date .w { font-size: .95rem; }
.ev-info { padding: 16px 18px; font-weight: 800; color: var(--sub); line-height: 1.7; }
.ev-title { color: var(--ink); font-size: 1.45rem; font-weight: 900; margin-bottom: 4px; }
.ev-tag { display: inline-block; vertical-align: middle; background: var(--red); color: #fff; font-size: .85rem;
  border-radius: 7px; padding: 2px 10px; margin-left: 6px; }
.ev-desc { color: #777; font-weight: 700; }
.ev-body { padding: 18px 18px 10px; }
.ev-count { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; font-weight: 900; }
.ev-count .n { font-size: 2.7rem; line-height: 1; }
.ev-count .of { font-size: 1.3rem; }
.ev-chip { border: 2.5px solid var(--ink); border-radius: 999px; padding: 4px 14px; font-size: 1rem; }
.ev-chip.ask { background: var(--brand); }
.ev-chip.yes { background: var(--ink); color: var(--brand); }
.ev-chip.no { background: #fff; color: var(--sub); }
.ev-chip.full { background: var(--red); color: #fff; }
.ev-first { color: var(--sub); font-weight: 800; }
.pk-roster { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 12px; }
.pk-pill { display: inline-flex; align-items: center; gap: 8px; background: var(--pill); border: 2.5px solid var(--ink);
  border-radius: 999px; padding: 7px 15px; font-weight: 900; font-size: 1.05rem; }
.pk-pill.me { background: var(--brand); }
.pk-pill.first { background: var(--red); color: #fff; }
.pk-pill .hatsu { background: var(--ink); color: #fff; font-size: .78rem; border-radius: 5px; padding: 1px 6px; }
.pk-pill .src { font-size: .82rem; font-weight: 800; }
.ev-note { color: var(--sub); font-weight: 700; line-height: 1.7; margin: 8px 0; }
.ev-empty { color: #888; font-weight: 700; margin: 14px 0; }
.ev-who { font-weight: 900; margin: 8px 18px 0; }
[class*="st-key-evbtn_"] { padding: 6px 18px 12px; }
/* 参加ボタン（参加する／参加予定／満員です）は文字が収まる大きさにして中央に置く */
[class*="st-key-evbtn_"] > div { flex: 0 0 auto !important; margin: 0 auto; }
[class*="st-key-evbtn_"] button {
  min-height: 0 !important; padding: 6px 22px !important; border-radius: 999px !important;
  border: 3px solid var(--ink) !important; box-shadow: 3px 4px 0 var(--ink);
  font-weight: 900 !important; background: #fff !important; color: var(--ink) !important;
}
[class*="st-key-evbtn_"] button p { font-size: 1rem !important; font-weight: 900 !important; }
[class*="st-key-evbtn_"] button[kind="primary"] { background: var(--brand) !important; }
[class*="st-key-go_on_"] button { background: var(--ink) !important; color: var(--brand) !important; }
[class*="st-key-evbtn_"] button:disabled { background: #e6e6e6 !important; color: #999 !important; box-shadow: none; }
.ev-hint { color: var(--sub); font-size: .85rem; font-weight: 700; text-align: center; margin: 4px 0 22px; }
.ev-spacer { height: 14px; }
.st-key-login_js, div:has(> .st-key-login_js) { display: none !important; }

/* ---- 管理者メニューのタブ：スマホでも全部見えるよう折り返して並べる ---- */
.stTabs [role="tablist"] { flex-wrap: wrap; gap: 6px 8px; overflow: visible !important; padding-bottom: 6px; }
.stTabs [role="tab"] {
  border: 2px solid var(--ink); border-radius: 999px; padding: 4px 12px !important;
  height: auto !important; margin: 0 !important; background: #fff;
}
.stTabs [role="tab"][aria-selected="true"] { background: var(--brand); color: var(--ink) !important; }
.stTabs [role="tab"]::after, .stTabs [role="tab"]::before { display: none !important; }
.stTabs [role="tab"] p { font-weight: 800; color: var(--ink) !important; }
.stTabs .react-aria-SelectionIndicator { display: none !important; }  /* 選択中タブの赤い下線 */
[data-testid="stTabsScrollRight"], [data-testid="stTabsScrollLeft"] { display: none !important; }

@media (max-width: 480px) {
  .pk-title { font-size: 2.3rem; }
  .pk-logo { width: 128px; height: 128px; top: 16px; right: 10px; }
  .pk-sub { max-width: calc(100% - 128px); }  /* ロゴに重ならないよう折り返す */
  .ev-top { grid-template-columns: 84px 1fr; }
  .ev-date .d { font-size: 2.6rem; }
}
</style>
"""


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


@st.cache_data(show_spinner=False)
def logo_data_uri() -> str:
    with open(os.path.join(LOGO_DIR, "logo.webp"), "rb") as f:
        return "data:image/webp;base64," + base64.b64encode(f.read()).decode()


def esc(s) -> str:
    return html.escape(str(s or ""))


def md(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


LOGIN_COOKIE = "yamepick_me"  # ブラウザに保存するログイン情報（ID.トークン）


def login_value(m: dict) -> str:
    return f"{m['id']}.{login_token(m)}"


def member_from_login(data: dict, value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    mid, tok = value.split(".", 1)
    m = find(data["members"], mid)
    return m if m and not m["family_of"] and tok == login_token(m) else None


def current_member(data: dict) -> dict | None:
    """セッション → URLの ?me=（以前のブックマーク用）→ ブラウザに保存したログイン情報 の順で復元する。"""
    if mid := st.session_state.get("me"):
        return find(data["members"], mid)
    if q := st.query_params.get("me"):
        st.query_params.pop("me", None)  # 他の人に貼られないようURLからは消す
        if m := member_from_login(data, q):
            sign_in(m)
            return m
    if m := member_from_login(data, st.context.cookies.get(LOGIN_COOKIE)):
        st.session_state["me"] = m["id"]
        return m
    return None


def sign_in(m: dict) -> None:
    st.session_state["me"] = m["id"]
    # 次回以降も名前を覚えておくよう、ブラウザに保存する（remember_login で書き込む）
    st.session_state["_save_login"] = login_value(m)


def sign_out() -> None:
    st.session_state.pop("me", None)
    st.query_params.pop("me", None)
    st.session_state["_clear_login"] = True


def remember_login(me: dict | None) -> None:
    """ブラウザのクッキーと localStorage にログイン情報を保存・削除する。

    クッキーはサーバー側（st.context.cookies）で読む。localStorage は予備で、
    クッキーが届かなかったときは ?me= を付けて1回だけ開き直す。
    """
    cookie = f"{LOGIN_COOKIE}=' + v + '; path=/; max-age=31536000; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '')"
    if value := st.session_state.pop("_save_login", None):
        js = f"""const v = {json.dumps(value)};
document.cookie = '{cookie};
try {{ localStorage.setItem('{LOGIN_COOKIE}', v); sessionStorage.removeItem('yp_tried'); }} catch (e) {{}}"""
    elif st.session_state.pop("_clear_login", None):
        js = f"""document.cookie = '{LOGIN_COOKIE}=; path=/; max-age=0';
try {{ localStorage.removeItem('{LOGIN_COOKIE}'); }} catch (e) {{}}"""
    elif me is None:
        js = f"""try {{
  const v = localStorage.getItem('{LOGIN_COOKIE}');
  if (v && !sessionStorage.getItem('yp_tried')) {{
    sessionStorage.setItem('yp_tried', '1');
    // URLの ?me= で渡す（サーバーがすぐにURLから消す）。クッキーが届かない環境でも復元できる
    const u = new URL(location.href);
    u.searchParams.set('me', v);
    location.replace(u.toString());
  }} else if (v) {{
    localStorage.removeItem('{LOGIN_COOKIE}');  // 無効になったログイン情報
  }}
}} catch (e) {{}}"""
    else:
        return
    with st.container(key="login_js"):  # 画面には何も出さない（CSSで非表示）
        st.html(f"<script>{js}</script>", unsafe_allow_javascript=True)


def render_hero(data: dict, me: dict | None) -> None:
    with st.container(key="hero"):
        md(f"""<div class="pk-glow"></div><img class="pk-logo" src="{logo_data_uri()}" alt="YAME PICK">
<div class="pk-hero-text">
  <div class="pk-kicker">PICKLEBALL COMMUNITY</div>
  <div class="pk-title">YAME <span class="y">PICK</span><br>参加確認</div>
  <div class="pk-sub">ボタンひとつで、誰が来るかすぐわかる。</div>
</div>""")
        if not me:
            return
        with st.container(key="hero_actions", horizontal=True, gap="small"):
            with st.popover(f"🟠 {me['name']} 変更"):
                st.write(f"**{me['name']}** さんでログイン中")
                st.caption("別の人に切り替えるときはログアウトしてください。")
                if st.button("ログアウト", key="logout"):
                    sign_out()
                    st.rerun()
            fam = family_of(data, me["id"])
            with st.popover("👨‍👩‍👧 家族を追加"):
                st.caption("お子さんやご家族の分も、このスマホから出欠を登録できます。")
                for f in fam:
                    c1, c2 = st.columns([3, 1])
                    c1.write(f"👤 {f['name']}")
                    if c2.button("削除", key=f"famdel_{f['id']}"):
                        _delete("attendance", {f["id"]}, col="member_id")
                        _delete("members", {f["id"]})
                        st.rerun()
                name = st.text_input("家族のお名前", key="fam_name", max_chars=20, placeholder="例: のり娘")
                if st.button("追加する", key="fam_add", type="primary"):
                    if not name.strip():
                        st.warning("お名前を入力してください。")
                    elif add_member(name, family_of=me["id"], source="家族", referrer=me["name"]) is None:
                        st.warning("その名前はすでに使われています。")
                    else:
                        st.session_state["flash"] = f"{name.strip()} さんを追加しました！"
                        st.rerun()
            # 登録メンバーの人数（家族として追加した人も含む）
            md(f'<div class="pk-count-chip">👥 YAME PICK登録メンバー <b>{len(data["members"])}</b>人</div>')


def render_login() -> None:
    with st.container(key="login"):
        md('<div class="pk-login-title">👋 お名前と好きな数字を登録</div>')
        if who := st.session_state.get("need_pin"):
            st.info(f"{who} さん、好きな数字の登録をお願いします 🙏 下にお名前と好きな数字を入れて「はじめる」を押してください。")
        st.caption("一度登録すると、このスマホ（ブラウザ）では次回から自動でログインします。"
                   "別のスマホでは、同じお名前と数字を入れてください。")
        name = st.text_input("お名前（表示名）", value=st.session_state.get("need_pin", ""), max_chars=20, placeholder="例: のり")
        pin = st.text_input("好きな数字（4〜8桁）", max_chars=8, type="password", placeholder="例: 0123",
                            help="同じ名前の人と見分けるための数字です。忘れたときは管理者がリセットできます。")
        with st.expander("はじめての方はこちらも教えてください"):
            source = st.selectbox("YAME PICKを知ったきっかけ", ["（選択しない）"] + SOURCES)
            referrer = st.text_input("紹介してくれた人", max_chars=20) if source == "友人・知人の紹介" else ""
        if st.button("はじめる 🏓", type="primary", width="stretch"):
            pin = pin.strip()
            if not name.strip():
                st.warning("お名前を入力してください。")
            elif not (pin.isdigit() and 4 <= len(pin) <= 8):
                st.warning("好きな数字を4〜8桁で入力してください。")
            else:
                src = "" if source.startswith("（") else source
                res, m = login_or_register(name, pin, src, referrer)
                if res in ("ok", "new"):
                    st.session_state.pop("need_pin", None)
                    sign_in(m)
                    st.session_state["flash"] = ("ようこそ！登録しました 🎉" if res == "new"
                                                 else f"おかえりなさい、{m['name']} さん！")
                    st.rerun()
                elif res == "badpin":
                    st.error(f"「{name.strip()}」さんの数字がちがいます。"
                             "同じ名前の別の方は、「田中（八女）」のように少し変えた名前で登録してください。"
                             "数字を忘れたときは管理者に「数字のリセット」をお願いしてください。")
                else:
                    st.error("この名前はご家族として登録されています。登録した方のスマホから出欠を入れてください。")


def setting(data: dict, key: str) -> str:
    row = find(data["settings"], key)
    return row["value"] if row else (HOWTO_DEFAULT | THEME_DEFAULT)[key]


def save_setting(data: dict, key: str, value: str) -> None:
    if find(data["settings"], key):
        _update("settings", key, {"value": value})
    else:
        _append("settings", {"id": key, "value": value})


def howto_html(title: str, steps: str, note: str) -> str:
    lines = [ln.strip() for ln in steps.splitlines() if ln.strip()]
    step_html = "".join(f'<div class="pk-step"><span class="n">{i}</span>{esc(ln)}</div>'
                        for i, ln in enumerate(lines, 1))
    note_html = f'<div class="pk-howto-note">{esc(note).replace(chr(10), "<br>")}</div>' if note.strip() else ""
    return f'<div class="pk-howto-title">{esc(title)}</div>{step_html}{note_html}'


def render_howto(data: dict) -> None:
    if st.session_state.get("hide_howto") or st.query_params.get("guide") == "off":
        return
    with st.container(key="howto"):
        if st.button("×", key="howto_close", help="この案内を閉じる"):
            st.session_state["hide_howto"] = True
            st.query_params["guide"] = "off"
            st.rerun()
        md(howto_html(*(setting(data, k) for k in HOWTO_DEFAULT)))


def theme_html(title: str, body: str) -> str:
    # 「楽しむ」のようにカギカッコで囲んだ言葉にはマーカーを引く
    body_html = re.sub(r"「([^」]+)」", r'<span class="pk-mark">「\1」</span>', esc(body)).replace("\n", "<br>")
    return f'<div class="pk-howto-title">{esc(title)}</div><div class="pk-theme-body">{body_html}</div>'


def render_theme(data: dict) -> None:
    title, body = (setting(data, k) for k in THEME_DEFAULT)
    if not (title.strip() or body.strip()):
        return
    with st.container(key="theme"):
        md(theme_html(title, body))


def render_news(data: dict) -> None:
    if not data["news"]:
        return
    md('<div class="pk-h">NEWS</div>')

    def card(n: dict) -> str:
        icon, cls = NEWS_CATEGORIES.get(n["category"], NEWS_CATEGORIES["その他"])
        d = date.fromisoformat(n["date"]) if n["date"] else None
        return f"""<div class="pk-news">
  <span class="pk-badge {cls}">{icon} {esc(n['category'] or 'その他')}</span>
  <div class="pk-news-title">{esc(n['title'])}</div>
  <div class="pk-news-body">{esc(n['body'])}</div>
  <div class="pk-news-date">{f"{d.month}/{d.day}" if d else ""}</div>
</div>"""

    for n in data["news"][:3]:
        md(card(n))
    if len(data["news"]) > 3:
        with st.expander(f"過去のお知らせ（{len(data['news']) - 3}件）"):
            for n in data["news"][3:]:
                md(card(n))


def pill(data: dict, m: dict, ev: dict, me: dict | None) -> str:
    if is_first_time(data, m["id"], ev):
        src = m["source"] + (f"（{m['referrer']}）" if m["referrer"] else "")
        src_html = f'<span class="src">{esc(src)}</span>' if src else ""
        return f'<span class="pk-pill first">{esc(m["name"])}<span class="hatsu">初</span>{src_html}</span>'
    (_, _, icon), _ = level_of(play_count(data, m["id"]))
    mine = me and (m["id"] == me["id"] or m["family_of"] == me["id"])
    return f'<span class="pk-pill{" me" if mine else ""}">{esc(m["name"])} {icon}</span>'


def render_event(data: dict, ev: dict, me: dict | None, past: bool = False) -> None:
    d = date.fromisoformat(ev["date"])
    members = {m["id"]: m for m in data["members"]}
    going = [members[a["member_id"]] for a in event_rows(data, ev["id"], "attending") if a["member_id"] in members]
    n_first = sum(is_first_time(data, m["id"], ev) for m in going)
    cap = ev["capacity"]
    full = bool(cap) and len(going) >= cap

    tag = f'<span class="ev-tag">⚡ {esc(ev["tag"])}</span>' if ev.get("tag") else ""
    info = [f'🕘 {esc(ev["time"])}　📍 {esc(ev["place"])}' if ev.get("time") or ev.get("place") else "",
            f"👥 定員{cap}名" if cap else "",
            f'💰 参加費 {esc(ev["fee"])}' if ev.get("fee") else "",
            f'<div class="ev-desc">💬 {esc(ev["description"])}</div>' if ev.get("description") else ""]

    my = status_of(data, ev["id"], me["id"]) if me else None
    if past:
        chip = '<span class="ev-chip no">終了</span>'
    elif me and my == "attending":
        chip = '<span class="ev-chip yes">✓ 参加予定</span>'
    elif me and my == "absent":
        chip = '<span class="ev-chip no">不参加</span>'
    elif full:
        chip = '<span class="ev-chip full">満員</span>'
    elif me:
        chip = '<span class="ev-chip ask">👇 出欠を教えてね</span>'
    else:
        chip = ""
    first_txt = f'<span class="ev-first">🔰 初参加 {n_first}人</span>' if n_first else ""

    roster = ("".join(pill(data, m, ev, me) for m in going) if going
              else '<div class="ev-empty">まだ参加者はいません。一番乗りをどうぞ！🏓</div>')
    notes = ""
    if n_first:
        notes += '<div class="ev-note">🔴 赤いお名前 ＝ 今回が初参加の方です。みんなで歓迎しましょう！</div>'

    with st.container(key=f"evcard_{ev['id']}"):
        md(f"""<div class="ev-top">
  <div class="ev-date"><div class="m">{d.month}月</div><div class="d">{d.day}</div><div class="w">{WEEKDAYS[d.weekday()]}</div></div>
  <div class="ev-info"><div class="ev-title">{esc(ev['title'])}{tag}</div>{"".join(f"<div>{x}</div>" for x in info if x)}</div>
</div>
<div class="ev-body">
  <div class="ev-count"><span><span class="n">{len(going)}</span><span class="of"> / {cap}人 参加</span></span>{chip}{first_txt}</div>
  <div class="pk-roster">{roster}</div>
  {notes}
</div>""")
        if not past:
            people = [me] + family_of(data, me["id"]) if me else [None]
            for p in people:
                render_buttons(data, ev, p, show_name=len(people) > 1, full=full)
        md('<div class="ev-spacer"></div>')


def render_buttons(data: dict, ev: dict, person: dict | None, show_name: bool, full: bool) -> None:
    pid = person["id"] if person else "guest"
    s = status_of(data, ev["id"], pid) if person else None
    if show_name:
        md(f'<div class="ev-who">👤 {esc(person["name"])}</div>')
    # ボタンは1つだけ。押すたびに「参加」⇔「不参加」が切り替わる
    with st.container(key=f"evbtn_{ev['id']}_{pid}"):
        if s == "attending":
            go = st.button("✅ 参加予定", key=f"go_on_{ev['id']}_{pid}", width="content")
        else:
            go = st.button("満員です" if full else "🏓 参加する", key=f"go_{ev['id']}_{pid}",
                           type="primary", width="content", disabled=full)
    if s == "attending":
        md('<div class="ev-hint">もう一度押すと不参加になります</div>')
    if not go:
        return
    if person is None:
        st.session_state["flash_warn"] = "まずは上の「お名前と好きな数字を登録」からログインしてください 🙏"
        st.rerun()
    res = set_status(ev["id"], pid, "absent" if s == "attending" else "attending")
    if res == "full":
        st.session_state["flash_warn"] = "タッチの差で満員になりました…🙏"
    elif s == "attending":
        st.session_state["flash"] = f"{person['name']} さんを不参加にしました。"
    else:
        st.session_state["flash"] = f"{person['name']} さんの参加を登録しました！🏓"
    st.rerun()


def render_events(data: dict, me: dict | None) -> None:
    upcoming = [e for e in data["events"] if e["date"] >= today()]
    past = [e for e in data["events"] if e["date"] < today()]
    md('<div class="pk-h">SCHEDULE</div>')
    if not upcoming:
        md('<div class="ev-empty">次の練習会はまだ決まっていません。お楽しみに！</div>')
    for ev in upcoming:
        render_event(data, ev, me)
    if past:
        with st.expander(f"終了した練習会（{len(past)}件）"):
            for ev in reversed(past[-10:]):
                render_event(data, ev, me, past=True)


# ---------------------------------------------------------------------------
# 管理者メニュー
# ---------------------------------------------------------------------------

def render_admin(data: dict) -> None:
    md('<div class="pk-h">ADMIN</div>')
    with st.expander("🔧 管理者メニュー"):
        if not st.session_state.get("is_admin"):
            pw = st.text_input("管理者パスワード", type="password", key="admin_pw")
            if st.button("ログイン", key="admin_login"):
                if pw == admin_password():
                    st.session_state["is_admin"] = True
                    st.rerun()
                st.error("パスワードが違います。")
            return
        admin_share()
        t1, t2, t6, t7, t3, t4, t5 = st.tabs(
            ["📅 練習会", "📣 お知らせ", "📖 使い方", "🎯 テーマ", "✅ 出欠", "👥 メンバー", "📊 CSV"])
        with t1:
            admin_events(data)
        with t2:
            admin_news(data)
        with t6:
            admin_howto(data)
        with t7:
            admin_theme(data)
        with t3:
            admin_attendance(data)
        with t4:
            admin_members(data)
        with t5:
            admin_csv(data)
        if st.button("管理者ログアウト", key="admin_logout"):
            st.session_state["is_admin"] = False
            st.rerun()


def delete_event(event_id: str) -> None:
    _delete("attendance", {event_id}, col="event_id")
    _delete("events", {event_id})


def admin_row(prefix: str, rec_id: str, line: str, edit_form, warning: str, on_delete, done: str) -> None:
    """一覧の1行。「✏️ 編集」でその場に編集フォームを開き、「🗑 削除」は確認してから削除する。

    開いている行は session_state[f"{prefix}_open"] = (rec_id, "edit" | "delete") で覚える。
    """
    open_key = f"{prefix}_open"
    rid, mode = st.session_state.get(open_key) or (None, None)
    with st.container(border=True):
        c1, c2, c3 = st.columns([3.2, 1.3, 1.3], vertical_alignment="center")
        c1.write(line)
        if rid != rec_id:
            if c2.button("✏️ 編集", key=f"{prefix}_edit_{rec_id}", width="stretch"):
                st.session_state[open_key] = (rec_id, "edit")
                st.rerun()
            if c3.button("🗑 削除", key=f"{prefix}_del_{rec_id}", width="stretch"):
                st.session_state[open_key] = (rec_id, "delete")
                st.rerun()
            return
        if mode == "edit":
            edit_form()
            return
        st.warning(warning)
        y, no = st.columns(2)
        if y.button("削除する", key=f"{prefix}_del_ok_{rec_id}", type="primary", width="stretch"):
            on_delete()
            st.session_state.pop(open_key, None)
            st.session_state["flash"] = done
            st.rerun()
        if no.button("やめる", key=f"{prefix}_del_ng_{rec_id}", width="stretch"):
            st.session_state.pop(open_key, None)
            st.rerun()


def close_row(prefix: str) -> None:
    st.session_state.pop(f"{prefix}_open", None)


def split_time(text: str) -> tuple[str, str]:
    """「09:00〜11:00」→ ("09:00", "11:00")。読み取れなければ 9時〜11時。"""
    m = re.search(r"(\d{1,2}):(\d{2})\D+(\d{1,2}):(\d{2})", text or "")
    if not m:
        return "09:00", "11:00"
    return f"{int(m[1]):02d}:{m[2]}", f"{int(m[3]):02d}:{m[4]}"


def event_form(key: str, ev: dict | None, base: dict) -> None:
    """練習会の入力フォーム。ev があればその練習会を更新、なければ新規作成。"""
    with st.form(key):
        d = st.date_input("日付", value=date.fromisoformat(ev["date"]) if ev else now().date())
        title = st.text_input("タイトル", value=base.get("title", "エンジョイDAY"))
        tag = st.text_input("タグ（任意・例: 経験者メイン）", value=base.get("tag", ""))
        start0, end0 = split_time(base.get("time", ""))
        # 30分おき以外の時刻が登録済みでも、そのまま選べるように加える
        slots = sorted(set(TIME_SLOTS) | {start0, end0})
        c1, c2 = st.columns(2)
        start = c1.selectbox("開始", slots, index=slots.index(start0))
        end = c2.selectbox("終了", slots, index=slots.index(end0))
        place = st.text_input("場所", value=base.get("place", ""))
        c3, c4 = st.columns(2)
        cap = c3.number_input("定員", min_value=1, max_value=300, value=int(base.get("capacity") or 20))
        fee = c4.text_input("参加費", value=base.get("fee", ""))
        desc = st.text_input("ひとこと（絵文字OK）", value=base.get("description", ""))
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("保存" if ev else "作成する", type="primary", width="stretch")
        cancel = b2.form_submit_button("閉じる", width="stretch") if ev else False
    if cancel:
        close_row("adm_ev")
        st.rerun()
    if save:
        if end <= start:
            st.warning("終了時刻は開始時刻より後にしてください。")
            return
        values = {"date": d.isoformat(), "title": title.strip() or "練習会", "tag": tag.strip(), "time": f"{start}〜{end}",
                  "place": place, "capacity": int(cap), "fee": fee, "description": desc}
        if ev:
            _update("events", ev["id"], values)
            close_row("adm_ev")
            st.session_state["flash"] = "練習会を更新しました。"
        else:
            _append("events", values | {"id": new_id()})
            st.session_state["flash"] = "練習会を作成しました。"
        st.rerun()


def news_form(key: str, n: dict | None) -> None:
    """お知らせの入力フォーム。n があればそのお知らせを更新、なければ新規作成。"""
    n0 = n or {}
    with st.form(key):
        d = st.date_input("日付", value=date.fromisoformat(n0["date"]) if n0.get("date") else now().date())
        cats = list(NEWS_CATEGORIES)
        cat = st.selectbox("種類", cats, index=cats.index(n0["category"]) if n0.get("category") in cats else 0)
        title = st.text_input("タイトル（絵文字OK）", value=n0.get("title", ""))
        body = st.text_area("本文", value=n0.get("body", ""), height=160)
        b1, b2 = st.columns(2)
        save = b1.form_submit_button("保存" if n else "作成する", type="primary", width="stretch")
        cancel = b2.form_submit_button("閉じる", width="stretch") if n else False
    if cancel:
        close_row("adm_news")
        st.rerun()
    if save:
        if not title.strip():
            st.warning("タイトルを入力してください。")
            return
        values = {"date": d.isoformat(), "category": cat, "title": title.strip(), "body": body}
        if n:
            _update("news", n["id"], values)
            close_row("adm_news")
            st.session_state["flash"] = "お知らせを更新しました。"
        else:
            _append("news", values | {"id": new_id()})
            st.session_state["flash"] = "お知らせを作成しました。"
        st.rerun()


def share_url() -> str:
    """みんなに配るURL。?me=（自動ログイン用）などは付けない。"""
    if url := secret("app_url"):  # 独自ドメインなどで変えたいときは Secrets に app_url を書く
        return url.rstrip("/")
    url = (getattr(st.context, "url", "") or "").split("?")[0].split("#")[0]
    url = re.sub(r"/~/\+.*$", "", url)  # Streamlit Cloud の内部パスを取り除く
    return url.rstrip("/")


def admin_share() -> None:
    url = share_url()
    with st.container(border=True):
        md("**🔗 共有用のURL**")
        if not url:
            st.caption("URLを取得できませんでした。ブラウザのアドレス欄の「?」より前をコピーしてください。")
            return
        st.code(url, language=None)
        st.caption("枠の右上の📋でコピーできます（スマホは枠をタップすると📋が出ます）。Instagram・LINE にはこのURLを貼ってください"
                   "（ブラウザのアドレス欄の「?me=…」付きURLを貼ると、開いた人があなたとしてログインしてしまいます）。")
        with st.expander("📣 告知文のひな形（LINE・Instagram用）"):
            md("**LINE オープンチャット用**（トーク・ノート・アナウンスに）")
            st.code(f"🏓 YAME PICK 参加確認ページ\n"
                    f"練習会の日程と出欠はこちらから👇\n{url}\n\n"
                    f"お名前を登録して「🏓 参加する」を押すだけ！\n"
                    f"※最初に英語のボタン（Yes, get this app back up!）が出たら押してください",
                    language=None, wrap_lines=True)
            md("**Instagram 投稿・ストーリーズ用**（URLはプロフィールのリンク欄へ）")
            st.code("🏓 練習会の日程・出欠はプロフィールのリンクから！\n"
                    "お名前を登録して「参加する」を押すだけ✨\n"
                    "初心者・未経験の方も大歓迎🙌 パドル無料貸出🆓\n"
                    "#八女 #ピックルボール #YAMEPICK",
                    language=None, wrap_lines=True)


def admin_events(data: dict) -> None:
    md("**登録済みの練習会**")
    if not data["events"]:
        st.caption("まだ練習会はありません。")
    for e in sorted(data["events"], key=lambda e: e["date"], reverse=True):
        d = date.fromisoformat(e["date"])
        n = len(event_rows(data, e["id"], "attending"))
        past = "（終了）" if e["date"] < today() else ""
        admin_row(
            "adm_ev", e["id"],
            f"**{d.month}/{d.day}（{WEEKDAYS[d.weekday()][0]}）** {e['title']}　参加{n}人{past}",
            lambda e=e: event_form(f"adm_ev_form_{e['id']}", e, e),
            f"この練習会と、出欠データ（{n}人分）を削除します。元に戻せません。",
            lambda eid=e["id"]: delete_event(eid),
            f"{d.month}/{d.day} {e['title']} を削除しました。")
    st.divider()
    md("**＋ 新しい練習会を作る**")
    st.caption("直近の練習会の内容を初期値にしています。")
    # 新規作成時は直近の練習会の内容を初期値にする
    latest = max(data["events"], key=lambda e: e["date"]) if data["events"] else {}
    event_form("adm_ev_form_new", None, latest)


def admin_news(data: dict) -> None:
    md("**登録済みのお知らせ**")
    if not data["news"]:
        st.caption("まだお知らせはありません。")
    for i, n in enumerate(data["news"]):
        d = date.fromisoformat(n["date"]) if n["date"] else None
        when = f"**{d.month}/{d.day}**　" if d else ""
        shown = "" if i < 3 else "（過去のお知らせ）"
        admin_row(
            "adm_news", n["id"],
            f"{when}[{n['category'] or 'その他'}] {n['title']}{shown}",
            lambda n=n: news_form(f"adm_news_form_{n['id']}", n),
            f"お知らせ「{n['title']}」を削除します。元に戻せません。",
            lambda nid=n["id"]: _delete("news", {nid}),
            f"お知らせ「{n['title']}」を削除しました。")
    st.divider()
    md("**＋ 新しいお知らせを作る**")
    news_form("adm_news_form_new", None)


def admin_howto(data: dict) -> None:
    st.caption("トップの「使い方はかんたん！」の案内文を編集できます。手順は1行に1つ書くと、自動で 1, 2, 3… と番号がつきます。")
    with st.form("adm_howto_form"):
        title = st.text_input("タイトル", value=setting(data, "howto_title"))
        steps = st.text_area("手順（1行に1つ）", value=setting(data, "howto_steps"), height=130)
        note = st.text_area("補足（小さい文字で表示・空欄なら非表示）", value=setting(data, "howto_note"), height=90)
        save = st.form_submit_button("保存", type="primary", width="stretch")
    if save:
        if not title.strip() and not steps.strip():
            st.warning("タイトルか手順を入力してください。")
        else:
            for key, value in (("howto_title", title.strip()), ("howto_steps", steps), ("howto_note", note.strip())):
                save_setting(data, key, value)
            st.session_state["flash"] = "使い方の案内を保存しました。"
            st.rerun()
    md("**現在の表示**")
    with st.container(border=True):
        md(howto_html(title, steps, note))
    if st.session_state.get("hide_howto") or st.query_params.get("guide") == "off":
        st.caption("※ この端末では案内を × で閉じているため、トップには表示されていません。")
    if st.button("初期の文に戻す", key="adm_howto_reset"):
        _delete("settings", set(HOWTO_DEFAULT))
        st.session_state["flash"] = "使い方の案内を初期の文に戻しました。"
        st.rerun()


def admin_theme(data: dict) -> None:
    st.caption("「使い方」の下に出る「テーマ」の欄を編集できます。「 」で囲んだ言葉にはオレンジのマーカーがつきます。")
    with st.form("adm_theme_form"):
        title = st.text_input("タイトル", value=setting(data, "theme_title"))
        body = st.text_area("本文（改行はそのまま表示・絵文字OK）", value=setting(data, "theme_body"), height=170)
        save = st.form_submit_button("保存", type="primary", width="stretch")
    if save:
        for key, value in (("theme_title", title.strip()), ("theme_body", body.strip())):
            save_setting(data, key, value)
        st.session_state["flash"] = "テーマを保存しました。"
        st.rerun()
    md("**現在の表示**")
    with st.container(border=True):
        md(theme_html(title, body))
    st.caption("タイトルと本文を両方空にして保存すると、トップには表示されません。")
    if st.button("初期の文に戻す", key="adm_theme_reset"):
        _delete("settings", set(THEME_DEFAULT))
        st.session_state["flash"] = "テーマを初期の文に戻しました。"
        st.rerun()


def admin_attendance(data: dict) -> None:
    if not data["events"]:
        st.info("練習会がありません。")
        return
    labels = {e["id"]: f"{e['date']} {e['title']}" for e in data["events"]}
    upcoming = [e["id"] for e in data["events"] if e["date"] >= today()]
    ids = list(reversed([e["id"] for e in data["events"]]))
    sel = st.selectbox("練習会", ids, format_func=labels.get, key="adm_att_sel",
                       index=ids.index(upcoming[0]) if upcoming else 0)
    members = {m["id"]: m for m in data["members"]}
    for a in [a for a in data["attendance"] if a["event_id"] == sel]:
        m = members.get(a["member_id"])
        if not m:
            continue
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.write(f"{'🟠' if a['status'] == 'attending' else '⚪'} {m['name']}")
        other = "absent" if a["status"] == "attending" else "attending"
        if c2.button("不参加にする" if other == "absent" else "参加にする", key=f"adm_flip_{a['id']}"):
            _update("attendance", a["id"], {"status": other, "updated_at": now().isoformat(timespec="seconds")})
            st.rerun()
        if c3.button("🗑", key=f"adm_attdel_{a['id']}"):
            _delete("attendance", {a["id"]})
            st.rerun()
    st.divider()
    st.write("**代理で参加登録**（電話やLINEで連絡をくれた方など）")
    name = st.text_input("お名前", key="adm_proxy_name")
    if st.button("参加で登録", key="adm_proxy_add") and name.strip():
        m = next((m for m in data["members"] if norm(m["name"]) == norm(name)), None)
        mid = m["id"] if m else add_member(name)
        set_status(sel, mid, "attending")
        st.rerun()


def admin_members(data: dict) -> None:
    st.caption("好きな数字を忘れた方は「数字をリセット」してください。次にログインするときに新しい数字を設定できます。")
    members = sorted(data["members"], key=lambda m: m["created_at"])
    for m in members:
        c1, c2, c3 = st.columns([3.4, 1.8, 0.8], vertical_alignment="center")
        fam = f"（{find(data['members'], m['family_of'])['name']}さんの家族）" if m["family_of"] and find(data["members"], m["family_of"]) else ""
        pin_note = "" if m["family_of"] else ("　🔢数字あり" if m["pin_hash"] else "　（数字未設定）")
        c1.write(f"{m['name']}{fam}　参加{play_count(data, m['id'])}回{pin_note}")
        # 数字を忘れた人用：空にすると、次のログイン時に新しい数字を設定できる
        if m["pin_hash"] and c2.button("数字をリセット", key=f"adm_pin_{m['id']}", width="stretch"):
            _update("members", m["id"], {"pin_hash": ""})
            st.session_state["flash"] = f"{m['name']} さんの数字をリセットしました。次のログインで新しい数字を設定できます。"
            st.rerun()
        if c3.button("🗑", key=f"adm_memdel_{m['id']}"):
            _delete("attendance", {m["id"]}, col="member_id")
            _delete("members", {m["id"]})
            st.rerun()


def admin_csv(data: dict) -> None:
    members = {m["id"]: m for m in data["members"]}
    events = {e["id"]: e for e in data["events"]}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日付", "練習会", "名前", "出欠", "初参加", "きっかけ", "紹介者", "更新日時"])
    for a in sorted(data["attendance"], key=lambda a: (events.get(a["event_id"], {}).get("date", ""), a["updated_at"])):
        e, m = events.get(a["event_id"]), members.get(a["member_id"])
        if e and m:
            w.writerow([e["date"], e["title"], m["name"], "参加" if a["status"] == "attending" else "不参加",
                        "○" if a["status"] == "attending" and is_first_time(data, m["id"], e) else "",
                        m["source"], m["referrer"], a["updated_at"]])
    st.download_button("📥 出欠一覧（CSV）", buf.getvalue().encode("utf-8-sig"),
                       file_name="pikkurume_attendance.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="YAME PICK 参加確認", page_icon=os.path.join(LOGO_DIR, "logo.png"), layout="centered")
    md(CSS)
    try:
        data = load_data()
    except (KeyError, FileNotFoundError):
        items = "".join(f"\n- {m}" for m in missing_settings())
        st.error("Google スプレッドシートの設定が見つかりません。Streamlit Cloud の Settings → Secrets に"
                 f"次の項目を追加してください（secrets.toml.example 参照）。{items}")
        st.stop()
    except json.JSONDecodeError:
        st.error("gcp_service_account_json の貼り付け方が正しくありません。JSON ファイルの中身を "
                 "`'''` と `'''` の間に、最初の { から最後の } まで丸ごと貼り付けてください。")
        st.stop()
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("スプレッドシートが見つかりません。URLと、サービスアカウントへの共有（編集者）を確認してください。")
        st.stop()
    except gspread.exceptions.APIError as e:
        show_api_error(e)
        st.stop()

    try:
        render_page(data)
    except gspread.exceptions.APIError as e:
        show_api_error(e)


def show_api_error(e: gspread.exceptions.APIError) -> None:
    if e.response.status_code == 429:
        st.warning("ただいま混み合っています 🙏 1分ほど待ってから、もう一度お試しください。")
    else:
        st.error(f"Google スプレッドシートとの通信でエラーが起きました。少し待ってから再読み込みしてください。（{e}）")


def render_page(data: dict) -> None:
    me = current_member(data)
    if me and not me["pin_hash"] and not me["family_of"]:
        # 数字なしで登録した人（数字機能が無かった頃・管理者のリセット後）は、
        # 登録フォームでお名前と好きな数字を一緒に登録し直してもらう
        sign_out()
        st.session_state["need_pin"] = me["name"]
        me = None
    remember_login(me)
    render_hero(data, me)
    if msg := st.session_state.pop("flash", None):
        st.toast(msg, icon="🎉")
    if msg := st.session_state.pop("flash_warn", None):
        st.toast(msg, icon="⚠️")
    if not me:
        render_login()
    render_howto(data)
    render_theme(data)
    render_news(data)
    render_events(data, me)
    render_admin(data)


if __name__ == "__main__":
    main()
