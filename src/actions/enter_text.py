async def run(page, selector, text):
    element = await page.query_selector(selector)
    if element:
        await element.fill(text)
        return True
    return False
