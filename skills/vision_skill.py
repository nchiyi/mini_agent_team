import logging
import os
import base64
from skills.base_skill import BaseSkill
import config

logger = logging.getLogger(__name__)

class VisionSkill(BaseSkill):
    """Skill to analyze images using multi-modal LLMs."""

    name = "vision"
    description = "影像分析與 OCR 文字辨識。當使用者傳送照片、圖片、截圖並詢問內容、或需要文字辨識（OCR）提取圖中文字時使用。"
    commands = ["/describe", "/ocr"]

    def get_tool_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "describe",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "分析指令或補充問題（例如：這張圖片裡有什麼、提取圖中文字）"
                        }
                    },
                    "required": []
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        # Check if there is a pending image in memory or if args contain a path (internal use)
        image_path = None
        if args and os.path.isfile(args[0]):
            image_path = args[0]
            prompt_text = " ".join(args[1:]) if len(args) > 1 else "請詳細描述這張圖片。"
        else:
            # Fallback for direct command without image
            return "💡 **使用方法：**\n請先傳送一張照片給我，然後對該照片回覆 `/describe` 或直接詢問問題。"

        if not os.path.exists(image_path):
             return f"❌ 找不到圖片檔案: {image_path}"

        try:
            # Prepare image data
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Determine prompt based on command
            if command == "/ocr":
                prompt_text = "請提取圖片中的所有文字，並以結構化的方式呈現。如果沒有文字，請告知。"
            elif not prompt_text:
                prompt_text = "請詳細描述這張圖片的內容。"

            # Multimodal payload for Ollama/OpenAI API
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                        }
                    ]
                }
            ]

            # Use a vision-capable model if specified, else default
            model = config.DEFAULT_MODEL # User should ensure this is a vision model like llava
            if self.engine and self.engine.memory:
                 preferred = self.engine.memory.get_setting(user_id, "vision_model")
                 if preferred:
                      model = preferred
            
            logger.info(f"Analyzing image {image_path} with model {model}")
            response = await self.engine.llm.generate(messages=messages, model=model)
            result = response.choices[0].message.content or "分析失敗。"

            return f"👁️ **影像分析結果：**\n\n{result}"

        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return f"❌ 影像分析出錯：{str(e)}"
