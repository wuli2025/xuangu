import asyncio
from playwright.async_api import async_playwright

OUT = "D:/polaris/polaris-app/.tmp-shots"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9223")
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if "localhost" in pg.url or "tauri" in pg.url or pg.url.startswith("http"):
                page = pg
                break
        if page is None:
            page = ctx.pages[0]
        print("page url:", page.url)
        # 等启动流程走完：输入卡出现（splash/env 覆盖层消失后才可交互）
        await page.wait_for_selector(".input-card", timeout=60000)
        await page.wait_for_timeout(2500)  # 等 splash 淡出动画
        await page.screenshot(path=f"{OUT}/app-1-default.png")
        await page.hover(".input-card")
        await page.wait_for_timeout(400)
        await page.screenshot(path=f"{OUT}/app-2-hover.png")
        await page.click(".input-card textarea")
        await page.wait_for_timeout(400)
        await page.screenshot(path=f"{OUT}/app-3-focus.png")
        print("done")

asyncio.run(main())
