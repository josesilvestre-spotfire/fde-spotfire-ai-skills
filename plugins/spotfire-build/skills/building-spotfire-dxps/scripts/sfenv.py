"""sfenv - where the DXP builder finds your workspace, the API index and Spotfire.

Every tool of the building-spotfire-dxps skill resolves these locations here, from environment
variables, so no tool carries a local path:

  DXP_WORKSPACE    folder that holds apps/, jobs/ and built DXPs (DXP_BUILDER_HOME is accepted as an
                   older alias)
  SFAPI_INDEX      the API index file (spotfire-api-<build>.json) written by dump_api.ps1; default:
                   the newest spotfire-api-*.json in $DXP_WORKSPACE/api/
  SPOTFIRE_HOME    the Spotfire Analyst install folder (the folder that holds Spotfire.Dxp.exe);
                   default: the newest %LOCALAPPDATA%/Spotfire/<version>/ that holds Spotfire.Dxp.exe
  SPOTFIRE_PYTHON  the python.exe Spotfire uses for Python data functions; default: the interpreter
                   under SPOTFIRE_HOME/Modules/Python Interpreter_*/python/

Standard library only. Nothing here starts Spotfire.
"""
import os
import re
from pathlib import Path

WORKSPACE_ENV = "DXP_WORKSPACE"
WORKSPACE_ALIASES = ("DXP_BUILDER_HOME",)
INDEX_ENV = "SFAPI_INDEX"


def workspace_root():
    """The DXP workspace folder, or None when neither DXP_WORKSPACE nor an alias is set."""
    for name in (WORKSPACE_ENV,) + WORKSPACE_ALIASES:
        value = os.environ.get(name)
        if value:
            return Path(value)
    return None


def _build_key(path):
    m = re.search(r"-([\d.]+)\.json$", Path(path).name)
    return tuple(int(x) for x in m.group(1).split(".") if x) if m else ()


def api_dir():
    """Folder of the API index: the folder of SFAPI_INDEX, else $DXP_WORKSPACE/api, else None."""
    env = os.environ.get(INDEX_ENV)
    if env:
        return Path(env).parent
    ws = workspace_root()
    return ws / "api" if ws else None


def api_index(folder=None):
    """The public API index file, or None when there is none.

    folder: look only there (newest spotfire-api-*.json). Without it: SFAPI_INDEX when the file
    exists, else the newest spotfire-api-*.json in $DXP_WORKSPACE/api/."""
    if folder is None:
        env = os.environ.get(INDEX_ENV)
        if env:
            return Path(env) if Path(env).is_file() else None
        folder = api_dir()
    if folder is None or not Path(folder).is_dir():
        return None
    files = sorted(Path(folder).glob("spotfire-api-*.json"), key=_build_key)
    return files[-1] if files else None


NO_INDEX_HINT = ("no Spotfire API index found: set SFAPI_INDEX to a spotfire-api-<build>.json, or run "
                 "scripts/dump_api.ps1 to write one into $DXP_WORKSPACE/api/")


def _version_key(path):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[._]", path.name))


def spotfire_home():
    """The Analyst install folder (holds Spotfire.Dxp.exe), or None."""
    env = os.environ.get("SPOTFIRE_HOME")
    if env:
        return Path(env)
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Spotfire"
    if not base.is_dir():
        return None
    found = [p for p in base.iterdir() if (p / "Spotfire.Dxp.exe").is_file()]
    return sorted(found, key=_version_key)[-1] if found else None


def spotfire_modules():
    """SPOTFIRE_HOME/Modules, or None."""
    home = spotfire_home()
    if home is None:
        return None
    mods = home / "Modules"
    return mods if mods.is_dir() else None


def spotfire_python():
    """Spotfire's python.exe, or None."""
    env = os.environ.get("SPOTFIRE_PYTHON")
    if env:
        return Path(env)
    mods = spotfire_modules()
    if mods is None:
        return None
    found = sorted(mods.glob("Python Interpreter_*/python/python.exe"), key=lambda p: _version_key(p.parent.parent))
    return found[-1] if found else None
