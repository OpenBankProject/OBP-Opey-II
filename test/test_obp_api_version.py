"""The OBP-API version every Opey call uses.

OBP-API deployments can switch off the versions below v5.1.0, so every path Opey sends
to OBP-API, every example it shows the model and every OBP_API_VERSION it is configured
with must be v5.1.0 or newer. This test reads the sources and fails on any `obp/vX.Y.Z`
below v5.1.0, or OBP_API_VERSION set below v5.1.0, that is not listed in BELOW_V510, so
a new call on an old version cannot slip in.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# "file|fragment" -> why that line is still below v5.1.0. A line is allowed when it is in
# `file` (relative to the repository root) and contains `fragment`. Empty: every call has
# a v5.1.0 or newer equivalent.
BELOW_V510: dict[str, str] = {}

# Where OBP-API paths and versions are written: the code, its prompts, the scripts and
# the configuration examples.
SOURCE_ROOTS = ["src", "scripts"]
ROOT_FILES = [".env.example", "docker-compose.yml", "Dockerfile", "run_dev.sh", "mcp_servers.example.json"]
EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".toml", ".sh", ".js", ".html"}
SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".venv", "build", "dist"}
# This file, whose examples name old versions on purpose.
THIS_FILE = "test/test_obp_api_version.py"

OBP_PATH_VERSION = re.compile(r"obp/v(\d+)\.(\d+)\.(\d+)(?![\d.])")
VERSION_LITERAL = re.compile(r"(?<![\w.])v(\d+)\.(\d+)\.(\d+)(?![\d.])")


def _below_v510(match: re.Match) -> bool:
    return tuple(int(p) for p in match.groups()) < (5, 1, 0)


def versions_below_v510(line: str) -> list[str]:
    """Every `obp/vX.Y.Z` in `line` whose version is below v5.1.0, as written."""
    return [m.group(0) for m in OBP_PATH_VERSION.finditer(line) if _below_v510(m)]


def version_settings_below_v510(line: str) -> list[str]:
    """Every `vX.Y.Z` below v5.1.0 on a line that sets or defaults OBP_API_VERSION, which Opey builds paths from."""
    if "OBP_API_VERSION" not in line:
        return []
    return [m.group(0) for m in VERSION_LITERAL.finditer(line) if _below_v510(m)]


def source_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for top in SOURCE_ROOTS:
        for path in sorted((ROOT / top).rglob("*")):
            parts = path.relative_to(ROOT).parts
            if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
                continue
            if path.is_file() and path.suffix in EXTENSIONS:
                files.append(path)
    return files


def calls_below_v510() -> list[str]:
    found = []
    for path in source_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            for version in versions_below_v510(line) + version_settings_below_v510(line):
                allowed = any(
                    key.split("|", 1)[0] == rel and key.split("|", 1)[1] in line for key in BELOW_V510
                )
                if not allowed:
                    found.append(f"{rel}:{n} {version}")
    return found


def test_finds_the_sources():
    # Tests that the scan reads the real sources, so an empty result means "no old version", not "no files".
    files = source_files()
    assert len(files) > 50, f"found only {len(files)} source files"
    assert ROOT / "src" / "auth" / "auth.py" in files
    assert ROOT / ".env.example" in files


def test_calls_obp_api_on_v510_or_newer():
    # Tests that no OBP-API path or OBP_API_VERSION below v5.1.0 exists outside the listed lines.
    assert calls_below_v510() == []


def test_every_listed_line_still_exists():
    # Tests that each entry in BELOW_V510 still matches a line, so a call that moved to v5.1.0 is also removed from the list.
    stale = []
    for key in BELOW_V510:
        file, fragment = key.split("|", 1)
        path = ROOT / file
        if not path.is_file() or fragment not in path.read_text(encoding="utf-8"):
            stale.append(key)
    assert stale == []


def test_recognises_the_ways_an_old_version_can_be_written():
    # Tests the matcher itself: old versions are found with or without a leading slash, newer ones are not.
    assert versions_below_v510("await client.get('/obp/v4.0.0/x')") == ["obp/v4.0.0"]
    assert versions_below_v510("api POST obp/v5.0.0/banks") == ["obp/v5.0.0"]
    assert versions_below_v510("f'{base}/obp/v4.0.0/x' and '/obp/v1.2.1/y'") == ["obp/v4.0.0", "obp/v1.2.1"]
    assert versions_below_v510("'/obp/v5.1.0/x'") == []
    assert versions_below_v510("/obp/v6.0.0/root and /obp/v7.0.0/my/accounts") == []
    assert versions_below_v510("/obp/dynamic-entity/x") == []
    assert version_settings_below_v510('OBP_API_VERSION="v4.0.0"') == ["v4.0.0"]
    assert version_settings_below_v510("os.getenv('OBP_API_VERSION', 'v5.0.0')") == ["v5.0.0"]
    assert version_settings_below_v510('OBP_API_VERSION="v6.0.0"') == []
    assert version_settings_below_v510("version v4.0.0 of something else") == []
