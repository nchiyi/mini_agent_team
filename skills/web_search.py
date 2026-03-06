"""
Web Search Skill — Semantic Web Search with Deep Reading.
"""
import json
import logging
import asyncio
import datetime
from duckduckgo_search import DDGS
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "智能聯網搜尋與深度閱讀。當使用者需要查詢即時資訊（如股價、天氣）、比較產品或閱讀最新新聞時使用。會主動點擊網頁獲取核心內文進行分析。"
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
                            "description": "使用者的原始查詢提問（例如：請幫我查今天台股大盤收盤指數）"
                        }
                    },
                    "required": ["args"]
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return (
                "🔍 **智能聯網搜尋 & 深度閱讀**\n\n"
                "用法: `/search <你的問題或任務>`\n"
                "範例: `/search 今天台灣股市大盤收盤價`\n"
                "說明: 系統會自動搜尋、嘗試抓取並閱讀最相關的原始網頁內文，再為你總結報告。"
            )

        original_query = " ".join(args)

        try:
            # Step 1: Query Formulation (Intent Analysis)
            search_queries = await self._formulate_queries(original_query)
            if not search_queries:
                search_queries = [original_query]
            
            # Step 2: Search & Deep Fetch
            all_snippets, deep_contents, used_links = await self._execute_search_and_fetch(search_queries)
            
            if not all_snippets and not deep_contents:
                return f"🔍 抱歉，關於「{original_query}」我沒有在網路上找到相關資訊。"

            # Step 3: Semantic Synthesis
            final_answer = await self._synthesize_answer(original_query, search_queries, all_snippets, deep_contents, used_links)
            
            return f"{final_answer}"

        except Exception as e:
            logger.error(f"Semantic search with deep fetch failed: {e}", exc_info=True)
            return f"❌ 搜尋時發生錯誤: {e}"

    async def _formulate_queries(self, original_query: str) -> list[str]:
        """Use LLM to generate 2 optimal search queries based on user intent."""
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        messages = [
            {"role": "system", "content": f"You are a professional research assistant. Today is {current_date}. Analyze the user's request and formulate 1 to 2 optimal web search queries. For live data (stocks, weather, news), include words like '今天', '{current_date}', or specific indicators to force fresh results. Return ONLY a valid JSON array of strings representing the queries. Example: [\"台灣加權指數 收盤 今天\", \"yahoo finance twii\"]"},
            {"role": "user", "content": f"User Request: {original_query}"}
        ]
        
        try:
            response = await self.engine.llm.generate(messages=messages, temperature=0.1)
            content = response.choices[0].message.content.strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
                
            queries = json.loads(content.strip())
            if isinstance(queries, list) and len(queries) > 0:
                return [str(q) for q in queries][:2]
            return [original_query]
        except Exception as e:
            logger.warning(f"Failed to formulate queries, fallback to original: {e}")
            return [original_query]

    async def _execute_search_and_fetch(self, queries: list[str]):
        """Execute DDGS searches, collect URLs, and selectively deep-fetch top 2 URLs."""
        all_snippets = []
        collected_urls = []
        seen_links = set()
        
        def fetch_ddgs(q: str):
            results = []
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(q, max_results=3, timelimit='d', region='wt-wt'):
                        results.append(r)
            except Exception as e:
                logger.warning(f"DDGS failed for query '{q}': {e}")
            return results

        # Run DDGS blocking calls in thread pool
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(None, fetch_ddgs, q) for q in queries]
        search_responses = await asyncio.gather(*tasks)
        
        for response in search_responses:
            for r in response:
                link = r.get('href', '')
                if link and link not in seen_links:
                    seen_links.add(link)
                    collected_urls.append(link)
                    title = r.get('title', '')
                    body = r.get('body', '')
                    all_snippets.append(f"Title: {title}\nURL: {link}\nSnippet: {body}")
        
        # Determine Top URLs to deep fetch (first 2 unique URLs)
        urls_to_fetch = collected_urls[:2]
        deep_contents = []
        successful_links = []
        
        if urls_to_fetch:
            try:
                import trafilatura
            except ImportError:
                logger.error("trafilatura not installed, skipping deep fetch.")
                trafilatura = None
                
            if trafilatura:
                def deep_fetch(url: str):
                    try:
                        downloaded = trafilatura.fetch_url(url)
                        if downloaded:
                            text = trafilatura.extract(downloaded, include_links=False, include_images=False)
                            if text:
                                # cap length to save tokens
                                return text[:3000]
                    except Exception as e:
                        logger.warning(f"Deep fetch failed for {url}: {e}")
                    return None
                
                fetch_tasks = [loop.run_in_executor(None, deep_fetch, u) for u in urls_to_fetch]
                fetch_results = await asyncio.gather(*fetch_tasks)
                
                for idx, text in enumerate(fetch_results):
                    if text:
                        deep_contents.append(f"--- Full Content from {urls_to_fetch[idx]} ---\n{text}")
                        successful_links.append(urls_to_fetch[idx])

        return all_snippets, deep_contents, successful_links

    async def _synthesize_answer(self, original_query: str, used_queries: list[str], snippets: list[str], deep_contents: list[str], used_links: list[str]) -> str:
        """Use LLM to synthesize final answer from snippets and deep full texts."""
        context_parts = []
        
        if deep_contents:
            context_parts.append("【深入閱讀全文網頁內容】:\n" + "\n\n".join(deep_contents))
            
        if snippets:
            context_parts.append("【其他搜尋引擎摘要】:\n" + "\n".join(snippets))
            
        context_str = "\n\n".join(context_parts)
        
        messages = [
            {"role": "system", "content": "你是一個資深的財經與研究助理。請仔細閱讀下方抓取到的「深入網頁全文」與「搜尋摘要」，來回答使用者的問題。我們已經親自進入重點網頁抓取了最新內文，所以請優先信任「全文網頁內容」中的具體數字（如收盤價、漲跌幅）。回答請使用繁體中文。請像專業幕僚般條理分明、直搗重點（例如列出點數、漲跌幅、觀察）。必須在回答底部使用 markdown 列表列出你參考的資料來源（來源必須包含網址）。"},
            {"role": "user", "content": f"使用者的疑問：{original_query}\n\n抓取到的參考資料：\n{context_str}"}
        ]
        
        response = await self.engine.llm.generate(messages=messages, temperature=0.2)
        answer = response.choices[0].message.content
        
        return answer
