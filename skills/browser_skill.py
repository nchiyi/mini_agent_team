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
    description = "瀏覽網頁與讀取內容 (需安裝 Playwright)"
    commands = ["/browse"]
    schedule = None

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            return (
                "❌ 瀏覽器功能未啟動（缺少相依套件）。\n"
                "請在伺服器端執行 `pip install playwright html2text` 且 `playwright install chromium`。"
            )

        if not args:
            return "💡 使用方式: `/browse <URL>`"

        target = " ".join(args)
        url = target if target.startswith("http") else f"https://{target}"

        return await self._fetch_page(url)

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

                # Truncate to avoid blowing up context (limit to 8k chars approx)
                if len(markdown) > 8000:
                    markdown = markdown[:8000] + "\n\n...(內容過長已截斷)"

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
