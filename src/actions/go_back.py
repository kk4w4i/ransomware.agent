async def run(page):
    await page.go_back(wait_until="load")
    return True
