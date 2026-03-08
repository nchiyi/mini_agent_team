import logging
import os
from duckduckgo_search import DDGS
from skills.base_skill import BaseSkill

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

logger = logging.getLogger(__name__)

class SearchSkill(BaseSkill):
    """Skill to perform web searches using DuckDuckGo."""

    name = "search"
    description = "網路搜尋功能。當使用者詢問即時資訊、天氣、新聞或需要進行一般性網頁檢索時使用此工具。它會回傳前幾筆相關結果的摘要。⚠️重要：請務必在回應使用者時，附上這些搜尋結果的『來源連結』，讓使用者可以點擊查看。"
    commands = ["/search"]

    def get_tool_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "search",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "搜尋關鍵字（例如：台北天氣、最新 AI 新聞）。回傳的結果會包含網址連結，請務必將連結提供給使用者。"
                        }
                    },
                    "required": ["args"]
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return "❌ 請提供搜尋關鍵字。例如：`/search 台北天氣`"

        query = " ".join(args)
        logger.info(f"User {user_id} searching for: {query}")

        try:
            tavily_key = os.getenv("TAVILY_API_KEY")
            results = []

            if tavily_key and TavilyClient:
                logger.debug("Using Tavily Search API")
                client = TavilyClient(api_key=tavily_key)
                response = client.search(query, search_depth="advanced", max_results=5)
                
                tavily_results = response.get("results", [])
                if tavily_results:
                    results.append("🚀 **Tavily 進階搜尋結果：**")
                    for r in tavily_results:
                        results.append(f"🔹 **標題：** {r.get('title', '無標題')}\n**摘要：** {r.get('content', '')}\n**連結：** {r.get('url', '')}\n")
            else:
                with DDGS() as ddgs:
                    # 1. Get top 3 standard web results
                    # Using list comprehension to avoid generator issues when taking a small slice
                    web_gen = ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y', max_results=3)
                    web_results = list(web_gen) if web_gen else []
                    
                    if web_results:
                        results.append("🌐 **網頁搜尋結果：**")
                        for r in web_results:
                            results.append(f"🔹 **標題：** {r.get('title', '無標題')}\n**摘要：** {r.get('body', '')}\n**連結：** {r.get('href', '')}\n")
    
                    # 2. Get top 3 news results
                    news_gen = ddgs.news(query, region='wt-wt', safesearch='moderate', timelimit='y', max_results=3)
                    news_results = list(news_gen) if news_gen else []
                    
                    if news_results:
                        results.append("📰 **即時新聞結果：**")
                        for r in news_results:
                            # body could be 'body' or sometimes 'abstract' depending on ddgs version, standardizing fallback mapping
                            body_text = r.get('body') or r.get('abstract', '') 
                            results.append(f"🔸 **標題：** {r.get('title', '無標題')}\n**摘要：** {body_text}\n**連結：** {r.get('url', '')}\n")

            if not results:
                return f"🔍 搜尋「{query}」沒有找到相關結果。"

            response = f"🔍 **「{query}」的綜合搜尋結果：**\n\n" + "\n".join(results)
            return response

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"❌ 搜尋出錯：{str(e)}"
