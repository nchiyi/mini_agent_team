"""
Browser Skill — Allows the agent to browse the web and read content.
"""
import asyncio
import logging
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright
    import html2text
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserSkill(BaseSkill):
    """A skill that provides web browsing capabilities."""

    name = "browser_eye"
    description = "直接網頁瀏覽功能。僅當使用者提供明確的 URL 網址時使用。如果你需要搜尋資訊、新聞或研究主題，請優先使用 search、news 或 researcher 工具。"
    commands = ["/browse", "/analyze"]
    schedule = None

    def get_tool_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "browse",
                "description": "瀏覽或分析特定網址的內容。僅適用於明確的 URL。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "目標網頁的完整網址 (例如：https://github.com/nchiyi/bot)"
                        }
                    },
                    "required": ["args"]
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            return (
                "❌ 瀏覽器功能未啟動（缺少相依套件）。\n"
                "請在伺服器端執行 `pip install playwright html2text` 且 `playwright install chromium`。"
            )

        if not args:
            return "💡 使用方式: `/browse <URL>` 或 `/analyze <URL>`"

        target = " ".join(args).strip()
        
        # Basic URL validation: if it contains spaces and doesn't look like a domain, it's probably a search
        # Simple check: if there are spaces and no dot, or many words without http, it's a query
        if " " in target and not target.startswith("http"):
             return f"⚠️ 偵測到疑似搜尋字串：「{target}」。\n瀏覽功能僅支援直接輸入網址。建議您改用 `/search {target}` 或 `/research {target}`。"

        url = target if target.startswith("http") else f"https://{target}"

        if command == "/analyze":
            return await self._analyze_page(url, user_id)
        
        return await self._fetch_page(url)

    async def _analyze_page(self, url: str, user_id: int) -> str:
        """Fetch a page and use LLM to analyze/summarize it."""
        raw_markdown = await self._fetch_page(url)
        
        if raw_markdown.startswith("❌"):
            return raw_markdown

        # Extract only the body if it's formatted as '🌐 **[title](url)**\n\ncontent'
        content_to_analyze = raw_markdown
        if "\n\n" in raw_markdown:
            content_to_analyze = raw_markdown.split("\n\n", 1)[1]

        prompt = (
            "你是一個資深的網頁情報分析專家。以下是從網頁中提取的原始內容：\n\n"
            f"【網址】：{url}\n\n"
            f"【原始內容】：\n{content_to_analyze[:12000]}\n\n"
            "--- \n"
            "請針對以上內容進行「深度分析」。你的目標是讓讀者在不點開原文的情況下，掌握該網頁的所有精華。\n\n"
            "要求格式如下：\n"
            "1. **🔍 核心意圖**：一句話總結該網頁存在的目的。\n"
            "2. **💡 關鍵洞察**：列出 5 個最重要的資訊點或技術細節，每個點請帶有簡短說明。\n"
            "3. **🛠️ 實用價值**（若適用）：如果是工具或專案，列出安裝、使用方式或具體解決了什麼問題。\n"
            "4. **🚩 專家點評**：從專業角度給予這份內容的評價或後續建議。\n"
            "5. **📝 總結**：一段話的結論。\n\n"
            "注意：請使用「繁體中文」，語氣精鍊專業，避免廢話。"
        )

        messages = [{"role": "user", "content": prompt}]
        
        # Get preferred model or default
        import config
        model = self.engine.memory.get_setting(user_id, "preferred_model", "") or config.DEFAULT_MODEL

        try:
            response = await self.engine.llm.generate(messages=messages, model=model)
            analysis = response.choices[0].message.content or "無法生成分析。"
            return f"🔬 **網頁深度情報分析**\n\n{analysis}\n\n🔗 [原文連結]({url})"
        except Exception as e:
            logger.error(f"Page analysis failed: {e}")
            return f"❌ 分析失敗：{e}\n\n以下是原始抓取的內容：\n\n{raw_markdown}"

    async def _fetch_page(self, url: str) -> str:
        """Fetch a page and convert to markdown."""
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # Use a common user agent to avoid being blocked
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                
                logger.info(f"Browsing URL: {url}")
                # Use 'domcontentloaded' instead of 'networkidle' for better reliability on heavy sites
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Wait a bit for potential JS content if needed, but don't wait for network idle
                await asyncio.sleep(2)
                
                # Get page title and content
                title = await page.title()
                content = await page.content()
                
                await browser.close()
                browser = None

                # Convert HTML to Markdown for better LLM readability
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = True
                markdown = h.handle(content)

                # Truncate to avoid blowing up context (increased to 12k chars)
                if len(markdown) > 12000:
                    markdown = markdown[:12000] + "\n\n...(內容過長已截斷)"

                return f"🌐 **[{title}]({url})**\n\n{markdown}"

        except asyncio.TimeoutError:
            return f"❌ 讀取網頁超時 (30s): {url}\n建議重試或檢查網址是否需要登入。"
        except Exception as e:
            logger.error(f"Browser error: {e}")
            return f"❌ 讀取網頁失敗: {e}"
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
