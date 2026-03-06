import logging
from openai import AsyncOpenAI
from config import OLLAMA_BASE_URL, OLLAMA_CLOUD_API_KEY, DEFAULT_MODEL

logger = logging.getLogger(__name__)

class OllamaClient:
    """
    OpenAI-compatible client for Ollama local endpoints.
    Provides async streaming and synchronous tool invocation.
    """
    def __init__(self, base_url=OLLAMA_BASE_URL, cloud_api_key=OLLAMA_CLOUD_API_KEY):
        logger.info(f"Initialize OllamaClient with local: {base_url}, cloud: {'ENABLED' if cloud_api_key else 'DISABLED'}")
        self.local_client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama" # api key is strictly required by the SDK but not verified by Ollama
        )
        self.cloud_client = None
        if cloud_api_key:
            self.cloud_client = AsyncOpenAI(
                base_url="https://ollama.com/v1",
                api_key=cloud_api_key
            )

    def _get_client_and_model(self, model_name: str):
        """Returns the appropriate (client, actual_model_name) based on prefix."""
        if model_name.startswith("cloud:"):
            if not self.cloud_client:
                raise ValueError("Ollama Cloud API Key not configured. Cannot use cloud models.")
            return self.cloud_client, model_name[6:]
        return self.local_client, model_name

    async def list_models(self) -> dict:
        """Fetch models from both local and cloud clients."""
        result = {"local": [], "cloud": []}
        try:
            local_res = await self.local_client.models.list()
            result["local"] = [m.id for m in local_res.data]
        except Exception as e:
            logger.error(f"Failed to fetch local models: {e}")

        if self.cloud_client:
            try:
                cloud_res = await self.cloud_client.models.list()
                result["cloud"] = [m.id for m in cloud_res.data]
            except Exception as e:
                logger.error(f"Failed to fetch cloud models: {e}")
                
        return result

    async def generate(self, messages, model=DEFAULT_MODEL, tools=None):
        """
        Standard chat completion generation. Used when we expect
        the model to potentially trigger a function call instead of streaming.
        """
        client, actual_model = self._get_client_and_model(model)
        response = await client.chat.completions.create(
            model=actual_model,
            messages=messages,
            tools=tools,
        )
        return response

    async def stream(self, messages, model=DEFAULT_MODEL):
        """
        Streams back delta text content.
        """
        client, actual_model = self._get_client_and_model(model)
        stream_resp = await client.chat.completions.create(
            model=actual_model,
            messages=messages,
            stream=True
        )
        
        async for chunk in stream_resp:
            if chunk.choices and chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
