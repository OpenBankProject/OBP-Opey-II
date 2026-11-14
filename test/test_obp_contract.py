"""The contract between Opey and OBP-API.

obp-api-contract/contract.json lists every OBP-API call Opey makes from its own code, with
the response fields the code reads. obp-api-contract/snapshot.json is what an OBP-API
documents for those calls, written by obp-api-contract/snapshot.py from its resource docs.
These tests need no server: they check that the list matches the code, and that every call
reaches an endpoint OBP-API documents, with every field the code reads. Retake the snapshot
from a new OBP-API build to learn whether that build breaks Opey.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "obp-api-contract"

# A string that builds an OBP-API path: a version (/obp/v6.0.0) or one filled in (/obp/{version}).
OBP_PATH = re.compile(r"/obp/(v\d|\{)")


def load(name: str) -> dict:
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


def calls() -> list[dict]:
    return load("contract.json")["calls"]


def key(call: dict) -> str:
    return f"{call['verb']} {call['path']}"


def documented(call: dict, snapshot: dict) -> dict | None:
    """The snapshot entry for a call, or None."""
    return next((e for e in snapshot["endpoints"] if key(e) == key(call)), None)


def undocumented_reads(call: dict, fields: set[str]) -> list[str]:
    """The reads of `call` that `fields` does not document. A read written `a|b` is satisfied by either field."""
    return [read for read in call.get("reads", []) if not any(f in fields for f in read.split("|"))]


def docstring_lines(text: str) -> set[int]:
    """Line numbers of the module, class and function docstrings in Python source."""
    lines = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def obp_path_lines_in(text: str) -> list[tuple[int, str]]:
    """Lines of Python source that build an OBP-API path, skipping comments and docstrings: (line number, line)."""
    skip = docstring_lines(text)
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        code = line.strip()
        if n in skip or code.startswith("#"):
            continue
        if ("'" in code or '"' in code) and OBP_PATH.search(code):
            out.append((n, line))
    return out


def obp_path_lines() -> list[tuple[str, int, str]]:
    """Lines of Opey's source that build an OBP-API path: (file relative to the repository, line number, line)."""
    out = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for n, line in obp_path_lines_in(path.read_text(encoding="utf-8")):
            out.append((rel, n, line))
    return out


def env_example_api_version() -> str:
    match = re.search(r'^OBP_API_VERSION="?([^"\s]+)"?', (ROOT / ".env.example").read_text(encoding="utf-8"), re.M)
    assert match, ".env.example sets no OBP_API_VERSION"
    return match.group(1)


def test_every_call_in_the_contract_is_in_its_source_file():
    # Tests that each listed call still exists: every needle of an entry occurs in the entry's source file.
    gone = []
    for call in calls():
        text = (ROOT / call["source"]).read_text(encoding="utf-8")
        gone += [f"{key(call)} - {needle}" for needle in call["needles"] if needle not in text]
    assert gone == []


def test_every_obp_api_call_in_the_source_is_in_the_contract():
    # Tests coverage: a line that builds an OBP-API path must contain a needle of a call listed for that file,
    # so a new call cannot reach OBP-API without its fields being recorded.
    listed = calls()
    unlisted = [
        f"{file}:{n} {line.strip()}"
        for file, n, line in obp_path_lines()
        if not any(c["source"] == file and any(needle.strip() in line for needle in c["needles"]) for c in listed)
    ]
    assert unlisted == []


def test_paths_built_from_obp_api_version_use_the_version_of_env_example():
    # Tests that a call whose version comes from OBP_API_VERSION is recorded with the version .env.example sets,
    # so the snapshot checks the endpoint Opey reaches by default.
    version = env_example_api_version()
    wrong = [
        f"{key(c)}: .env.example sets {version}"
        for c in calls()
        if any("OBP_API_VERSION" in needle for needle in c["needles"]) and c["path"].split("/")[2] != version
    ]
    assert wrong == []


def test_the_snapshot_was_taken_for_this_contract():
    # Tests that snapshot.json holds exactly the calls of contract.json; otherwise rerun snapshot.py.
    snapshot = load("snapshot.json")
    assert {key(c) for c in calls()} == {key(e) for e in snapshot["endpoints"]}


def test_every_call_reaches_an_endpoint_obp_api_documents(capsys):
    # Tests that each call's version and path name a documented endpoint, unless the entry records why not
    # (undocumented_endpoint). A recorded gap that OBP-API has since documented fails too, so the note goes.
    snapshot = load("snapshot.json")
    problems = []
    for call in calls():
        entry = documented(call, snapshot) or {}
        missing = entry.get("missing", False)
        known_gap = call.get("undocumented_endpoint")
        if missing and not known_gap:
            problems.append(f"{key(call)}: no documented endpoint")
        elif not missing and known_gap:
            problems.append(f"{key(call)}: now documented as {entry.get('operation_id')}; drop undocumented_endpoint")
        elif missing and known_gap:
            print(f"known gap - {key(call)}: {known_gap}")
        if entry.get("ambiguous"):
            problems.append(f"{key(call)}: matches several endpoints {entry['ambiguous']}")
    assert problems == []


def test_every_field_the_code_reads_is_documented():
    # Tests that each field the code reads is in the documented response of its endpoint, unless the entry
    # lists it in undocumented_fields; a listed field that OBP-API now documents fails, so the list shrinks.
    snapshot = load("snapshot.json")
    problems = []
    for call in calls():
        entry = documented(call, snapshot)
        if not entry or entry.get("missing"):
            continue
        fields = set(entry["fields"])
        known = set(call.get("undocumented_fields", []))
        for read in undocumented_reads(call, fields):
            if read in known:
                print(f"known gap - {key(call)}: {read} is not documented")
            else:
                problems.append(f"{key(call)} ({entry['operation_id']}): reads {read}, not documented")
        problems += [f"{key(call)}: {f} is now documented; drop it from undocumented_fields" for f in sorted(known & fields)]
    assert problems == []


def test_a_renamed_or_removed_field_is_reported():
    # Tests the check itself: with `user_id` gone from the documented fields, the read is reported,
    # and a read with an alternative (`user_id|id`) passes on either field.
    current_user = {"reads": ["user_id"]}
    assert undocumented_reads(current_user, {"username", "email"}) == ["user_id"]
    either = {"reads": ["user_id|id"]}
    assert undocumented_reads(either, {"id"}) == []
    assert undocumented_reads(either, set()) == ["user_id|id"]


def test_the_coverage_scan_skips_comments_and_docstrings():
    # Tests the scan itself: a path in a docstring or a comment is not a call, a path in code is.
    source = (
        'def get(path):\n'
        '    """Example: client.get(\'/obp/v5.1.0/banks\')"""\n'
        '    # url = "/obp/v5.1.0/banks"\n'
        '    return base + f"/obp/{version}/users/current"\n'
    )
    assert [n for n, _ in obp_path_lines_in(source)] == [4]
