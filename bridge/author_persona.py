"""Version 2 author reconstruction contracts; semantic claims need human review."""
from pathlib import Path

from book_skill_common import ContractError, SCHEMA, digest, read_yaml, text

AUTHOR_KINDS = ("habits", "paths")
VOICE_LEVELS = {"author", "narrator", "character", "quoted", "editor", "translator", "mixed"}


def refs(value, known, label, required=True):
    if not isinstance(value, list) or (required and not value):
        raise ContractError(f"{label}: reference list required")
    if len(value) != len(set(value)) or any(x not in known for x in value):
        raise ContractError(f"{label}: duplicate/unknown reference")
    return value


def episodes_from(book, snapshot, src, anchors):
    record = read_yaml(Path(book) / "reading/episodes.yaml")
    if record.get("schema_version") != SCHEMA or record.get("source") != snapshot["source"]:
        raise ContractError("episode source/schema differs from actual source")
    values, episodes = record.get("episodes"), {}
    if not isinstance(values, list) or not values:
        raise ContractError("nonempty reading episodes required")
    for episode in values:
        eid = text(episode.get("id"), "episode.id")
        if eid in episodes:
            raise ContractError(f"duplicate episode: {eid}")
        start, end = episode.get("start"), episode.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(src):
            raise ContractError(f"{eid}: invalid episode interval")
        if episode.get("span_sha256") != digest(src[start:end].encode()):
            raise ContractError(f"{eid}: episode span changed")
        for field in ("locator", "task", "progression", "reading_effect", "completeness"):
            text(episode.get(field), f"{eid}.{field}")
        voice = episode.get("voice", {})
        if voice.get("level") not in VOICE_LEVELS:
            raise ContractError(f"{eid}: voice level required")
        text(voice.get("speaker"), f"{eid}.voice.speaker")
        for aid in refs(episode.get("anchors"), anchors, f"{eid}.anchors", False):
            anchor = anchors[aid]
            from book_skill_common import qnorm
            if not start <= anchor["start"] < anchor["start"] + len(qnorm(anchor["quote"])) <= end:
                raise ContractError(f"{eid}: anchor {aid} outside episode")
        episodes[eid] = episode
    for aid, anchor in anchors.items():
        linked = refs(anchor.get("episodes"), episodes, f"{aid}.episodes")
        if any(aid not in episodes[eid]["anchors"] for eid in linked):
            raise ContractError(f"{aid}: episode links must be reciprocal")
    return episodes


def node_contracts(nodes, kinds, episodes):
    for nid, node in nodes.items():
        if kinds[nid] not in AUTHOR_KINDS:
            continue
        refs(node.get("episodes"), episodes, f"{nid}.episodes")
        grounded = {aid for eid in node["episodes"] for aid in episodes[eid]["anchors"]}
        if set(node["anchors"]) - grounded:
            raise ContractError(f"{nid}: supporting anchors outside declared episodes")
        refs(node.get("counterepisodes", []), episodes, f"{nid}.counterepisodes", False)
        if kinds[nid] == "habits":
            for field in ("trigger", "move", "effect", "alternatives", "counterevidence", "revise_when"):
                text(node.get(field), f"{nid}.{field}")
            if node.get("stability") not in {"local", "cross_context"}:
                raise ContractError(f"{nid}: habit stability must be declared")
        else:
            for field in ("task", "selection", "composition", "revise_when"):
                text(node.get(field), f"{nid}.{field}")
            refs(node.get("habits"), {i for i in nodes if kinds[i] == "habits"}, f"{nid}.habits")
            refs(node.get("operators"), {i for i in nodes if kinds[i] == "operators"}, f"{nid}.operators")


def persona_contracts(model, nodes, kinds, episodes, styles, examples, closure):
    for field in ("portrait", "scope", "voice_policy", "limits"):
        text(model.get("author", {}).get(field), f"author.{field}")
    for field in ("reading", "reconstruction", "runtime", "acceptance"):
        text(model["scope"].get(field), f"scope.{field}")
    for kind in AUTHOR_KINDS:
        if not any(kinds[nid] == kind for nid in closure):
            raise ContractError(f"core needs a reviewed {kind} dependency")
    for sid, style in styles.items():
        if not any(kinds[nid] in AUTHOR_KINDS for nid in style["uses"]):
            raise ContractError(f"{sid}: expression must connect to a habit/path")
    for nid in closure:
        if kinds[nid] != "paths":
            continue
        node = nodes[nid]
        expression = refs(node.get("expression"), styles, f"{nid}.expression")
        used_examples = refs(node.get("examples"), examples, f"{nid}.examples")
        if not {"application", "condition_variant"}.issubset({examples[e]["kind"] for e in used_examples}):
            raise ContractError(f"{nid}: joint application and condition variant required")
        for eid in used_examples:
            example = examples[eid]
            if nid not in example["uses"] or not set(example["expression"]) & set(expression):
                raise ContractError(f"{nid}: example {eid} disconnected from path/expression")
            if not set(node["operators"]) & set(example["uses"]):
                raise ContractError(f"{nid}: example {eid} must exercise a path operation")
    inventory = {nid: kinds[nid] for nid in sorted(closure) if kinds[nid] in AUTHOR_KINDS}
    for nid in closure:
        if kinds[nid] == "paths":
            inventory.update({sid: "expression" for sid in nodes[nid]["expression"]})
    return inventory


def author_profile(model):
    """Generated view, never a second editable source of author instructions."""
    author = model["author"]
    lines = ["# 作者画像（生成视图）", "", author["portrait"], "",
             "重建范围：" + author["scope"], "", "声音层次：" + author["voice_policy"], "",
             "局限：" + author["limits"], "", "## 习惯与条件", ""]
    for habit in model["habits"]:
        lines += [f"### {habit['id']}", "", habit["statement"], "",
                  "触发：" + habit["trigger"], "", "动作与作用：" + habit["move"] + "；" + habit["effect"], "",
                  "条件：" + habit["conditions"], "", "其他解释：" + habit["alternatives"], "",
                  "反证与修正：" + habit["counterevidence"] + "；" + habit["revise_when"], ""]
    lines += ["## 任务与路径选择", ""]
    for path in model["paths"]:
        lines += [f"### {path['id']}", "", path["task"], "", path["selection"], "", path["composition"], "",
                  "修正：" + path["revise_when"], ""]
    return "\n".join(lines) + "\n"
