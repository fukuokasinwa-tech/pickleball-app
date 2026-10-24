"""Streamlit Community Cloud のアプリを開いて、休止していたら起こす。

GitHub Actions（.github/workflows/keep-awake.yml）から定期的に実行する。
使い方: APP_URL=https://xxx.streamlit.app python wake_app.py
"""

import os
import re
import sys

from playwright.sync_api import sync_playwright

APP_URL = os.environ["APP_URL"]
WAKE_BUTTON = re.compile(r"get this app back up", re.I)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(10_000)

        button = page.get_by_role("button", name=WAKE_BUTTON)
        if button.count():
            print("休止中だったので起こします")
            button.first.click()
        else:
            print("起動しています")

        # アプリ本体（Cloud では iframe の中）に「YAME」が出るまで、数秒おきに最大4分待つ
        for _ in range(80):
            if any(f.get_by_text("YAME").count() for f in page.frames if not f.is_detached()):
                print("アプリの表示を確認しました")
                break
            page.wait_for_timeout(3_000)
        else:
            print("アプリの表示を確認できませんでした", file=sys.stderr)
            page.screenshot(path="wake_failed.png", full_page=True)
            browser.close()
            return 1
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
