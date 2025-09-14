async def run(page, selector):
    element = await page.query_selector(selector)
    if element:
        html = await element.inner_html()
        return html
    return None
