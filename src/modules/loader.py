# src/modules/loader.py
# Deprecated: use src.skills.loader instead.
import warnings
warnings.warn(
    "src.modules.loader is deprecated; import from src.skills.loader",
    DeprecationWarning,
    stacklevel=2,
)

from src.skills.loader import (  # noqa: F401, E402
    LoadedSkill as LoadedModule,
    SkillRegistry as ModuleRegistry,
    load_skills as load_modules,
)

__all__ = ["LoadedModule", "ModuleRegistry", "load_modules"]
