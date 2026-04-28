# src/gateway/app_context.py
"""Shared application dependencies bundled into one object."""
from dataclasses import dataclass, field

from src.core.config import Config
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler
from src.gateway.bot_registry import BotRegistry
from src.gateway.bot_turns import BotTurnTracker
from src.gateway.nlu import FastPathDetector
from src.gateway.rate_limit import RateLimiter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.skills.loader import SkillRegistry


@dataclass
class AppContext:
    cfg: Config
    runners: dict
    module_registry: SkillRegistry
    router: Router
    session_mgr: SessionManager
    tier1: Tier1Store
    tier3: Tier3Store
    assembler: ContextAssembler
    nlu_detector: FastPathDetector
    rate_limiter: RateLimiter
    bot_registry: BotRegistry = field(default_factory=BotRegistry)
    bot_turns: BotTurnTracker = field(default_factory=BotTurnTracker)
