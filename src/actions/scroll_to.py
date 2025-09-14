async def run(page, selector):
    element = await page.query_selector(selector)
    if element:
        await element.scroll_into_view_if_needed()
        return True
    return False
