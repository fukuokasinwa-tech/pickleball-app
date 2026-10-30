"""配布用チラシ（A4横に A5 縦のチラシを2枚並べたもの）を作る。

使い方:
    pip install segno playwright
    python flyer/build_flyer.py
できるもの（flyer/ の中）:
    yamepick_flyer_A4.pdf  … 印刷用（A4横・真ん中の点線で切ると A5 が2枚）
    yamepick_flyer_A4.png  … 確認用の画像
    flyer.html             … レイアウトの元（文章を変えるときはこのファイルの下の CONTENT を編集）
"""

from __future__ import annotations

import base64
import os
import sys

import segno

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
LOGO = os.path.join(ROOT, "assets", "logo.png")

ENTRY_URL = "https://fukuokasinwa-tech.github.io/pickleball-app/"  # 入口ページ（アプリへ移動）
INSTAGRAM_URL = "https://www.instagram.com/yamepick/"

# ---- 文章（ここを書き換えるとチラシの文が変わります） ---------------------------------
CONTENT = {
    "kicker": "PICKLEBALL COMMUNITY in 八女",
    "title_1": "ピックルボール、",
    "title_2": "はじめよう！",
    "lead": "いま話題の新スポーツを、八女で。",
    "what_title": "ピックルボールってなに？",
    "what_body": "テニス・卓球・バドミントンのいいところを集めた、アメリカ生まれのラケットスポーツ。"
                 "コートが小さく、ボールもゆっくり。運動が久しぶりの人でも、"
                 "<b>その日のうちにラリーが続く！</b>",
    "points": [
        ("🔰", "はじめてでも大丈夫", "ルールは5分で覚えられる。<br>経験者がやさしく教えます"),
        ("🏓", "パドル無料貸出", "道具はいりません。<br>動ける服で来るだけ！"),
        ("👨‍👩‍👧", "親子・シニアも", "世代をこえて、<br>みんなで楽しめる"),
    ],
    "theme": ["楽しむ", "つながる", "健康になる"],
    "info": [
        ("📅", "日時", "毎月開催！ 最新の日程は下のQRから"),
        ("📍", "場所", "旧忠見小学校 体育館（八女市忠見980）"),
        ("💰", "参加費", "はじめての方 1,000円 ／ 2回目から 500円"),
        ("👟", "持ち物", "動きやすい服装・室内シューズ・飲み物"),
    ],
    "qr_entry": "日程・参加登録",
    "qr_insta": "Instagram",
    "cta_1": "日程チェック＆参加登録は",
    "cta_2": "スマホでQRを読み取るだけ！",
    "cta_3": "はじめての方も、まずは見学からどうぞ",
    "footer": "YAME PICK ─ 八女でピックルボールを楽しむコミュニティ",
}
# ------------------------------------------------------------------------------------------


def qr_svg(url: str) -> str:
    # omitsize: 幅・高さを書かず viewBox だけにして、枠の大きさに合わせて縮める（切れないように）
    return segno.make(url, error="m").svg_inline(scale=4, dark="#111111", light="#ffffff", border=2, omitsize=True)


def data_uri(path: str, mime: str) -> str:
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def flyer_html(c: dict) -> str:
    points = "".join(f"""
      <div class="point"><div class="pi">{icon}</div><div><div class="pt">{t}</div><div class="pd">{d}</div></div></div>"""
                     for icon, t, d in c["points"])
    info = "".join(f"""
        <tr><td class="ii">{icon}</td><th>{k}</th><td>{v}</td></tr>""" for icon, k, v in c["info"])
    theme = "".join(f"<span>{t}</span>" for t in c["theme"])
    return f"""
  <section class="flyer">
    <div class="card">
      <header class="hero">
        <div class="ball"></div>
        <img class="logo" src="{LOGO_URI}" alt="YAME PICK">
        <div class="kicker">{c['kicker']}</div>
        <h1><span class="o">{c['title_1']}</span><br>{c['title_2']}</h1>
        <p class="lead">{c['lead']}</p>
      </header>
      <div class="body">
        <div class="what">
          <h2>{c['what_title']}</h2>
          <p>{c['what_body']}</p>
        </div>
        <div class="points">{points}
        </div>
        <div class="theme">テーマは {theme}</div>
        <table class="info">{info}
        </table>
        <div class="cta">
          <div class="cta-text"><div class="c1">{c['cta_1']}</div><div class="c2">{c['cta_2']}</div>
            <div class="c3">{c['cta_3']}</div></div>
          <div class="qr">{QR_ENTRY}<div>{c['qr_entry']}</div></div>
          <div class="qr">{QR_INSTA}<div>{c['qr_insta']}</div></div>
        </div>
      </div>
      <footer>{c['footer']}</footer>
    </div>
  </section>"""


