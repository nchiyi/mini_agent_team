# src/modules/manifest.py
# Deprecated: use src.skills.manifest instead.
import warnings
warnings.warn(
    "src.modules.manifest is deprecated; import from src.skills.manifest",
    DeprecationWarning,
    stacklevel=2,
)

from src.skills.manifest import SkillManifest as ModuleManifest, parse_manifest  # noqa: F401, E402

__all__ = ["ModuleManifest", "parse_manifest"]
