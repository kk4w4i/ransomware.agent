async def run(page, path="screenshot.png"):
    await page.screenshot(path=path)
    return path
