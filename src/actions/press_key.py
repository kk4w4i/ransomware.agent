async def run(page, selector, key):
    element = await page.query_selector(selector)
    if element:
        await element.press(key)
        return True
    return False
