"""Instagram 投稿用の画像を作る（管理者メニュー「🖼 投稿画像」）。

アプリの見た目（黒・オレンジ・丸ゴシック）に合わせて、Pillow で PNG を描く。
Streamlit には依存しない。練習会のデータは app.py から dict で受け取る。

    events: [{"date": "2026-11-07", "title": ..., "tag": ..., "time": ..., "place": ...,
              "fee": ..., "capacity": 20, "going": 12, "first": 3}, ...]
"""

from __future__ import annotations

import calendar
import io
import os
import re
from datetime import date
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
LOGO_PATH = os.path.join(HERE, "assets", "logo.png")

INK = (17, 17, 17)
BRAND = (254, 151, 26)
BG = (242, 242, 238)
RED = (230, 0, 18)
WHITE = (255, 255, 255)
SUB = (85, 85, 85)
LIGHT = (255, 241, 222)
GREY = (225, 225, 225)
SUN, SAT = (230, 0, 18), (21, 101, 192)

W = 1080          # 画像の幅
HEADER_H = 250    # 黒いヘッダーの高さ
PAD = 60          # 左右の余白
SIZES = {"feed": (1080, 1350), "story": (1080, 1920)}
WEEK = "月火水木金土日"

# カラー絵文字は描けないので取り除く（記号・絵文字の範囲と、異体字セレクタ・結合子）
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿⬀-⯿️‍⃣]")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", _EMOJI.sub("", text or "")).strip()


@lru_cache(maxsize=None)
def font(size: int, black: bool = True) -> ImageFont.FreeTypeFont:
    name = "MPLUSRounded1c-Black.ttf" if black else "MPLUSRounded1c-Bold.ttf"
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


def text_w(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> float:
    return d.textlength(text, font=f)


def fit(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: float) -> str:
    """幅に収まらなければ末尾を「…」にする。"""
    if text_w(d, text, f) <= width:
        return text
    while text and text_w(d, text + "…", f) > width:
        text = text[:-1]
    return text + "…"


def card(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill=WHITE, radius: int = 34) -> None:
    """アプリのカードと同じ「オレンジの影＋黒い縁」の角丸の箱。"""
    x0, y0, x1, y1 = box
    d.rounded_rectangle((x0 + 10, y0 + 12, x1 + 10, y1 + 12), radius, fill=BRAND, outline=INK, width=5)
    d.rounded_rectangle(box, radius, fill=fill, outline=INK, width=6)


def pill(d: ImageDraw.ImageDraw, x: float, y: float, text: str, f, fill, color, pad_x: int = 18, h: int = 52) -> float:
    """角丸のラベルを描いて、右端の x を返す。"""
    w = text_w(d, text, f) + pad_x * 2
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=fill, outline=INK, width=4)
    d.text((x + pad_x, y + h / 2), text, font=f, fill=color, anchor="lm")
    return x + w


@lru_cache(maxsize=1)
def logo() -> Image.Image:
    im = Image.open(LOGO_PATH).convert("RGBA").resize((180, 180), Image.LANCZOS)
    return im.rotate(8, resample=Image.BICUBIC, expand=True)


def short(e: dict) -> str:
    d = date.fromisoformat(e["date"])
    return f"{d.month}/{d.day}"


def start_time(text: str) -> str:
    m = re.match(r"\s*(\d{1,2}):(\d{2})", text or "")
    return f"{int(m[1])}:{m[2]}" if m else ""


# ---------------------------------------------------------------------------
# 部品
# ---------------------------------------------------------------------------

