"""Check every skill and plugin in this repo.

Checks:
  - SKILL.md frontmatter follows the Agent Skills spec (keys, name, description)
  - the skill folder name equals the skill name
  - SKILL.md body length and an approximate token count
  - copies of the shared formats match the canonical files
  - files copied between skills (SYNCED) match their source
  - marketplace.json and every plugin.json agree on names and versions
  - no local paths, email addresses, tokens or non-public API index files,
    also inside zip-based files (DXP, XLSX)
  - optional: no term from a private list (--terms FILE, one term per line)

Usage:
  python scripts/check_skills.py [--terms FILE] [--quiet]

Exit code 1 when any error is found. Standard library only.
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_KEYS = {"name", "description", "license", "compatibility",
                "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_BODY_LINES = 500
TOKEN_WARN = 5000
CANONICAL = ROOT / "plugins/spotfire-reference/skills/spotfire-reference/references"
SHARED_FORMATS = ("app-brief-format.md", "logic-spec-format.md",
                  "naming-standard.md")
# Files copied between skills on purpose, so each skill works alone.
# (source folder, copy folder, files): the copy must equal the source.
_P = "plugins/"
SYNCED = [
    (_P + "spotfire-testing/skills/running-spotfire-unattended/scripts",
     _P + "spotfire-version-control/skills/"
     "updating-data-functions-with-claude/scripts",
     ("build_job.py", "build_runner.py", "runner_autoclick.js",
      "runner_job.py", "sfrun.py")),
    (_P + "spotfire-version-control/skills/tracking-dxps-in-git/references",
     _P + "spotfire-version-control/skills/"
     "updating-data-functions-with-claude/references",
     ("script-trust.md",)),
    (_P + "spotfire-ingest/skills/ingesting-excel-workbooks",
     _P + "spotfire-ingest/skills/ingesting-prototypes",
     ("references/spec-draft.md", "scripts/check_handoff.py")),
    (_P + "spotfire-build/skills/building-visualization-mods/assets/"
     "demo-layers/src",
     _P + "spotfire-build/skills/building-spotfire-dxps/assets/examples/"
     "mod-layers-demo/mods/demo-layers",
     ("index.html", "main.js", "main.css", "mod-manifest.json",
      "icon.svg")),
]
TEXT_SUFFIXES = {".md", ".py", ".ps1", ".json", ".yaml", ".yml", ".txt",
                 ".html", ".css", ".js", ".ts", ".toml", ".cfg", ".ini",
                 ".csv", ".xml", ".sh", ".cmd", ".bat", ".r", ".svg"}
ZIP_SUFFIXES = {".dxp", ".xlsx", ".xlsm", ".zip", ".mod", ".spk",
                ".docx", ".pptx"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", "results"}

LEAK_PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<|%|\$|\{)\w", re.I),
     "Windows user path"),
    (re.compile(r"/c/Users/\w", re.I), "Windows user path (POSIX form)"),
    (re.compile(r"\b(Desktop|Downloads|OneDrive)[\\/]\w", re.I),
     "personal folder path"),
    (re.compile(r"[\w.+-]+@(?!example\.|anthropic\.com)[\w-]+\.[a-z]{2,}\b"),
     "email address"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS key"),
    (re.compile(r"spotfire-internal-[\d.]+\.json|\.internal\.txt"),
     "non-public Spotfire API index"),
]


def iter_files(base):
    for path in base.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def read_text(path):
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def parse_frontmatter(text):
    """Return (dict, body) for a SKILL.md. Handles the simple YAML
    subset the spec allows: scalar keys, quoted strings, folded
    continuation lines and one level of nested keys under metadata."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    data, key = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and key:
            if key == "metadata":
                continue
            data[key] = (data[key] + " " + line.strip()).strip()
            continue
        if ":" not in line:
            return None, body
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value in (">", "|", ">-", "|-"):
            value = ""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key] = value
    return data, body


def check_skills(errors, warnings, rows):
    for skill_md in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        rel = skill_md.relative_to(ROOT)
        folder = skill_md.parent.name
        text = read_text(skill_md) or ""
        meta, body = parse_frontmatter(text)
        if meta is None:
            errors.append(f"{rel}: missing or unreadable frontmatter")
            continue
        for key in meta:
            if key not in ALLOWED_KEYS:
                errors.append(f"{rel}: frontmatter key '{key}' is not "
                              "allowed")
        name = meta.get("name", "")
        desc = meta.get("description", "")
        if not NAME_RE.match(name) or len(name) > 64:
            errors.append(f"{rel}: invalid name '{name}'")
        if name != folder:
            errors.append(f"{rel}: name '{name}' does not match folder "
                          f"'{folder}'")
        if not desc:
            errors.append(f"{rel}: description is empty")
        elif len(desc) > 1024:
            errors.append(f"{rel}: description has {len(desc)} characters "
                          "(max 1024)")
        lines = body.count("\n") + 1
        tokens = len(body) // 4
        if lines > MAX_BODY_LINES:
            errors.append(f"{rel}: body has {lines} lines "
                          f"(max {MAX_BODY_LINES})")
        if tokens > TOKEN_WARN:
            warnings.append(f"{rel}: body is about {tokens} tokens")
        for match in re.finditer(r"\]\(([^)#]+)\)", body):
            target = match.group(1)
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (skill_md.parent / target).exists():
                errors.append(f"{rel}: broken link '{target}'")
        rows.append((skill_md.parent.parent.parent.name, name, lines,
                     tokens))


