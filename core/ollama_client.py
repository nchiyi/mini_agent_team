import logging
from openai import AsyncOpenAI
from config import OLLAMA_BASE_URL, OLLAMA_CLOUD_API_KEY, DEFAULT_MODEL

logger = logging.getLogger(__name__)

class OllamaClient:
    """
    OpenAI-compatible client for Ollama local endpoints.
    Provides async streaming and synchronous tool invocation.
    """
    def __init__(self, base_url=None, cloud_api_key=None):
        self.reinitialize(base_url, cloud_api_key)

    def reinitialize(self, base_url=None, cloud_api_key=None):
        """(Re)initialize the local and cloud OpenAI clients."""
        # Use provided or latest from config
        from config import OLLAMA_BASE_URL, OLLAMA_CLOUD_API_KEY
        
        url = base_url or OLLAMA_BASE_URL
        key = cloud_api_key or OLLAMA_CLOUD_API_KEY
        
        logger.info(f"Initialize OllamaClient with local: {url}, cloud: {'ENABLED' if key else 'DISABLED'}")
        
        self.local_client = AsyncOpenAI(
            base_url=url,
            api_key="ollama"
        )
        self.cloud_client = None
        if key:
            self.cloud_client = AsyncOpenAI(
                base_url="https://ollama.com/v1",
                api_key=key
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
