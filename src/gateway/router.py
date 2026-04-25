# src/gateway/router.py
from dataclasses import dataclass, field
from .role_router import RoleRouter

@dataclass
class ParsedCommand:
    runner: str
    prompt: str
    role: str = "" # Added for Agency Integration
    is_switch_runner: bool = False
    is_cancel: bool = False
    is_status: bool = False
    is_reset: bool = False
    is_new: bool = False
    is_voice_on: bool = False
    is_voice_off: bool = False
    is_usage: bool = False
    is_remember: bool = False
    is_forget: bool = False
    is_recall: bool = False
    is_module: bool = False
    module_command: str = ""
    is_pipeline: bool = False
    pipeline_runners: list[str] = field(default_factory=list)
    is_discussion: bool = False
    discussion_runners: list[str] = field(default_factory=list)
    discussion_rounds: int = 3
    is_debate: bool = False
    debate_runners: list[str] = field(default_factory=list)


class Router:

    def __init__(self, known_runners: set[str], default_runner: str,
                 module_registry=None):
        self._runners = known_runners
        self._default = default_runner
        self._modules = module_registry
        self._role_router = RoleRouter()

    async def parse(self, text: str) -> ParsedCommand:
        text = text.strip()

        if text == "/cancel":
            return ParsedCommand(runner=self._default, prompt="", is_cancel=True)
        if text == "/status":
            return ParsedCommand(runner=self._default, prompt="", is_status=True)
        if text == "/reset":
            return ParsedCommand(runner=self._default, prompt="", is_reset=True)
        if text == "/new":
            return ParsedCommand(runner=self._default, prompt="", is_new=True)
        if text == "/voice on":
            return ParsedCommand(runner=self._default, prompt="", is_voice_on=True)
        if text == "/voice off":
            return ParsedCommand(runner=self._default, prompt="", is_voice_off=True)
        if text == "/usage":
            return ParsedCommand(runner=self._default, prompt="", is_usage=True)

        if text.startswith("/remember "):
            content = text[10:].strip()
            if content:
                return ParsedCommand(runner=self._default, prompt=content, is_remember=True)

        if text.startswith("/forget "):
            keyword = text[8:].strip()
            if keyword:
                return ParsedCommand(runner=self._default, prompt=keyword, is_forget=True)

        if text.startswith("/recall "):
            query = text[8:].strip()
            if query:
                return ParsedCommand(runner=self._default, prompt=query, is_recall=True)

        if text.startswith("/discuss "):
            rest = text[9:].strip()
            parts2 = rest.split(None, 1)
            if len(parts2) >= 1:
                runner_part = parts2[0]
                rounds = 3
                if ",rounds=" in runner_part:
                    runner_part, rounds_str = runner_part.rsplit(",rounds=", 1)
                    rounds = min(max(int(rounds_str), 2), 6)
                runners = [r.strip() for r in runner_part.split(",") if r.strip() in self._runners]
                prompt = parts2[1].strip() if len(parts2) > 1 else ""
                if len(runners) >= 2 and prompt:
                    return ParsedCommand(
                        runner=runners[0], prompt=prompt,
                        is_discussion=True,
                        discussion_runners=runners,
                        discussion_rounds=rounds,
                    )

        if text.startswith("/debate "):
            rest = text[8:].strip()
            parts2 = rest.split(None, 1)
            if len(parts2) >= 1:
                runners_list = [r.strip() for r in parts2[0].split(",")
                                if r.strip() in self._runners]
                prompt = parts2[1].strip() if len(parts2) > 1 else ""
                if len(runners_list) >= 2 and prompt:
                    return ParsedCommand(
                        runner=runners_list[0], prompt=prompt,
                        is_debate=True, debate_runners=runners_list,
                    )

        if text.startswith("/relay "):
            rest = text[7:].strip()
            parts2 = rest.split(None, 1)
            if len(parts2) >= 1:
                runners = [r.strip() for r in parts2[0].split(",") if r.strip() in self._runners]
                prompt = parts2[1].strip() if len(parts2) > 1 else ""
                if len(runners) >= 2 and prompt:
                    return ParsedCommand(
                        runner=runners[0], prompt=prompt,
                        is_pipeline=True, pipeline_runners=runners,
                    )

        if text.startswith("/use "):
            target = text[5:].strip()
            if target in self._runners:
                return ParsedCommand(runner=target, prompt="", is_switch_runner=True)

        if text.startswith("/"):
            parts = text.split(None, 1)
            prefix = parts[0].lstrip("/").lower()
            if prefix in self._runners:
                prompt = parts[1] if len(parts) > 1 else ""
                return ParsedCommand(runner=prefix, prompt=prompt)

            # Check module registry before falling through to default runner
            slash_prefix = parts[0].lower()  # keep the leading slash
            if self._modules and self._modules.has_command(slash_prefix):
                args = parts[1] if len(parts) > 1 else ""
                return ParsedCommand(
                    runner=self._default, prompt=args,
                    is_module=True, module_command=slash_prefix,
                )

            # Unknown slash command: pass full text to default runner
            return ParsedCommand(runner=self._default, prompt=text)

        # Agency Integration: Try semantic routing for natural language
        matched_role = await self._role_router.route(text)
        
        return ParsedCommand(
            runner=self._default, 
            prompt=text, 
            role=matched_role if matched_role else ""
        )
