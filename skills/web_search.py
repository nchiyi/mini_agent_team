"""
Web Search Skill — Semantic Web Search with Intent Analysis.
"""
import json
import logging
import asyncio
from duckduckgo_search import DDGS
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "智能聯網搜尋。當使用者需要查詢資料、比較產品、尋找最新資訊或需要綜合分析網路結果時使用此工具。支援意圖分析與多重搜尋總結。"
    commands = ["/search", "/ask"]

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
                            "description": "使用者的原始查詢提問（例如：請幫我比較台積電與 Intel 的最新製程）"
                        }
                    },
                    "required": ["args"]
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return (
                "🔍 **智能聯網搜尋**\n\n"
                "用法: `/search <你的問題或任務>`\n"
                "範例: `/search 幫我整理今年最新的 AI 影片生成工具比較`\n"
                "說明: 系統會自動分析你的意圖，發動多次精確搜尋，並為你總結一份報告。"
            )

        original_query = " ".join(args)

        try:
            # Step 1: Query Formulation (Intent Analysis)
            search_queries = await self._formulate_queries(original_query)
            if not search_queries:
                search_queries = [original_query] # Fallback to original
            
            # Step 2: Multi-Search execution
            all_snippets = await self._execute_multi_search(search_queries)
            
            if not all_snippets:
                return f"🔍 抱歉，關於「{original_query}」我沒有在網路上找到相關資訊。"

            # Step 3: Semantic Synthesis
            final_answer = await self._synthesize_answer(original_query, search_queries, all_snippets)
            
            return f"🔍 **搜尋結果分析:**\n\n{final_answer}"

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return f"❌ 搜尋時發生錯誤: {e}"

    async def _formulate_queries(self, original_query: str) -> list[str]:
        """Use LLM to generate 2-3 optimal search queries based on user intent."""
        import datetime
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        messages = [
            {"role": "system", "content": f"You are a professional research assistant. Today is {current_date}. Analyze the user's request and formulate 2 to 3 optimal web search queries. If the user asks for current events, prices, or news, MAKE SURE to include the current year/month (e.g. '{current_date[:4]}') in the queries to fetch the latest data. Return ONLY a valid JSON array of strings representing the queries. Example: [\"TSMC stock price {current_date[:4]}\", \"Taiwan weighted index today\"]"},
            {"role": "user", "content": f"User Request: {original_query}"}
        ]
        
        try:
            response = await self.engine.llm.generate(messages=messages, temperature=0.2)
            content = response.choices[0].message.content.strip()
            # Clean up potential markdown formatting
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
                
            queries = json.loads(content.strip())
            if isinstance(queries, list) and len(queries) > 0:
                logger.debug(f"Formulated queries: {queries}")
                return [str(q) for q in queries][:3] # Limit to max 3 queries
            return [original_query]
        except Exception as e:
            logger.warning(f"Failed to formulate queries, fallback to original: {e}")
            return [original_query]

    async def _execute_multi_search(self, queries: list[str]) -> list[str]:
        """Execute multiple DuckDuckGo searches concurrently and aggregate unique snippets."""
        all_results = []
        seen_links = set()
        
        def fetch_search(q: str):
            results = []
            try:
                with DDGS() as ddgs:
                    # Fetch top 4 results per query, favor the past year to avoid ancient garbage like 2004
                    for r in ddgs.text(q, max_results=4, timelimit='y', region='wt-wt'):
                        results.append(r)
            except Exception as e:
                logger.warning(f"Search failed for query '{q}': {e}")
            return results

        # Run blocking network calls in a thread pool
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(None, fetch_search, q) for q in queries]
        
        search_responses = await asyncio.gather(*tasks)
        
        for response in search_responses:
            for r in response:
                link = r.get('href', '')
                if link and link not in seen_links:
                    seen_links.add(link)
                    title = r.get('title', '')
                    body = r.get('body', '')
                    all_results.append(f"Source: {title} ({link})\nContent: {body}")
                    
        return all_results

    async def _synthesize_answer(self, original_query: str, used_queries: list[str], snippets: list[str]) -> str:
        """Use LLM to synthesize a final answer based on the aggregated search snippets."""
        context = "\n\n---\n\n".join(snippets)
        queries_str = ", ".join(f"`{q}`" for q in used_queries)
        
        messages = [
            {"role": "system", "content": "你是一個專業的 AI 研究助理。請根據提供的多個網路搜尋結果，綜合分析並回答使用者的問題。請使用繁體中文（zh-TW）回答。如果資訊衝突，請客觀陳述。如果提供的搜尋結果無法完全回答問題，請根據結果盡力回答，並說明資訊不足的部分。請在重點處使用 Markdown 格式（如粗體、條列式）以利閱讀。可以附上參考資料來源。"},
            {"role": "user", "content": f"使用者的原始問題：{original_query}\n\n以下是幾組相關的網路搜尋結果片段：\n\n{context}"}
        ]
        
        response = await self.engine.llm.generate(messages=messages)
        answer = response.choices[0].message.content
        
        # Append a small footer indicating the search scope
        footer = f"\n\n*(🔍 綜合搜尋關鍵字: {queries_str})*"
        return answer + footer
