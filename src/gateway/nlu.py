# src/gateway/nlu.py
import re
from .router import ParsedCommand

_RELAY_KEYWORDS = re.compile(r"接力|relay|chain|one after another", re.IGNORECASE)
_DISCUSS_KEYWORDS = re.compile(r"討論|discuss|對話|exchange|conversation between", re.IGNORECASE)
_DEBATE_KEYWORDS = re.compile(r"辯論|debate|argue|比較|compare|誰比較好|which is better", re.IGNORECASE)

_RUNNER_ALIASES: dict[str, list[str]] = {
    "claude": ["claude", "claude-code", "claude code"],
    "codex": ["codex", "openai"],
    "gemini": ["gemini", "google"],
    "kiro": ["kiro", "aws"],
}


def _find_runners(text: str, known_runners: set[str]) -> list[str]:
    text_lower = text.lower()
    found: list[str] = []
    for runner in known_runners:
        aliases = _RUNNER_ALIASES.get(runner, [runner])
        if any(alias in text_lower for alias in aliases):
            if runner not in found:
                found.append(runner)
    return found


def _strip_meta(text: str, known_runners: set[str]) -> str:
    """Remove runner names and mode keywords from text to get the actual prompt."""
    result = text
    for runner in known_runners:
        for alias in _RUNNER_ALIASES.get(runner, [runner]):
            result = re.sub(re.escape(alias), "", result, flags=re.IGNORECASE)
    result = _RELAY_KEYWORDS.sub("", result)
    result = _DISCUSS_KEYWORDS.sub("", result)
    result = _DEBATE_KEYWORDS.sub("", result)
    result = re.sub(r"[,，、]+", " ", result)
    result = re.sub(r"\s{2,}", " ", result).strip(" :：,，")
    return result


class FastPathDetector:
    def __init__(self, known_runners: set[str]) -> None:
        self._known = known_runners

    def detect(self, text: str) -> "ParsedCommand | None":
        if text.startswith("/"):
            return None

        runners = _find_runners(text, self._known)
        if not runners:
            return None

        prompt = _strip_meta(text, self._known)
        if not prompt:
            return None

        if _RELAY_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_pipeline=True, pipeline_runners=runners,
            )

        if _DISCUSS_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_discussion=True, discussion_runners=runners, discussion_rounds=3,
            )

        if _DEBATE_KEYWORDS.search(text) and len(runners) >= 2:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_debate=True, debate_runners=runners,
            )

        return None
