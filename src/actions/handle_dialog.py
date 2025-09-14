async def run(page):
    async def dialog_handler(dialog):
        await dialog.dismiss()
    page.once('dialog', dialog_handler)