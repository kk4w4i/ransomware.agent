async def run(page, selector):
    element = await page.query_selector(selector)
    return await element.inner_text() if element else None