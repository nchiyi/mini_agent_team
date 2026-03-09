import logging
import trafilatura
from skills.base_skill import BaseSkill
import config

logger = logging.getLogger(__name__)

class WebSummarizerSkill(BaseSkill):
    """Skill to extract and summarize web content."""

    name = "summarizer"
    description = "抓取網頁內容並進行 AI 摘要"
    commands = ["/sum"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return "❌ 請提供網址。例如：`/sum https://example.com`"

        url = args[0]
        logger.info(f"User {user_id} summarizing URL: {url}")

        try:
            # 1. Download and extract text
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return "❌ 無法讀取該網址，請確認網址是否正確或該網站是否阻擋爬蟲。"

            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if not text or len(text) < 50:
                return "❌ 無法從該網址提取足夠的文字內容。"

            # 2. Summarize using LLM
            # We use the engine's LLM directly
            prompt = (
                "你是一個專業的內容摘要專家。以下是從網頁中提取的原始文字內容：\n\n"
                f"【網址】：{url}\n\n"
                f"【內容大綱】：\n{text[:4000]}\n\n" # Limit to avoid token overflow
                "--- \n"
                "請針對以上內容進行精簡的摘要。要求：\n"
                "1. 使用繁體中文。\n"
                "2. 列出 3-5 個核心重點。\n"
                "3. 提供一個簡短的總結性結論。\n"
                "4. 保持語氣中立專業。"
            )

            messages = [{"role": "user", "content": prompt}]
            
            # Using the default model from config or user preference if possible
            model = config.DEFAULT_MODEL
            if self.engine and self.engine.memory:
                 preferred = self.engine.memory.get_setting(user_id, "preferred_model")
                 if preferred:
                      model = preferred

            response = await self.engine.llm.generate(messages=messages, model=model)
            summary = response.choices[0].message.content or "無法生成摘要。"

            return f"📝 **網頁摘要：**\n\n{summary}\n\n🔗 [原文連結]({url})"

        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return f"❌ 摘要出錯：{str(e)}"
