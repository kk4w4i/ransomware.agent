import os
import asyncio
import functools
import httpx
from dotenv import load_dotenv
import google.generativeai as genai

# -------- Provider Interfaces --------
class BaseProvider:
    def __init__(self, model: str):
        self.model = model

    async def generate(self, prompt: str, system: str = "You are a helpful assistant") -> str:
        raise NotImplementedError


class DeepSeekProvider(BaseProvider):
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        self.api_key = api_key

    async def generate(self, prompt: str, system: str = "You are a helpful assistant") -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self.BASE_URL, json=payload, headers=headers, timeout=180)
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()
            except httpx.ReadTimeout:
                if attempt < max_retries:
                    await asyncio.sleep(2 * attempt)
                else:
                    raise
            except httpx.HTTPStatusError:
                raise


class GeminiProvider(BaseProvider):
    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        self.api_key = api_key
        self._configured = False

    def _ensure_config(self):
        if not self._configured:
            genai.configure(api_key=self.api_key)
            self._configured = True

    def _generate_sync(self, prompt: str, system: str) -> str:
        self._ensure_config()
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(f"{system}\n\n{prompt}")
        return (response.text or "").strip()

    async def generate(self, prompt: str, system: str = "You are a helpful assistant") -> str:
        loop = asyncio.get_running_loop()
        func = functools.partial(self._generate_sync, prompt, system)
        return await loop.run_in_executor(None, func)


# -------- Provider Factory --------
class ProviderFactory:
    MODEL_PREFIX_MAP = {
        "deepseek-": "deepseek",
        "gemini-": "gemini",
    }

    @staticmethod
    def infer_provider_from_model(model: str) -> str:
        m = model.lower()
        for prefix, provider in ProviderFactory.MODEL_PREFIX_MAP.items():
            if m.startswith(prefix):
                return provider
        return ""

    @staticmethod
    def create(provider: str, model: str, env: dict):
        provider = provider or ProviderFactory.infer_provider_from_model(model)
        if provider == "deepseek":
            api_key = env.get("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("Missing DEEPSEEK_API_KEY")
            return DeepSeekProvider(model=model, api_key=api_key)
        if provider == "gemini":
            api_key = env.get("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("Missing GOOGLE_API_KEY")
            return GeminiProvider(model=model, api_key=api_key)
        raise ValueError(f"Unsupported provider for model '{model}'. Provide explicit provider or extend factory.")


# -------- LLM Manager --------
class LLMManager:
    """
    High-level manager:
    - Accepts a model name and optional provider (auto-infers from model when possible).
    - Exposes uniform async API: llm_request, get_llm_plan, get_json_schema, get_formatted_json.
    """
    MODEL_METADATA = {
        "deepseek-chat": {"context_size": 64_000},
        "gemini-2.5-flash": {"context_size": 1_048_576},
        "claude-3.7-sonnet": {"context_size": 200_000},
        "gpt-4o-mini": {"context_size": 128_000}
    }

    def __init__(self, model: str, provider: str | None = None, default_context_size: int = 128_000):
        load_dotenv()
        self.model = model

        # infer provider: explicit > metadata hint > prefix
        meta = self.MODEL_METADATA.get(model, {})
        inferred = provider or meta.get("provider") or ProviderFactory.infer_provider_from_model(model)
        if not inferred:
            raise ValueError(f"Cannot infer provider for model '{model}'. Pass provider explicitly.")

        # build provider instance
        env = {
            "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY"),
            "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
        }
        self.provider = ProviderFactory.create(inferred, model, env)

        # context size
        self.context_size = int(meta.get("context_size", default_context_size))

    @staticmethod
    def clean_llm_json(s) -> str:
    # Remove triple-backtick code fences (supports ```json and just ```
        return s.replace('```json', '').replace('```', '').strip()

    async def llm_request(self, prompt: str, system: str = "You are a helpful assistant") -> str:
        return await self.provider.generate(prompt=prompt, system=system)

    async def get_llm_plan(self, prompt: str) -> str:
        return self.clean_llm_json(await self.llm_request(prompt))

    async def get_json_schema(self, html_content: str) -> str:
        prompt = (
            "Analyze the following website HTML content and output a JSON schema describing the main data "
            "structures, fields, and their types found in the content. Only return the JSON schema object, no explanations.\n\n"
            f"Website HTML content:\n{html_content}"
        )
        system = "You are an expert web data analyst. Only output a valid JSON schema."
        return await self.llm_request(prompt, system=system)

    async def get_formatted_json(self, prompt: str | None = None) -> str:
        prompt = prompt or "Format the following data as a well-structured JSON object:"
        return self.clean_llm_json(await self.llm_request(prompt))
