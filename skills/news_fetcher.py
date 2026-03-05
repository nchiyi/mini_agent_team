"""
News Fetcher Skill — Search and push news via web search.
"""
import asyncio
import json
from .base_skill import BaseSkill


class NewsFetcherSkill(BaseSkill):
    name = "news_fetcher"
    description = "新聞推播 — 搜尋最新科技新聞與定時推播服務"
    commands = ["/news", "/subscribe", "/unsubscribe"]
    schedule = "0 9 * * *"  # Every day at 9 AM

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if command == "/news":
            return await self._search_news(args, user_id)
        elif command == "/subscribe":
            return self._subscribe(args, user_id)
        elif command == "/unsubscribe":
            return self._unsubscribe(args, user_id)
        return "未知指令"

    async def _search_news(self, args: list[str], user_id: int) -> str:
        if not args:
            return (
                "📰 **新聞搜尋**\n\n"
                "用法: `/news <關鍵字>`\n"
                "範例: `/news AI video generation`\n\n"
                "📬 **訂閱推播:**\n"
                "`/subscribe <關鍵字>` — 每天 9:00 自動推播\n"
                "`/unsubscribe <關鍵字>` — 取消訂閱"
            )

        query = " ".join(args)

        # Use Gemini CLI to search for news
        prompt = (
            f"Search for the latest news about '{query}'. "
            f"Return the top 5 most relevant and recent news items. "
            f"For each item, include: title, source, date, and a brief summary. "
            f"Format as a numbered list in Traditional Chinese."
        )

        cwd = "/tmp"
        result = await self.engine.gemini.execute(prompt, cwd)
        return f"📰 **「{query}」最新新聞:**\n\n{result}"

    def _subscribe(self, args: list[str], user_id: int) -> str:
        if not args:
            return "用法: `/subscribe <關鍵字>`"

        topic = " ".join(args)
        subs = self._get_subscriptions(user_id)
        if topic not in subs:
            subs.append(topic)
            self._save_subscriptions(user_id, subs)

        return f"✅ 已訂閱: **{topic}**\n每天 9:00 自動推播相關新聞。"

    def _unsubscribe(self, args: list[str], user_id: int) -> str:
        if not args:
            subs = self._get_subscriptions(user_id)
            if not subs:
                return "📭 目前沒有任何訂閱。"
            items = "\n".join(f"• {s}" for s in subs)
            return f"📬 **目前訂閱:**\n{items}\n\n取消: `/unsubscribe <關鍵字>`"

        topic = " ".join(args)
        subs = self._get_subscriptions(user_id)
        if topic in subs:
            subs.remove(topic)
            self._save_subscriptions(user_id, subs)
            return f"✅ 已取消訂閱: {topic}"
        return f"❌ 未訂閱: {topic}"

    async def scheduled_task(self):
        """Daily news push for all subscribed users."""
        # This gets called by the scheduler
        # We need the scheduler's notify callback to send messages
        if not self.engine or not self.engine.scheduler:
            return

        # Get all users with subscriptions
        # For simplicity, check all settings for news_subs
        import sqlite3
        try:
            with sqlite3.connect(self.engine.memory.db_path) as conn:
                rows = conn.execute(
                    "SELECT user_id, value FROM settings WHERE key = 'news_subscriptions'"
                ).fetchall()

            for user_id, subs_json in rows:
                subs = json.loads(subs_json)
                for topic in subs:
                    result = await self._search_news([topic], user_id)
                    await self.engine.scheduler.notify(user_id, f"📬 **每日新聞推播**\n\n{result}")
        except Exception:
            pass

    def _get_subscriptions(self, user_id: int) -> list[str]:
        raw = self.engine.memory.get_setting(user_id, "news_subscriptions", "[]")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []

    def _save_subscriptions(self, user_id: int, subs: list[str]):
        self.engine.memory.set_setting(user_id, "news_subscriptions", json.dumps(subs))
