from typing import AsyncIterator

from src.gateway.session import clear_active_role, set_active_role
from src.roles import load_roles


def _usage() -> str:
    return (
        "💡 **用法：**\n"
        "`/agency list` - 列出所有角色\n"
        "`/agency info <slug>` - 查看角色詳情\n"
        "`/agency use <slug>` - 啟動角色\n"
        "`/agency clear` - 清除當前角色"
    )


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    roles = load_roles()
    parts = args.split() if args else []

    if not parts or parts[0] == "list":
        if not roles:
            yield "📭 **目前角色庫是空的。**"
            return
        lines = ["🏢 **代理人企業 - 角色清單：**"]
        for slug, meta in roles.items():
            lines.append(f"- **{meta.get('name', slug)}** (`{slug}`): {meta.get('summary', '')}")
        lines.append("")
        lines.append("使用 `/agency use <slug>` 來啟動特定角色。")
        yield "\n".join(lines)
        return

    sub_cmd = parts[0]

    if sub_cmd == "info" and len(parts) > 1:
        slug = parts[1]
        meta = roles.get(slug)
        if not meta:
            yield f"❌ **找不到角色：`{slug}`**"
            return
        rules = meta.get("rules") or []
        if not isinstance(rules, list):
            rules = [str(rules)]
        yield (
            f"🎭 **角色詳情：{meta.get('name', slug)}**\n"
            f"🆔 識別碼：`{slug}`\n"
            f"📝 簡介：{meta.get('summary', '')}\n"
            f"🧩 建議引擎：`{meta.get('preferred_runner', 'N/A')}`\n\n"
            f"📖 **背景與準則：**\n{meta.get('identity', '')}\n\n"
            f"⚖️ **核心規則：**\n" + "\n".join(f"- {rule}" for rule in rules)
        )
        return

    if sub_cmd == "use" and len(parts) > 1:
        slug = parts[1]
        if slug in {"none", "default"}:
            clear_active_role(user_id, channel)
            yield "🍃 **已清除當前角色，恢復預設模式。**"
            return
        meta = roles.get(slug)
        if not meta:
            yield f"❌ **找不到角色：`{slug}`**"
            return
        set_active_role(user_id, channel, slug)
        yield (
            f"✅ **角色已啟動：{meta.get('name', slug)}**\n"
            "現在我的行為將遵循該角色的 DNA 準則。"
        )
        return

    if sub_cmd == "clear":
        clear_active_role(user_id, channel)
        yield "🍃 **已清除當前角色，恢復預設模式。**"
        return

    yield _usage()
