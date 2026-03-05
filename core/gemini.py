"""
Gemini Client — Native Google GenAI SDK wrapper.

Replaces the old CLI subprocess approach with a persistent,
high-performance API client supporting:
  - Persistent connection (no cold starts)
  - Function Calling (native tool use)
  - Streaming responses
  - Precise token counting
"""
import logging
from typing import Optional, AsyncIterator

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiClient:
    """Persistent Google GenAI client with streaming and tool support."""

    def __init__(self, client: genai.Client, default_model: str = "gemini-2.0-flash"):
        self.client = client
        self.default_model = default_model

    # ------------------------------------------------------------------
    # Core: single-shot generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        tools: Optional[list] = None,
        temperature: float = 0.7,
    ) -> tuple[str, dict]:
        """
        Generate content via the Gemini API.

        Returns:
            (response_text, usage_dict)
        """
        model_name = model or self.default_model

        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction
        if tools:
            config.tools = tools

        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            text = response.text or "(無輸出)"

            # Extract precise token usage
            usage = {"model": model_name}
            if response.usage_metadata:
                usage["prompt_tokens"] = response.usage_metadata.prompt_token_count or 0
                usage["completion_tokens"] = response.usage_metadata.candidates_token_count or 0
                usage["total_tokens"] = response.usage_metadata.total_token_count or 0

            return text, usage

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return f"❌ Gemini API 錯誤: {e}", {"model": model_name}

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------
    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Stream content from Gemini, yielding text chunks.
        """
        model_name = model or self.default_model

        config = types.GenerateContentConfig(
            temperature=0.7,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        try:
            for chunk in self.client.models.generate_content_stream(
                model=model_name,
                contents=prompt,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            yield f"\n\n❌ Streaming 錯誤: {e}"

    # ------------------------------------------------------------------
    # Function Calling generation
    # ------------------------------------------------------------------
    async def generate_with_tools(
        self,
        prompt: str,
        tools: list,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> "genai.types.GenerateContentResponse":
        """
        Generate with function calling tools.
        Returns the raw response for the caller to inspect
        function_calls vs text.
        """
        model_name = model or self.default_model

        config = types.GenerateContentConfig(
            tools=tools,
            temperature=0.4,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return response
        except Exception as e:
            logger.error(f"Gemini function calling error: {e}")
            raise

    # ------------------------------------------------------------------
    # Model listing
    # ------------------------------------------------------------------
    def list_models(self) -> list[dict]:
        """List all available Gemini models."""
        try:
            models = self.client.models.list()
            result = []
            for m in models:
                result.append({
                    "name": m.name,
                    "display_name": m.display_name,
                    "description": m.description,
                })
            return result
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    # ------------------------------------------------------------------
    # Compatibility shim (for skills that call execute())
    # ------------------------------------------------------------------
    async def execute(self, prompt: str, cwd: str, model: Optional[str] = None) -> tuple[str, dict]:
        """
        Backward-compatible method for existing skills.
        Maps old execute(prompt, cwd, model) to new generate().
        """
        return await self.generate(prompt, model=model)
