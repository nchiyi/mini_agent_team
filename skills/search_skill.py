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
                # Get top 5 results
                ddgs_gen = ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y')
                for i, r in enumerate(ddgs_gen):
                    if i >= 5:
                        break
                    results.append(f"🔹 **[{r['title']}]({r['href']})**\n{r['body']}\n")

            if not results:
                return f"🔍 搜尋「{query}」沒有找到相關結果。"

            response = f"🔍 **「{query}」的搜尋結果：**\n\n" + "\n".join(results)
            return response

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"❌ 搜尋出錯：{str(e)}"
