# src/gateway/router.py
from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    runner: str
    prompt: str
    is_switch_runner: bool = False
    is_cancel: bool = False
    is_status: bool = False
    is_reset: bool = False
    is_new: bool = False
    is_remember: bool = False
    is_forget: bool = False
    is_recall: bool = False
    is_module: bool = False
    module_command: str = ""
    is_pipeline: bool = False
    pipeline_runners: list[str] = field(default_factory=list)


class Router:

    def __init__(self, known_runners: set[str], default_runner: str,
                 module_registry=None):
        self._runners = known_runners
        self._default = default_runner
        self._modules = module_registry

    def parse(self, text: str) -> ParsedCommand:
        text = text.strip()

        if text == "/cancel":
            return ParsedCommand(runner=self._default, prompt="", is_cancel=True)
        if text == "/status":
            return ParsedCommand(runner=self._default, prompt="", is_status=True)
        if text == "/reset":
            return ParsedCommand(runner=self._default, prompt="", is_reset=True)
        if text == "/new":
            return ParsedCommand(runner=self._default, prompt="", is_new=True)

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

        return ParsedCommand(runner=self._default, prompt=text)
