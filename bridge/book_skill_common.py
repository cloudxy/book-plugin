"""Shared contracts for book-workflow's own thinking/narrative pipeline."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

import yaml

VERSION = "0.3.0"
SCHEMA = "book-skill/1"
INPUTS = (
    "thinking/model.yaml", "thinking/EXAMPLES.md", "expression/PROFILE.md",
    "evidence/anchors.yaml", "BOOK_OVERVIEW.md", "coverage-audit.md",
)
DIMENSIONS = ("fidelity", "modeling", "inference", "updating", "utility", "expression")
STYLE_DIMENSIONS = ("viewpoint", "organization", "tone", "rhythm", "naturalness", "preservation")
CASE_GROUPS = tuple(f"C{i:02}" for i in range(1, 16))


class ContractError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    """A repeated key must not silently replace an audited value."""


def _mapping(loader, node, deep=False):
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate YAML key: {key}")
        result[key] = value
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path):
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"expected mapping: {path}")
    return data


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ContractError(f"invalid slug: {value!r}")
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label}: nonempty text required")
    return value


def contained(root, rel):
    root = Path(root).resolve()
    rel = Path(rel)
    if rel.is_absolute() or ".." in rel.parts:
        raise ContractError(f"relative package path required: {rel}")
    current = root
    for part in rel.parts:
        current /= part
        if current.is_symlink():
            raise ContractError(f"symlink is not an input/payload: {current}")
    if not current.resolve().is_relative_to(root):
        raise ContractError(f"path escapes root: {rel}")
    return current


def tree_hashes(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ContractError(f"directory required: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContractError(f"symlink in tree: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def procedure_hash(book):
    root = Path(book) / ".cangjie/capabilities"
    if not root.exists():
        return None
    return digest(tree_hashes(root))


def bridge_state(task, include_evidence=False):
    task = Path(task)
    files = {rel: digest((task / rel).read_bytes()) for rel in ("book_text.md", "verified.md")}
    for rel, sha in tree_hashes(task / "skills").items():
        if include_evidence or Path(rel).name == "SKILL.md":
            files[f"skills/{rel}"] = sha
    return digest(files)


def load_source(path):
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    if path.suffix.lower() not in {".txt", ".md"}:
        raise ContractError("source must be UTF-8 txt/md or PDF; extract EPUB/transcripts first")
    return path.read_text(encoding="utf-8")


def qnorm(value):
    return re.sub(r"\s", "", value)


def source_hashes(source):
    path = Path(source)
    return {"raw_sha256": digest(path.read_bytes()),
            "text_sha256": digest(qnorm(load_source(path)).encode()), "normalization": "qnorm-v1"}


def input_snapshot(book, source):
    book = Path(book)
    files = {}
    for rel in (*INPUTS, "GLOSSARY.md"):
        path = contained(book, rel)
        if path.is_file():
            files[rel] = digest(path.read_bytes())
        elif rel in INPUTS:
            raise ContractError(f"missing required input: {rel}")
    return {"files": files, "source": source_hashes(source), "procedures": procedure_hash(book)}


def section(body, heading):
    pattern = rf"^## {re.escape(heading)}\s*$"
    matches = list(re.finditer(pattern, body, re.M))
    if len(matches) != 1:
        raise ContractError(f"exactly one '## {heading}' required")
    tail = body[matches[0].end():]
    end = re.search(r"^## ", tail, re.M)
    return text(tail[:end.start()] if end else tail, heading).strip()


def markdown_records(body):
    """Metadata fences remain readable prose and have one unambiguous parser."""
    records = []
    for match in re.finditer(r"^```yaml\n(.*?)^```\s*$", body, re.M | re.S):
        data = yaml.load(match.group(1), Loader=UniqueLoader)
        if not isinstance(data, dict):
            raise ContractError("metadata fence must be a mapping")
        records.append(data)
    return records


def engine_hash():
    root = Path(__file__).parent
    return digest({p.name: digest(p.read_bytes()) for p in sorted(root.glob("*.py"))})


def verify_package(root):
    root = Path(root).resolve()
    manifest = read_json(root / "book-workflow-manifest.json")
    if manifest.get("schema_version") != SCHEMA:
        raise ContractError("unsupported package manifest")
    actual = tree_hashes(root)
    actual.pop("book-workflow-manifest.json", None)
    if actual != manifest.get("files") or digest(actual) != manifest.get("build_id"):
        raise ContractError("package payload changed or files missing/unlisted")
    if [p for p in actual if Path(p).name == "SKILL.md"] != ["SKILL.md"]:
        raise ContractError("exactly one discoverable SKILL.md required")
    for rel in actual:
        if Path(rel).name.upper() == "ENTRY.MD":
            raise ContractError("upstream routing ENTRY.md must not be shipped")
        if rel.endswith(".md"):
            body = contained(root, rel).read_text(encoding="utf-8")
            prose = re.sub(r"```.*?```", "", body, flags=re.S)
            for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", prose):
                if re.match(r"(?:https?://|mailto:|#)", target):
                    continue
                raw = unquote(target.split("#", 1)[0])
                resolved = (root / rel).parent / raw
                if Path(raw).is_absolute() or not resolved.resolve().is_relative_to(root):
                    raise ContractError(f"external/absolute link in {rel}: {target}")
                if not resolved.exists():
                    raise ContractError(f"broken link in {rel}: {target}")
    entry = (root / "SKILL.md").read_text(encoding="utf-8")
    for required in ("## 思想核心", "## 叙事与口吻", "## 运用方式"):
        if required not in entry:
            raise ContractError(f"entry missing required runtime content: {required}")
    return manifest
