"""
Skills auto-loader — discovers and registers all skill modules.
"""
import importlib
import pkgutil
import logging
from pathlib import Path
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)


def discover_skills() -> list[BaseSkill]:
    """Discover and instantiate all skills in this package."""
    skills = []
    package_dir = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        if module_name.startswith("_") or module_name == "base_skill":
            continue

        try:
            module = importlib.import_module(f".{module_name}", package="skills")

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                ):
                    skill = attr()
                    skills.append(skill)
                    logger.info(f"Discovered skill: {skill.name} from {module_name}")

        except Exception as e:
            logger.error(f"Failed to load skill {module_name}: {e}")

    return skills
