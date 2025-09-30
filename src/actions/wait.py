from playwright.async_api import TimeoutError as PlaywrightTimeoutError


async def run(page, selector, timeout=20000):
    selectors_to_try = [selector]

    if "file-browser" in selector and ".file-browser" not in selector:
        selectors_to_try.append(".file-browser")

    last_error: Exception | None = None
    for target in selectors_to_try:
        try:
            element = await page.wait_for_selector(
                target,
                state="visible",
                timeout=timeout,
            )
            if element:
                return True
        except PlaywrightTimeoutError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error

    raise Exception(f"No element found for selector(s): {selectors_to_try}")
