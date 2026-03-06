import logging
import asyncio
import json
from .base_skill import BaseSkill
from duckduckgo_search import DDGS
import config

logger = logging.getLogger(__name__)

class ResearchSkill(BaseSkill):
    """
    Research Skill — Integrates search, selection, and multi-page synthesis
    to provide a comprehensive report on any topic.
    """

    name = "researcher"
    description = "深度研究 — 整合搜尋與多網頁分析，生成綜合研究報告。當使用者需要深入暸解某個主題、撰寫報告或需要多方對比資訊時使用此工具。"
    commands = ["/research"]

    def get_tool_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "researcher",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "研究主題（例如：2024 AI 趨勢分析、半導體產業報告）"
                        }
                    },
                    "required": ["args"]
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return "❌ 請提供研究主題。例如：`/research 2024 AI 發展趨勢`"

        query = " ".join(args)
        logger.info(f"User {user_id} starting research on: {query}")

        # 1. Search for candidates
        search_results = await self._search_candidates(query)
        if not search_results:
            return f"🔍 搜尋「{query}」沒有找到相關結果。"

        # 2. Let LLM pick the best URLs (Top 3)
        selection_prompt = (
            f"以下是關於「{query}」的搜尋結果。請以 JSON 陣列格式回傳前 3 個最值得深入閱讀進行研究的 URL。\n\n"
            f"搜尋結果：\n" + "\n".join([f"- {r['title']}: {r['href']}" for r in search_results]) + "\n\n"
            "格式要求：[\"url1\", \"url2\", \"url3\"]"
        )
        
        selected_urls = []
        try:
            model = self.engine.memory.get_setting(user_id, "preferred_model", "") or config.DEFAULT_MODEL
            response = await self.engine.llm.generate(messages=[{"role": "user", "content": selection_prompt}], model=model)
            content = response.choices[0].message.content or "[]"
            # Extract JSON from potential markdown blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            selected_urls = json.loads(content)
        except Exception as e:
            logger.error(f"URL selection failed: {e}")
            selected_urls = [r['href'] for r in search_results[:3]]

        if not selected_urls:
            return "❌ 無法從搜尋結果中選取有效的參考資料。"

        # 3. Fetch contents of selected URLs in parallel
        browser_skill = self.engine.skills.get("browser_eye")
        if not browser_skill:
            return "❌ 系統缺少 `BrowserSkill`，無法進行深度研究。"

        tasks = [browser_skill._fetch_page(url) for url in selected_urls]
        contents = await asyncio.gather(*tasks)

        # 4. Synthesize final report
        valid_contents = []
        for i, c in enumerate(contents):
            if not c.startswith("❌"):
                valid_contents.append(f"【來源 {i+1}】\n{c}")

        if not valid_contents:
            return "❌ 抓取參考資料失敗，無法生成研究報告。"

        synthesis_prompt = (
            f"你是一個頂尖的市場研究員與資料分析師。目前的任務是針對「{query}」撰寫一份綜合研究報告。\n\n"
            "我為你準備了多個來源的抓取內容：\n\n"
            + "\n\n".join(valid_contents) + "\n\n"
            "--- \n"
            "請根據以上資訊撰寫報告，要求：\n"
            "1. **使用繁體中文**。\n"
            "2. **架構清晰**：包含簡介、核心要點分析、多方觀點對比、以及結論。\n"
            "3. **事實庫**：僅使用提供的資訊，若有衝突請標註不同來源的說法。\n"
            "4. **深度與廣度**：不僅是摘要，要有深入的洞察與趨勢判斷。\n"
            "5. 回報長度請控制在 1500 字以內，並適度使用 Markdown 格式（標題、清單、粗體）。"
        )

        try:
            final_resp = await self.engine.llm.generate(messages=[{"role": "user", "content": synthesis_prompt}], model=model)
            report = final_resp.choices[0].message.content or "無法生成報告。"
            
            footer = "\n\n📚 **參考來源：**\n" + "\n".join([f"• {url}" for url in selected_urls])
            return f"📑 **關於「{query}」的研究報告**\n\n{report}{footer}"
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return f"❌ 彙整報告失敗：{e}"

    async def _search_candidates(self, query: str):
        """Perform a quick search to get candidates."""
        try:
            results = []
            with DDGS() as ddgs:
                ddgs_gen = ddgs.text(query, region='wt-wt', safesearch='moderate', max_results=8)
                for r in ddgs_gen:
                    results.append(r)
            return results
        except Exception as e:
            logger.error(f"Research search failed: {e}")
            return []
