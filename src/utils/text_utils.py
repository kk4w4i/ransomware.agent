import re
from html import unescape

async def clean_text(text):
    text = unescape(text)
    text = re.sub(r'\xa0+', ' ', text)
    text = re.sub(r'&nbsp;+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
