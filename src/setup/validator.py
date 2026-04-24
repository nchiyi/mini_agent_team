import json
import urllib.error
import urllib.request


class ValidationResult:
    def __init__(self, valid: bool, skipped: bool = False, reason: str = ""):
        self.valid = valid
        self.skipped = skipped
        self.reason = reason


def validate_telegram_token(token: str) -> ValidationResult:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            ok = bool(data.get("ok"))
            return ValidationResult(valid=ok, reason="" if ok else "API rejected token")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ValidationResult(valid=False, reason="API rejected token (401)")
        return ValidationResult(valid=True, skipped=True, reason=f"HTTP {e.code}, skipping validation")
    except (urllib.error.URLError, ValueError, OSError) as e:
        return ValidationResult(valid=True, skipped=True, reason=f"network error, skipping validation: {e}")


def validate_discord_token(token: str) -> ValidationResult:
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (https://github.com/nchiyi/mini_agent_team, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            return ValidationResult(valid=ok, reason="" if ok else "API rejected token")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ValidationResult(valid=False, reason="API rejected token (401)")
        return ValidationResult(valid=True, skipped=True, reason=f"HTTP {e.code}, skipping validation")
    except (urllib.error.URLError, OSError) as e:
        return ValidationResult(valid=True, skipped=True, reason=f"network error, skipping validation: {e}")
