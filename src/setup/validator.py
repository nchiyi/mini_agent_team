import json
import urllib.error
import urllib.request


class ValidationResult:
    def __init__(
        self,
        valid: bool,
        skipped: bool = False,
        reason: str = "",
        bot_username: str | None = None,
        bot_id: int | None = None,
        error_category: str | None = None,
    ):
        self.valid = valid
        self.skipped = skipped
        self.reason = reason
        self.bot_username = bot_username
        self.bot_id = bot_id
        # error_category: "auth" | "network" | "rate_limit" | None
        self.error_category = error_category


def validate_telegram_token(token: str) -> ValidationResult:
    import re
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{35,}", token):
        return ValidationResult(
            valid=False,
            reason="invalid format (expected <id>:<key>)",
            error_category="auth",
        )
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            ok = bool(data.get("ok"))
            if ok:
                result_data = data.get("result", {})
                username = result_data.get("username")
                bot_id = result_data.get("id")
                return ValidationResult(
                    valid=True,
                    bot_username=username,
                    bot_id=bot_id,
                )
            return ValidationResult(valid=False, reason="API rejected token", error_category="auth")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ValidationResult(
                valid=False,
                reason=f"API rejected token ({e.code})",
                error_category="auth",
            )
        if e.code == 429:
            return ValidationResult(
                valid=False,
                reason=f"rate limited ({e.code})",
                error_category="rate_limit",
            )
        if e.code == 404:
            return ValidationResult(
                valid=False,
                reason=f"API rejected token ({e.code})",
                error_category="auth",
            )
        return ValidationResult(valid=True, skipped=True, reason=f"HTTP {e.code}, skipping validation")
    except (urllib.error.URLError, ValueError, OSError) as e:
        return ValidationResult(
            valid=True,
            skipped=True,
            reason=f"network error, skipping validation: {e}",
            error_category="network",
        )


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
            if ok:
                data = json.loads(resp.read())
                username = data.get("username")
                bot_id_raw = data.get("id")
                bot_id = int(bot_id_raw) if bot_id_raw is not None else None
                return ValidationResult(
                    valid=True,
                    bot_username=username,
                    bot_id=bot_id,
                )
            return ValidationResult(valid=False, reason="API rejected token", error_category="auth")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ValidationResult(
                valid=False,
                reason="API rejected token (401)",
                error_category="auth",
            )
        if e.code == 429:
            return ValidationResult(
                valid=False,
                reason=f"rate limited ({e.code})",
                error_category="rate_limit",
            )
        return ValidationResult(valid=True, skipped=True, reason=f"HTTP {e.code}, skipping validation")
    except (urllib.error.URLError, OSError) as e:
        return ValidationResult(
            valid=True,
            skipped=True,
            reason=f"network error, skipping validation: {e}",
            error_category="network",
        )
