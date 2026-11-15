"""YAME PICK 練習メニュー集（menus.json に追加していく）。1080x1920 の画像に入るだけ入れて、いっぱいになったら2枚目・3枚目へ。"""
import base64, json, os
from playwright.sync_api import sync_playwright
OUT = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(OUT)
u = lambda p, m: f"data:{m};base64," + base64.b64encode(open(p, "rb").read()).decode()
LOGO = u(f"{ROOT}/assets/logo.png", "image/png")
BL = u(f"{ROOT}/assets/fonts/MPLUSRounded1c-Black.ttf", "font/ttf")
BD = u(f"{ROOT}/assets/fonts/MPLUSRounded1c-Bold.ttf", "font/ttf")
MENUS = json.load(open(os.path.join(OUT, "menus.json"), encoding="utf-8"))

def card_html(i, m):
    pts = "".join(f"<li>{p}</li>" for p in m["points"])
    goal = f'<div class="goal">🎯 {m["goal"]}</div>' if m.get("goal") else ""
    return f'''<div class="card"><div class="ch"><div class="no">MENU {i:02d}</div><div class="t">{m["title"]}</div></div>
{goal}<ol>{pts}</ol></div>'''


def page_html(cards, page, pages):
    pg_label = f"（{page}/{pages}枚目）" if pages > 1 else ""
    return f"""<html><head><meta charset=utf-8><style>
    @font-face{{font-family:M;font-weight:900;src:url("{BL}")}} @font-face{{font-family:M;font-weight:700;src:url("{BD}")}}
    *{{margin:0;padding:0;box-sizing:border-box}}
    html,body{{width:1080px;overflow-x:hidden}}
    body{{height:1920px;background:#111;font-family:M,"Noto Color Emoji",sans-serif;color:#111;position:relative;overflow:hidden;
         padding:90px 60px 90px}}
    .g{{position:absolute;width:900px;height:900px;right:-360px;top:-260px;border-radius:50%;
       background:radial-gradient(circle,rgba(254,151,26,.5),rgba(254,151,26,0) 65%)}}
    .head{{display:flex;justify-content:space-between;align-items:center;color:#fff;position:relative}}
    .k{{color:#FE971A;font-size:30px;font-weight:900;letter-spacing:.14em}}
    h1{{font-size:96px;font-weight:900;line-height:1.1;margin-top:6px}} h1 span{{color:#FE971A}}
    .sub{{color:#ccc;font-size:32px;margin-top:10px}}
    .logo{{width:170px;transform:rotate(-8deg);filter:drop-shadow(6px 9px 0 rgba(0,0,0,.6))}}
    .list{{margin-top:44px;display:flex;flex-direction:column;gap:40px;position:relative}}
    .card{{background:#fff;border:7px solid #111;border-radius:36px;padding:30px 34px 34px;box-shadow:12px 14px 0 #FE971A}}
    .ch{{display:flex;align-items:center;gap:20px;flex-wrap:wrap}}
    .no{{background:#111;color:#FE971A;border-radius:999px;padding:4px 22px 8px;font-size:30px;font-weight:900;letter-spacing:.06em}}
    .t{{font-size:58px;font-weight:900;line-height:1.2}}
    .goal{{margin-top:16px;background:#FFF1DE;border-radius:18px;padding:12px 20px;font-size:32px;line-height:1.45;color:#333}}
    ol{{list-style:none;counter-reset:p;margin-top:18px;display:flex;flex-direction:column;gap:14px}}
    li{{counter-increment:p;position:relative;padding-left:72px;font-size:42px;font-weight:900;line-height:1.4}}
    li::before{{content:counter(p);position:absolute;left:0;top:2px;width:54px;height:54px;border-radius:50%;background:#FE971A;
               border:5px solid #111;display:grid;place-items:center;font-size:30px;line-height:1}}
    li em{{font-style:normal;white-space:nowrap;background:linear-gradient(transparent 58%,#FFD27A 58%)}}
    .foot{{color:#ccc;text-align:center;font-size:32px;position:absolute;left:0;right:0;bottom:90px}} .foot b{{color:#FE971A}}
    </style></head><body><div class=g></div>
    <div class=head><div><div class=k>YAME PICK</div><h1>練習<span>メニュー</span></h1><div class=sub>全{len(MENUS)}メニュー{pg_label}</div></div>
    <img class=logo src="{LOGO}"></div>
    <div class=list>{cards}</div>
    <div class=foot>思いついたら追加していきます 🏓　<b>@yamepick</b></div>
    </body></html>"""
LIST_TOP_PAD = 0
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium"); pg = b.new_page(viewport={"width": 1080, "height": 1920})
    f = os.path.join(OUT, "menu.html")
    # ① 全部を1枚に並べて、カード1枚ずつの高さと、カードを置ける範囲をはかる
    allc = [card_html(i, m) for i, m in enumerate(MENUS, 1)]
    open(f, "w", encoding="utf-8").write(page_html("".join(allc), 1, 1)); pg.goto("file://" + f); pg.wait_for_timeout(1000)
    hs = pg.evaluate("[...document.querySelectorAll('.card')].map(c => c.getBoundingClientRect().height)")
    top = pg.evaluate("document.querySelector('.list').getBoundingClientRect().top")
    limit = pg.evaluate("document.querySelector('.foot').getBoundingClientRect().top") - 40 - top
    GAP = 40
    # ② 入るだけ詰めて、入らなくなったら次の画像へ
    pages, cur, used = [], [], 0
    for c, h in zip(allc, hs):
        need = h + (GAP if cur else 0)
        if cur and used + need > limit:
            pages.append(cur); cur, used = [], 0; need = h
        cur.append(c); used += need
    pages.append(cur)
    for old in [x for x in os.listdir(OUT) if x.startswith("yamepick_practice_menu") and x.endswith(".jpg")]:
        os.remove(os.path.join(OUT, old))
    for n, cs in enumerate(pages, 1):
        open(f, "w", encoding="utf-8").write(page_html("".join(cs), n, len(pages))); pg.goto("file://" + f); pg.wait_for_timeout(800)
        name = "yamepick_practice_menu.jpg" if len(pages) == 1 else f"yamepick_practice_menu_{n}.jpg"
        pg.screenshot(path=os.path.join(OUT, name), type="jpeg", quality=92, clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
        print(name, len(cs), "menus")
    print("limit", limit, "heights", hs)
    b.close()
