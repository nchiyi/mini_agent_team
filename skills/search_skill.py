import logging
from duckduckgo_search import DDGS
from skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

class SearchSkill(BaseSkill):
    """Skill to perform web searches using DuckDuckGo."""

    name = "search"
    description = "網路搜尋功能。當使用者詢問即時資訊、天氣、新聞或需要進行一般性網頁檢索時使用此工具。它會回傳前 5 個相關結果的摘要。"
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
                            "description": "搜尋關鍵字（例如：台北天氣、最新 AI 新聞）"
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
            results = []
            with DDGS() as ddgs:
                # 1. Get top 3 standard web results
                # Using list comprehension to avoid generator issues when taking a small slice
                web_gen = ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y', max_results=3)
                web_results = list(web_gen) if web_gen else []
                
                if web_results:
                    results.append("🌐 **網頁搜尋結果：**")
                    for r in web_results:
                        results.append(f"🔹 **[{r.get('title', '無標題')}]({r.get('href', '')})**\n{r.get('body', '')}\n")

                # 2. Get top 3 news results
                news_gen = ddgs.news(query, region='wt-wt', safesearch='moderate', timelimit='y', max_results=3)
                news_results = list(news_gen) if news_gen else []
                
                if news_results:
                    results.append("📰 **即時新聞結果：**")
                    for r in news_results:
                        # body could be 'body' or sometimes 'abstract' depending on ddgs version, standardizing fallback mapping
                        body_text = r.get('body') or r.get('abstract', '') 
                        results.append(f"🔸 **[{r.get('title', '無標題')}]({r.get('url', '')})**\n{body_text}\n")

            if not results:
                return f"🔍 搜尋「{query}」沒有找到相關結果。"

            response = f"🔍 **「{query}」的綜合搜尋結果：**\n\n" + "\n".join(results)
            return response

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"❌ 搜尋出錯：{str(e)}"
