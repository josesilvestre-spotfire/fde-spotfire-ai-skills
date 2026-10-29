"""Where the engine looks for packs, profiles, bundles and tag maps by default.

The engine ships inside a skill folder:

    <skill>/scripts/tssme/          this package
    <skill>/assets/examples/        the synthetic example pack, profile and bundle

Every search below can be extended with an environment variable, which is the normal way
to point the engine at your own packs and profiles. Nothing here names a pack.
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))

ENGINE_ROOT = os.path.dirname(_HERE)          # the folder holding the tssme package
SKILL_ROOT = os.path.dirname(ENGINE_ROOT)     # the skill folder, when shipped in one
EXAMPLES_DIR = os.path.join(SKILL_ROOT, "assets", "examples")


def example_dirs() -> list[str]:
    """The shipped example folders, if present. A vendored copy of the engine without the
    skill around it simply has none."""
    return [EXAMPLES_DIR] if os.path.isdir(EXAMPLES_DIR) else []


def sibling_asset_dirs() -> list[str]:
    """`assets` folders of skills installed next to this one.

    A plugin installs its skills side by side. A skill that ships a pack keeps it under its
    own `assets/` folder, so scanning the siblings' `assets/` folders discovers it without
    the engine knowing which skill, or which pack, is there.
    """
    skills_dir = os.path.dirname(SKILL_ROOT)
    if not os.path.isdir(skills_dir):
        return []
    out = []
    for entry in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, entry, "assets")
        if entry != os.path.basename(SKILL_ROOT) and os.path.isdir(path):
            out.append(path)
    return out
