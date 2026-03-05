"""
Usage Stats Skill — View precise token usage history from the database.
"""
import sqlite3
from .base_skill import BaseSkill

class UsageStatsSkill(BaseSkill):
    name = "usage_stats"
    description = "使用統計 — 檢視精確的 Token 消耗紀錄與成本統計"
    commands = ["/stats"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        with sqlite3.connect(self.engine.memory.db_path) as conn:
            # Get total stats
            total_row = conn.execute("""
                SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens), COUNT(*)
                FROM usage_logs WHERE user_id = ?
            """, (user_id,)).fetchone()
            
            # Get recent log items
            recent_rows = conn.execute("""
                SELECT model, total_tokens, estimated_cost, timestamp 
                FROM usage_logs WHERE user_id = ? 
                ORDER BY timestamp DESC LIMIT 5
            """, (user_id,)).fetchall()

        if not total_row or total_row[3] == 0:
            return "📭 目前尚無使用紀錄數據。"

        prompt, completion, total, count = total_row
        
        lines = [
            f"📊 **個人使用量統計 (總計)**",
            f"• 總對話次數: `{count}`",
            f"• 總 Token 消耗: `{total}`",
            f"  (Input: `{prompt}` / Output: `{completion}`)",
            "",
            f"📝 **最近 5 筆紀錄:**"
        ]
        
        for model, tokens, cost, ts in recent_rows:
            # Format timestamp briefly
            time_part = ts.split("T")[1][:5]
            lines.append(f"• [{time_part}] `{model}`: `{tokens}` tokens")

        lines.append("\n💡 數據為精確記錄，成本估算與計費方式請參考 `/usage`。")
        return "\n".join(lines)
