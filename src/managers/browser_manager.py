import importlib
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError # type: ignore
import asyncio
import traceback

from src.contexts.sensingContext import SensingContext
from src.managers.llm_manager import LLMManager
from src.utils.text_utils import clean_text

class BrowserManager:
    _instance = None

    def __init__(self, start_url: str, headless: bool, llm: LLMManager, victims_collection, session_collection, hf_token: str = None):
        if not start_url:
            raise ValueError("Start URL cannot be empty")
        if BrowserManager._instance:
            raise RuntimeError("BrowserManager is already running")
        self._start_url = start_url
        self._playwright = None
        self._browser = None
        self._page = None
        self._actions = {
            "enter_text": "src.actions.enter_text",
            "press_key": "src.actions.press_key",
            "wait": "src.actions.wait",
            "click": "src.actions.click",
            "scroll_to": "src.actions.scroll_to",
            "handle_dialog": "src.actions.handle_dialog",
            "scrape_and_store": "src.actions.scrape_and_store"
        }
        BrowserManager._instance = self
        self.victims_collection = None
        self.session_collection = None
        self.headless = headless
        self.victims_collection = victims_collection
        self.session_collection = session_collection
        self.hf_token = hf_token
        self.llm = llm
    
    async def start(self):
        async def _launch_browser():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                proxy={"server": "socks5://localhost:9050"}, 
                headless=self.headless)
            self._page = await self._browser.new_page(ignore_https_errors=True)

        retries = 5
        for attempt in range(retries):
            try:
                await _launch_browser()
                await self._page.goto(self._start_url)
                return  # Success!
            except PlaywrightTimeoutError:
                print(f"Timeout on attempt {attempt+1}/{retries}. Resetting browser...")
                await self.exit()  # await, don't just call
                if attempt == retries - 1:
                    print("Unable to open page after 5 attempts.")
                    raise
                # else, next attempt will retry

    def list_actions(self):
        return list(self._actions.keys())

    async def execute(self, actions: list):
        results = []
        for action in actions:
            name = action.get("action")
            selector = action.get("selector")
            params = action.get("params", {})
            args = []
            kwargs = params or {}

            # Determine argument structure based on action
            if name == "wait" and selector:
                args = [selector]
                kwargs = {}
            elif selector:
                args = [selector]
                kwargs = params or {}

            print(f"[EXECUTE] Action: {name}")
            print(f"[EXECUTE] Args: {args}")
            print(f"[EXECUTE] Kwargs: {kwargs}")

            try:
                # Handle special logic for 'scrape_and_store'
                if name == "scrape_and_store":
                    mod = importlib.import_module(self._actions[name])
                     # scrape_and_store expects page and context_size
                    result = await mod.run(self._page, self.victims_collection, self.session_collection, self.llm, self.hf_token)
                    print(f"[EXECUTE] Result: {result}")
                    results.append(result)
                else:
                    mod = importlib.import_module(self._actions[name])
                    result = await mod.run(self._page, *args, **kwargs)
                    print(f"[EXECUTE] Result: {result}")
                    results.append(result)
            except Exception as e:
                print(f"[EXECUTE ERROR] Action: {name}, Error: {e}")
                traceback.print_exc()
                results.append(None)
        print(f"[EXECUTE] All Results: {results}")
        return results

    def chunk_text(self, text, chunk_size, overlap_ratio=0.1):
        chunks = []
        step = int(chunk_size * (1 - overlap_ratio))
        for start in range(0, len(text), step):
            chunk = text[start:start + chunk_size]
            if chunk:
                chunks.append(chunk)
            if start + chunk_size >= len(text):
                break
        return chunks

    async def summarize_chunk(self, chunk, chunk_idx, total_chunks):
        prompt = (
            f"You are helping summarize website source code for a vision-assisted autonomous web agent.\n"
            f"This is chunk {chunk_idx+1} of {total_chunks} of the raw HTML/visible content. "
            f"Provide a concise expert summary of what this chunk presents to the user (extract structure, main data, sections, hidden links/forms, etc)."
        )
        summary = await self.llm.llm_request(chunk, system=prompt)
        return summary

    async def sense(self):  # context_size in chars for the LLM
        # TODO: incorporate visual queues using screen shots
        # screenshot_description = await self._page.screenshot(full_page=True)

        await self._page.wait_for_load_state('load')

        html_content = await self._page.content()

        html_content = await clean_text(html_content)

        print(f"👁️ Sensed {len(html_content)} characters of visible text.")

        max_length = self.llm.context_size * 2

        # Decide on summarization strategy
        if len(html_content) <= max_length:
            description = await self.summarize_chunk(html_content, 0, 1)
        else:
            chunks = self.chunk_text(html_content, max_length, overlap_ratio=0.1)
            print(f"Summarizing {len(chunks)} chunks concurrently...")
            # Run all chunk summarizations in parallel
            tasks = [
                self.summarize_chunk(chunk, i, len(chunks))
                for i, chunk in enumerate(chunks)
            ]
            summaries = await asyncio.gather(*tasks)
            merged_summary_text = "\n\n".join(summaries)
            print("Merging chunk summaries with LLM...")
            final_prompt = (
                "Given the following webpage chunk summaries, create a single coherent, structured, "
                "high-level natural language description for what the page presents, including key data and visual structures, for a web automation agent:\n\n"
                f"{merged_summary_text}"
            )
            description = await self.llm.llm_request(merged_summary_text, system=final_prompt)

        dom_content = description

        print(dom_content)

        url = self._page.url

        self.sensingcontext = SensingContext(
            url=url,
            domContent=dom_content,
        )
        return self.sensingcontext


    async def exit(self):
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        BrowserManager._instance = None