def check_synced_copies(errors):
    for source, copy, names in SYNCED:
        for name in names:
            src, dst = ROOT / source / name, ROOT / copy / name
            if not src.exists() or not dst.exists():
                errors.append(f"synced copy missing: {source}/{name} or "
                              f"{copy}/{name}")
            elif src.read_bytes() != dst.read_bytes():
                errors.append(f"{copy}/{name}: differs from {source}/{name} "
                              "(copy the source over it)")


def check_shared_formats(errors):
    for fname in SHARED_FORMATS:
        canonical = CANONICAL / fname
        if not canonical.exists():
            errors.append(f"canonical {fname} is missing")
            continue
        ref = canonical.read_bytes()
        for copy in ROOT.glob(f"plugins/*/skills/*/references/{fname}"):
            if copy != canonical and copy.read_bytes() != ref:
                errors.append(f"{copy.relative_to(ROOT)}: differs from "
                              f"the canonical {fname}")


def check_manifests(errors):
    market_path = ROOT / ".claude-plugin/marketplace.json"
    try:
        market = json.loads(market_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"marketplace.json: {exc}")
        return
    listed = set()
    for entry in market.get("plugins", []):
        name = entry.get("name")
        listed.add(name)
        source = ROOT / entry.get("source", "")
        manifest = source / ".claude-plugin/plugin.json"
        if not manifest.exists():
            errors.append(f"marketplace entry '{name}': {manifest} missing")
            continue
        plugin = json.loads(manifest.read_text(encoding="utf-8"))
        if plugin.get("name") != name:
            errors.append(f"{manifest.relative_to(ROOT)}: name "
                          f"'{plugin.get('name')}' != marketplace '{name}'")
        if entry.get("version") and \
                plugin.get("version") != entry.get("version"):
            errors.append(f"{manifest.relative_to(ROOT)}: version "
                          f"{plugin.get('version')} != marketplace "
                          f"{entry.get('version')}")
        if not list(source.glob("skills/*/SKILL.md")):
            errors.append(f"plugin '{name}' has no skills")
    for folder in ROOT.glob("plugins/*"):
        if folder.is_dir() and folder.name not in listed:
            errors.append(f"plugins/{folder.name} is not in "
                          "marketplace.json")


def load_terms(path):
    terms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    if not terms:
        return None
    pattern = "|".join(re.escape(t) for t in terms)
    return re.compile(rf"(?<![\w])(?:{pattern})(?![\w])", re.I)


def scan_text(errors, where, text, terms_re):
    for lineno, line in enumerate(text.splitlines(), 1):
        for regex, label in LEAK_PATTERNS:
            if regex.search(line):
                errors.append(f"{where}:{lineno}: {label}: "
                              f"{line.strip()[:100]}")
        if terms_re:
            hit = terms_re.search(line)
            if hit:
                errors.append(f"{where}:{lineno}: private term "
                              f"'{hit.group(0)}'")


def scan_zip(errors, path, rel, terms_re):
    """Scan the text members of a zip-based file (DXP, XLSX, mod)."""
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                data = archive.read(member)
                if b"\x00" in data[:4096]:
                    continue
                text = data.decode("utf-8", errors="replace")
                # Spotfire and Office XML escape backslashes rarely;
                # also scan with entities decoded.
                text = text.replace("&#92;", "\\")
                scan_text(errors, f"{rel}!{member}", text, terms_re)
    except zipfile.BadZipFile:
        errors.append(f"{rel}: unreadable zip-based file")


def check_leaks(errors, terms_re):
    me = Path(__file__).resolve()
    for path in iter_files(ROOT):
        if path.resolve() == me:
            continue
        rel = path.relative_to(ROOT)
        if path.suffix.lower() in ZIP_SUFFIXES:
            scan_zip(errors, path, rel, terms_re)
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and \
                path.name not in {"LICENSE", ".gitignore",
                                  ".gitattributes"}:
            if "internal" in path.name and "spotfire" in path.name:
                errors.append(f"{rel}: non-public Spotfire API index")
            continue
        text = read_text(path)
        if text is None:
            continue
        scan_text(errors, rel, text, terms_re)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--terms", help="file with private terms to "
                        "reject, one per line")
    parser.add_argument("--quiet", action="store_true",
                        help="do not print the size table")
    args = parser.parse_args()

    errors, warnings, rows = [], [], []
    check_skills(errors, warnings, rows)
    check_shared_formats(errors)
    check_synced_copies(errors)
    check_manifests(errors)
    check_leaks(errors, load_terms(args.terms) if args.terms else None)

    if not args.quiet:
        print(f"{'plugin':28} {'skill':40} {'lines':>5} {'tokens':>7}")
        for plugin, name, lines, tokens in rows:
            print(f"{plugin:28} {name:40} {lines:5} {tokens:7}")
        print(f"\n{len(rows)} skills")
    for warning in warnings:
        print(f"WARNING {warning}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