CSS = """
@font-face { font-family: "MPR"; font-weight: 700; src: url("FONT_BOLD"); }
@font-face { font-family: "MPR"; font-weight: 900; src: url("FONT_BLACK"); }
@page { size: 297mm 210mm; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
:root { --ink: #111; --brand: #FE971A; --light: #FFF1DE; --red: #E60012; --bg: #F2F2EE; }
html, body { width: 297mm; height: 210mm; }
body {
  font-family: "MPR", "Noto Color Emoji", sans-serif; font-weight: 700; color: var(--ink);
  display: flex; -webkit-print-color-adjust: exact; print-color-adjust: exact; background: #fff;
}
/* A5（148.5 x 210mm）を左右に2枚。家庭用プリンタの余白で切れないよう、内側に余白をとる */
.flyer { width: 148.5mm; height: 210mm; padding: 6mm; position: relative; }
.flyer + .flyer::before {
  content: "✂ ここで切る"; position: absolute; left: -0.2mm; top: 0; bottom: 0; width: 0;
  border-left: 0.4mm dashed #999; font-size: 2.6mm; color: #999; writing-mode: vertical-rl;
  padding-top: 3mm; text-indent: 1mm;
}
.card {
  height: 100%; border: 0.9mm solid var(--ink); border-radius: 6mm; overflow: hidden;
  display: flex; flex-direction: column; background: var(--bg);
}
.hero { flex: none; background: var(--ink); color: #fff; padding: 5.5mm 7mm 5mm; position: relative; overflow: hidden; }
.ball {
  position: absolute; right: -16mm; top: -16mm; width: 56mm; height: 56mm; border-radius: 50%;
  background: radial-gradient(circle, rgba(254,151,26,.38), rgba(254,151,26,0) 68%);
}
.logo { position: absolute; right: 4mm; top: 9mm; width: 27mm; transform: rotate(-8deg);
        filter: drop-shadow(0.8mm 1.2mm 0 rgba(0,0,0,.55)); }
.kicker { color: var(--brand); font-size: 2.9mm; letter-spacing: .12em; font-weight: 900; }
h1 { font-weight: 900; font-size: 10.2mm; line-height: 1.18; margin-top: 2mm; letter-spacing: .01em; }
h1 .o { color: var(--brand); }
.lead { margin-top: 2.6mm; font-size: 4.2mm; color: #eee; }
.body { flex: 1; min-height: 0; padding: 4mm 6mm 3.5mm; display: flex; flex-direction: column; justify-content: space-between; gap: 2.4mm; }
.what { background: #fff; border: 0.6mm solid var(--ink); border-radius: 4mm; padding: 2.6mm 4mm;
        box-shadow: 1.2mm 1.5mm 0 var(--brand); }
h2 { font-size: 4.6mm; font-weight: 900; margin-bottom: 1.2mm; }
h2::before { content: "🏓 "; }
.what p { font-size: 3.25mm; line-height: 1.6; }
.what b { background: linear-gradient(transparent 55%, rgba(254,151,26,.55) 55%); font-weight: 900; }
.points { display: grid; grid-template-columns: repeat(3, 1fr); gap: 2.4mm; }
.point { background: var(--brand); border: 0.6mm solid var(--ink); border-radius: 4mm; padding: 2mm 2mm;
         text-align: center; display: flex; flex-direction: column; align-items: center; gap: 1mm; }
.pi { font-size: 6.6mm; line-height: 1; }
.pt { font-size: 3.5mm; font-weight: 900; }
.pd { font-size: 2.55mm; line-height: 1.45; margin-top: .6mm; }
.theme { text-align: center; font-size: 3.4mm; font-weight: 900; }
.theme span { display: inline-block; background: var(--ink); color: var(--brand); border-radius: 99mm;
              padding: .6mm 2.6mm; margin: 0 .7mm; }
.info { width: 100%; background: #fff; border: 0.6mm solid var(--ink); border-radius: 4mm; border-collapse: separate;
        padding: 1.8mm 3mm; font-size: 3.05mm; line-height: 1.45; }
.info th { white-space: nowrap; text-align: left; padding: .6mm 2mm .6mm .6mm; font-weight: 900; vertical-align: top; }
.info td { padding: .6mm 0; vertical-align: top; }
.info .ii { width: 5mm; }
.cta { display: flex; gap: 2.4mm; align-items: center; background: var(--ink); border-radius: 4mm; padding: 2.6mm 3mm; }
.cta-text { flex: 1; color: #fff; }
.cta .c1 { font-size: 3.2mm; }
.cta .c2 { font-size: 4.3mm; font-weight: 900; color: var(--brand); margin-top: .4mm; }
.cta .c3 { font-size: 2.5mm; color: #ccc; margin-top: 1mm; }
.qr { width: 19.5mm; background: #fff; border-radius: 2.4mm; padding: 1.2mm; text-align: center;
      font-size: 2.2mm; font-weight: 900; line-height: 1.2; }
.qr svg { width: 100%; height: auto; display: block; }
footer { flex: none; background: var(--ink); color: #fff; text-align: center; font-size: 2.8mm; padding: 2.4mm 0; }
"""


def build() -> str:
    global LOGO_URI, QR_ENTRY, QR_INSTA
    LOGO_URI = data_uri(LOGO, "image/png")
    QR_ENTRY = qr_svg(ENTRY_URL)
    QR_INSTA = qr_svg(INSTAGRAM_URL)
    css = (CSS.replace("FONT_BOLD", data_uri(os.path.join(FONT_DIR, "MPLUSRounded1c-Bold.ttf"), "font/ttf"))
              .replace("FONT_BLACK", data_uri(os.path.join(FONT_DIR, "MPLUSRounded1c-Black.ttf"), "font/ttf")))
    one = flyer_html(CONTENT)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>YAME PICK チラシ（A4にA5×2）</title>
<style>{css}</style></head>
<body>{one}{one}</body></html>"""


def main() -> None:
    from playwright.sync_api import sync_playwright

    html_path = os.path.join(HERE, "flyer.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build())
    exe = os.environ.get("CHROMIUM_PATH")  # 入っているブラウザを使うときに指定
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 1123, "height": 794}, device_scale_factor=3)
        page.goto("file://" + html_path)
        page.wait_for_timeout(1500)  # フォントの読み込みを待つ
        page.pdf(path=os.path.join(HERE, "yamepick_flyer_A4.pdf"), width="297mm", height="210mm",
                 print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        page.screenshot(path=os.path.join(HERE, "yamepick_flyer_A4.png"), full_page=False)
        browser.close()
    print("作成しました:", os.path.join(HERE, "yamepick_flyer_A4.pdf"))


if __name__ == "__main__":
    sys.exit(main())