def draw_header(im: Image.Image, y: int, subtitle: str) -> int:
    """黒い帯のヘッダー（ロゴ・YAME PICK・サブタイトル）。下端の y を返す。"""
    d = ImageDraw.Draw(im)
    h = HEADER_H
    d.rectangle((0, y, W, y + h), fill=INK)
    lg = logo()
    im.paste(lg, (W - lg.width - 24, y + (h - lg.height) // 2), lg)
    d.text((PAD, y + 34), "P I C K L E B A L L   C O M M U N I T Y", font=font(24, False), fill=BRAND)
    d.text((PAD, y + 66), "YAME", font=font(88), fill=WHITE)
    d.text((PAD + text_w(d, "YAME ", font(88)), y + 66), "PICK", font=font(88), fill=BRAND)
    sub = fit(d, clean(subtitle), font(44), W - PAD - 250)
    d.text((PAD, y + 176), sub, font=font(44), fill=WHITE)
    return y + h


def draw_calendar(im: Image.Image, y: int, year: int, month: int, events: list[dict]) -> int:
    """月のカレンダー（練習会の日はオレンジ）。下端の y を返す。"""
    d = ImageDraw.Draw(im)
    by_day: dict[str, list[dict]] = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    inner = 24
    cw = (W - PAD * 2 - inner * 2 - 6 * 8) / 7
    ch = 76
    top = y + 30
    h = 30 + 46 + len(weeks) * (ch + 8) + 22
    card(d, (PAD, top - 30 + 30, W - PAD, y + h + 30))
    y0 = top + 26
    for i, w in enumerate("日月火水木金土"):
        cx = PAD + inner + i * (cw + 8) + cw / 2
        color = SUN if i == 0 else SAT if i == 6 else SUB
        d.text((cx, y0 + 16), w, font=font(28), fill=color, anchor="mm")
    y0 += 46
    for week in weeks:
        for i, day in enumerate(week):
            x = PAD + inner + i * (cw + 8)
            iso = day.isoformat()
            evs = by_day.get(iso, []) if day.month == month else []
            fill = BRAND if evs else (247, 247, 243)
            if day.month != month:
                fill = BG
            d.rounded_rectangle((x, y0, x + cw, y0 + ch), 14, fill=fill)
            num_color = INK if evs else (SUN if i == 0 else SAT if i == 6 else INK)
            if day.month != month:
                num_color = (190, 190, 190)
            d.text((x + 10, y0 + 4), str(day.day), font=font(28), fill=num_color)
            if evs:
                t = start_time(evs[0]["time"])
                d.text((x + cw / 2, y0 + ch - 18), t + ("〜" if t else ""), font=font(22), fill=INK, anchor="mm")
                if len(evs) > 1:
                    d.text((x + cw - 10, y0 + 10), f"+{len(evs) - 1}", font=font(22), fill=INK, anchor="ra")
        y0 += ch + 8
    return y + h + 30 + 14


def draw_event_rows(im: Image.Image, y: int, events: list[dict]) -> int:
    """練習会の一覧（日付・タイトル・時間・場所・参加費）。下端の y を返す。"""
    d = ImageDraw.Draw(im)
    row_h = 126
    h = len(events) * row_h + 24
    card(d, (PAD, y + 30, W - PAD, y + 30 + h))
    yy = y + 30 + 12
    for i, e in enumerate(events):
        dt = date.fromisoformat(e["date"])
        bx = PAD + 24
        d.rounded_rectangle((bx, yy + 12, bx + 156, yy + row_h - 12), 20, fill=BRAND, outline=INK, width=4)
        d.text((bx + 78, yy + 46), short(e), font=font(38), fill=INK, anchor="mm")
        d.text((bx + 78, yy + 82), f"（{WEEK[dt.weekday()]}）", font=font(22), fill=INK, anchor="mm")
        tx = bx + 180
        right = W - PAD - 24
        title_f = font(36)
        tag = clean(e.get("tag", ""))
        title_w = right - tx - (text_w(d, tag, font(24)) + 56 if tag else 0)
        title = fit(d, clean(e["title"]) or "練習会", title_f, title_w)
        d.text((tx, yy + 12), title, font=title_f, fill=INK)
        if tag:
            pill(d, tx + text_w(d, title, title_f) + 12, yy + 16, tag, font(22), RED, WHITE, pad_x=12, h=36)
        line2 = "  ".join(x for x in (clean(e["time"]), f"場所 {clean(e['place'])}" if e.get("place") else "") if x)
        d.text((tx, yy + 60), fit(d, line2, font(25, False), right - tx), font=font(25, False), fill=SUB)
        if e.get("fee"):
            d.text((tx, yy + 90), fit(d, f"参加費 {clean(e['fee'])}", font(23, False), right - tx),
                   font=font(23, False), fill=SUB)
        yy += row_h
        if i < len(events) - 1:
            d.line((tx, yy, right, yy), fill=GREY, width=3)
    return y + 30 + h + 14


def draw_footer(im: Image.Image, y: int, main: str, sub: str) -> int:
    d = ImageDraw.Draw(im)
    h = 140
    d.rounded_rectangle((PAD, y + 30, W - PAD, y + 30 + h), 30, fill=INK)
    d.text((W / 2, y + 30 + 48), fit(d, main, font(38), W - PAD * 2 - 60), font=font(38), fill=BRAND, anchor="mm")
    d.text((W / 2, y + 30 + 102), fit(d, sub, font(26, False), W - PAD * 2 - 60), font=font(26, False),
           fill=WHITE, anchor="mm")
    return y + 30 + h + 40


def finish(content: Image.Image, used_h: int, size: str) -> bytes:
    """描いた中身を投稿サイズの画像に収めて PNG にする。

    入りきらないときは縮める。上端は黒いヘッダーの帯を横幅いっぱいに伸ばし、
    ストーリーズでは上に名前などが重なるので、ヘッダーの文字を少し下げる。
    """
    tw, th = SIZES[size]
    content = content.crop((0, 0, W, used_h))
    top = 0 if size == "feed" else 200
    room = th - top - (20 if size == "feed" else 230)
    scale = min(1.0, room / content.height)
    if scale < 1:
        content = content.resize((int(W * scale), int(content.height * scale)), Image.LANCZOS)
    out = Image.new("RGB", (tw, th), BG)
    ImageDraw.Draw(out).rectangle((0, 0, tw, top + int(HEADER_H * scale)), fill=INK)
    if size == "story":  # 余った高さは、ヘッダーの下と一番下に半分ずつ
        top_body = top + (room - content.height) // 2 if content.height < room else top
        ImageDraw.Draw(out).rectangle((0, 0, tw, top_body + int(HEADER_H * scale)), fill=INK)
        top = top_body
    out.paste(content, ((tw - content.width) // 2, top))
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 画像
# ---------------------------------------------------------------------------

def schedule_image(year: int, month: int, events: list[dict], size: str = "feed") -> bytes:
    """① 月間スケジュール（カレンダー＋一覧）。"""
    events = sorted(events, key=lambda e: e["date"])
    im = Image.new("RGB", (W, 4000), BG)
    y = draw_header(im, 0, f"{year}年{month}月の練習会・体験会")
    y = draw_calendar(im, y + 10, year, month, events)
    if events:
        y = draw_event_rows(im, y, events)
    y = draw_footer(im, y, "参加登録はプロフィールのリンクから", "初心者・未経験の方も大歓迎！パドル無料貸出  @yamepick")
    return finish(im, y, size)


def status_image(month: int, events: list[dict], size: str = "feed") -> bytes:
    """② 参加状況（残り席・満員だけ。参加予定人数や名前は載せない）。"""
    events = sorted(events, key=lambda e: e["date"])
    im = Image.new("RGB", (W, 4000), BG)
    y = draw_header(im, 0, f"参加者募集中！ {month}月の練習会")
    d = ImageDraw.Draw(im)
    y += 20
    for e in events:
        dt = date.fromisoformat(e["date"])
        h = 286 if e.get("capacity") else 236
        card(d, (PAD, y + 30, W - PAD, y + 30 + h))
        x0, top = PAD + 34, y + 30 + 28
        right = W - PAD - 34
        end = pill(d, x0, top, f"{short(e)}（{WEEK[dt.weekday()]}）", font(34), BRAND, INK, h=58)
        d.text((end + 20, top + 29), fit(d, clean(e["title"]) or "練習会", font(40), right - end - 20),
               font=font(40), fill=INK, anchor="lm")
        line2 = "  ".join(x for x in (clean(e["time"]), clean(e.get("place", ""))) if x)
        d.text((x0, top + 82), fit(d, line2, font(28, False), right - x0), font=font(28, False), fill=SUB)
        cap, going = int(e["capacity"] or 0), int(e["going"])
        # 参加予定人数は出さず、定員だけ
        d.text((x0, top + 156), f"定員 {cap}名" if cap else "定員なし", font=font(34), fill=INK, anchor="lm")
        # 状態
        if cap and going >= cap:
            chip, fill, color = "満員", RED, WHITE
        elif cap:
            chip, fill, color = f"残り {cap - going} 席", BRAND, INK
        else:
            chip, fill, color = "募集中", BRAND, INK
        cw = text_w(d, chip, font(36)) + 44
        pill(d, right - cw, top + 124, chip, font(36), fill, color, pad_x=22, h=64)
        # 埋まり具合のバー（人数の数字は出さない）
        if cap:
            by = top + 204
            d.rounded_rectangle((x0, by, right, by + 26), 13, fill=GREY, outline=INK, width=3)
            filled = x0 + (right - x0) * min(1, going / cap)
            if going:
                d.rounded_rectangle((x0, by, max(filled, x0 + 26), by + 26), 13, fill=BRAND, outline=INK, width=3)
        y += h + 30 + 10
    y = draw_footer(im, y, "空きがあるうちに参加登録を！", "プロフィールのリンクから  @yamepick")
    return finish(im, y, size)


def caption(year: int, month: int, events: list[dict], venue_name: str = "", venue_address: str = "") -> str:
    """投稿文（日程・場所・参加費・ハッシュタグ）。

    場所が ACCESS 欄の施設名（venue_name）と同じ練習会だけなら、その住所も添える。
    """
    events = sorted(events, key=lambda e: e["date"])
    lines = [f"🏓 YAME PICK {month}月の練習会・体験会のお知らせ", ""]
    for e in events:
        dt = date.fromisoformat(e["date"])
        tag = f"［{e['tag']}］" if e.get("tag") else ""
        lines.append(f"📅 {dt.month}/{dt.day}（{WEEK[dt.weekday()]}）{e['time']} {e['title']}{tag}")
    places = sorted({e["place"] for e in events if e.get("place")})
    fees = sorted({e["fee"] for e in events if e.get("fee")})
    lines.append("")
    core = lambda t: re.sub(r"[\s()（）・旧]", "", t)  # 「旧）忠見小学校体育館」と「旧忠見小学校」を同じ場所とみなす
    same_venue = venue_name and venue_address and places and all(core(venue_name) in core(p) for p in places)
    if places:
        lines.append("📍 " + "／".join(places) + (f"（{venue_address}）" if same_venue and len(places) == 1 else ""))
    if len(fees) == 1:
        lines.append(f"💰 参加費 {fees[0]}")
    lines += [
        "🔰 初心者・未経験の方も大歓迎！パドル無料貸出🆓",
        "✍️ 参加登録はプロフィールのリンクから",
        "",
        # ピックルボールに興味がある人に届きやすいハッシュタグを5つ
        "#ピックルボール #pickleball #ピックルボール好きと繋がりたい #ピックルボール初心者 #pickleballjapan",
    ]
    return "\n".join(lines)
