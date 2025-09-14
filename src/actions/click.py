async def run(page, selector):
    element = await page.query_selector(selector)
    if element:
        await element.click()
        return True
    return False