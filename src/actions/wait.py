import asyncio

async def run(page, selector, timeout=20000):
    element = await page.query_selector(selector)
    if not element:
        await page.wait_for_selector(selector, timeout=timeout)
        element = await page.query_selector(selector)
        if not element:
            raise Exception(f"No element found for selector: {selector}")
    initial_html = await element.inner_html()

    await page.wait_for_function(
        """([el, initial]) => el && el.innerHTML !== initial""",
        arg=[element, initial_html],
        timeout=timeout
    )
    return True