"""Pure, bounded material drafts; image regions are chosen by the human caller."""
from app.exports.contracts import validate_math

FIELDS = {
    "knowledge": {"definition", "conditions", "common_errors"},
    "method": {"name", "conditions", "steps", "notes"},
    "question_type": {"name", "conditions", "structural_features"},
}


def validate(proposal):
    if not isinstance(proposal, dict) or set(proposal) != {"printed_text", "missing_fields", "nodes", "answer"}:
        raise ValueError("material_schema_invalid")
    text = proposal["printed_text"]
    if text is not None and (not isinstance(text, str) or len(text) > 20000 or "\x00" in text):
        raise ValueError("material_schema_invalid")
    missing = proposal["missing_fields"]
    if not isinstance(missing, list) or len(missing) > 30 or any(not isinstance(row, str) or len(row) > 200 for row in missing):
        raise ValueError("material_schema_invalid")
    if not text and "printed_text" not in missing:
        raise ValueError("material_unknown_missing")
    nodes = proposal["nodes"]
    if not isinstance(nodes, list) or len(nodes) > 3:
        raise ValueError("material_schema_invalid")
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"kind", "data"} or node["kind"] not in FIELDS:
            raise ValueError("material_schema_invalid")
        data = node["data"]
        if not isinstance(data, dict) or set(data) - FIELDS[node["kind"]]:
            raise ValueError("material_schema_invalid")
        for value in data.values():
            if not isinstance(value, str) or len(value) > 20000 or "\x00" in value:
                raise ValueError("material_schema_invalid")
        name = "definition" if node["kind"] == "knowledge" else "name"
        if not data.get(name, "").strip():
            raise ValueError("material_schema_invalid")
    answer = proposal["answer"]
    if answer is not None:
        if not isinstance(answer, dict) or set(answer) != {"body", "formulas", "basis"}:
            raise ValueError("material_schema_invalid")
        for key, limit in (("body", 20000), ("basis", 4000)):
            if not isinstance(answer[key], str) or not answer[key].strip() or len(answer[key]) > limit or "\x00" in answer[key]:
                raise ValueError("material_schema_invalid")
        if not isinstance(answer["formulas"], list) or len(answer["formulas"]) > 20:
            raise ValueError("material_schema_invalid")
        for formula in answer["formulas"]:
            validate_math(formula)
    return proposal


def records(proposal, refs, number=""):
    """Companion records from typed content, never from a document's prose/index."""
    validate(proposal)
    rows = [{"id": "question", "kind": "question", "data": {
        "printed_text": proposal["printed_text"], "original_number": number, "sources": refs}}]
    for index, node in enumerate(proposal["nodes"]):
        identity = f"node-{index}"
        rows.append({"id": identity, "kind": node["kind"], "data": {**node["data"], "sources": refs}})
        rows.append({"id": f"link-{index}", "kind": "link", "data": {
            "question": "question", "node": identity,
            "role": {"knowledge": "applies", "method": "primary", "question_type": "belongs"}[node["kind"]]}})
    if proposal["answer"] is not None:
        rows.append({"id": "answer", "kind": "answer", "data": {"question": "question", **proposal["answer"]}})
    return {"schema_version": "swb.skill-records.v1", "records": rows}
