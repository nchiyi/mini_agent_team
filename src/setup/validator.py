import json
import urllib.error
import urllib.request


def validate_telegram_token(token: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return bool(data.get("ok"))
    except (urllib.error.URLError, ValueError):
        return False


def validate_discord_token(token: str) -> bool:
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bot {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError):
        return False
