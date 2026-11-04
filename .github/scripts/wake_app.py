"""Streamlit Community Cloud のアプリを開いて、休止していたら起こす。

GitHub Actions（.github/workflows/keep-awake.yml）から定期的に実行する。
使い方: APP_URL=https://xxx.streamlit.app python wake_app.py

- 休止画面の「Yes, get this app back up!」を、どの枠（iframe）の中にあっても探して押す
- アプリ本体（stApp）が読み込まれたら成功。エラー表示でも起きていれば成功とする
- 1分たっても表示されなければ読み込み直し、最大6分待つ
- 失敗したときは、画面の写真と、そのときの画面の文字をログに残す
"""

import os
import re
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

APP_URL = os.environ["APP_URL"]
WAKE_BUTTON = re.compile(r"get this app back up|wake.*up", re.I)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
CHECK_EVERY_MS = 5_000
RELOAD_AFTER_CHECKS = 12   # 約1分ごとに読み込み直す
MAX_CHECKS = 72            # 最大で約6分


def app_loaded(page) -> bool:
    for f in page.frames:
        try:
            if f.is_detached():
                continue
            if f.locator('[data-testid="stApp"]').count() or f.get_by_text("YAME").count():
                return True
        except PlaywrightError:
            continue
    return False


def press_wake_button(page) -> bool:
    for f in page.frames:
        try:
            button = f.get_by_role("button", name=WAKE_BUTTON)
            if button.count():
                button.first.click()
                return True
        except PlaywrightError:
            continue
    return False


def describe(page) -> str:
    """ログ用に、いまの画面の URL・タイトル・文字の先頭を返す。"""
    try:
        text = page.locator("body").inner_text(timeout=5_000)
    except PlaywrightError:
        text = ""
    return f"url={page.url} title={page.title()!r} text={' '.join(text.split())[:300]!r}"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=USER_AGENT, locale="ja-JP", viewport={"width": 1280, "height": 900})
        page.goto(APP_URL, wait_until="load", timeout=120_000)

        woke = False
        for i in range(1, MAX_CHECKS + 1):
            page.wait_for_timeout(CHECK_EVERY_MS)
            if app_loaded(page):
                print("アプリの表示を確認しました" + ("（休止から起こしました）" if woke else ""))
                browser.close()
                return 0
            if press_wake_button(page):
                woke = True
                print("休止中だったので起こします")
            elif i % RELOAD_AFTER_CHECKS == 0:
                print(f"まだ表示されないので読み込み直します（{i * CHECK_EVERY_MS // 1000}秒）:", describe(page))
                try:
                    page.reload(wait_until="load", timeout=120_000)
                except PlaywrightError as e:
                    print("読み込み直しに失敗:", e)

        print("アプリの表示を確認できませんでした:", describe(page), file=sys.stderr)
        page.screenshot(path="wake_failed.png", full_page=True)
        with open("wake_failed.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
