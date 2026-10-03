#!/usr/bin/env python3
"""Validate fabricated AI development/holdout fixtures without a provider or DB."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.schema import InvalidProposal, parse_response

FIXTURE_DIR = ROOT / "tests" / "ai" / "fixtures"
TASKS = {"question", "knowledge", "assessment", "variant"}
REQUIRED_TAGS = {
    "blank", "unreadable", "unknown_author", "classroom_notes", "prompted_after_completion",
}
ASSESSMENT_DIMENSIONS = {"answer", "method", "process", "calculation", "notation"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_split(name):
    path = FIXTURE_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("fixture_schema_version") == "study-workbench.ai-baseline-fixture.v1",
        f"{name}: unsupported fixture schema")
    require(data.get("split") == name and data.get("synthetic_only") is True,
        f"{name}: split must be explicitly synthetic")
    require(isinstance(data.get("examples"), list) and data["examples"],
        f"{name}: examples are missing")
    return data


def validate_example(example, split):
    case_id = example.get("case_id")
    prefix = "dev-" if split == "development" else "holdout-"
    require(isinstance(case_id, str) and case_id.startswith(prefix),
        f"{split}: case id must carry its split prefix")
    task = example.get("task")
    require(task in TASKS, f"{case_id}: unsupported task")
    page_id = example.get("source_page_id")
    require(isinstance(page_id, str) and page_id.startswith("synthetic-page-"),
        f"{case_id}: source page must be synthetic")
    require(isinstance(example.get("source_excerpt"), str) and example["source_excerpt"].strip(),
        f"{case_id}: source excerpt is missing")
    source_ids = example.get("source_revision_ids")
    region_ids = example.get("region_revision_ids")
    require(isinstance(source_ids, list) and source_ids and all(isinstance(x, str) for x in source_ids),
        f"{case_id}: source revision ids must be nonempty strings")
    require(all(value.startswith("synthetic-") for value in source_ids),
        f"{case_id}: source revision ids must be synthetic")
    require(len(source_ids) == len(set(source_ids)), f"{case_id}: duplicate source revision id")
    require(isinstance(region_ids, list) and set(region_ids) <= set(source_ids),
        f"{case_id}: region revisions must be included in allowed source ids")
    method_ids = example.get("method_revision_ids", [])
    require(isinstance(method_ids, list) and all(isinstance(item, str) for item in method_ids)
        and len(method_ids) == len(set(method_ids)) and set(method_ids) <= set(source_ids),
        f"{case_id}: selected method revisions must be unique allowed source ids")
    require(task != "variant" or method_ids, f"{case_id}: variant needs explicitly selected methods")
    require(isinstance(example.get("source_unknowns"), dict) and example["source_unknowns"],
        f"{case_id}: expected source unknowns must be recorded")
    require(isinstance(example.get("case_tags"), list), f"{case_id}: case tags are missing")
    tags = set(example["case_tags"])
    unknowns = example["source_unknowns"]
    if "blank" in tags:
        require(task == "question" and unknowns.get("printed_text") == "blank",
            f"{case_id}: blank scenario is mislabeled")
    if "unreadable" in tags:
        require(task in {"question", "assessment"}
            and "unreadable" in unknowns.values(), f"{case_id}: unreadable scenario is mislabeled")
    if "unknown_author" in tags:
        require(unknowns.get("author") == "unknown", f"{case_id}: author uncertainty is missing")
    if "classroom_notes" in tags:
        require(task in {"knowledge", "variant"} and "课堂" in example["source_excerpt"],
            f"{case_id}: classroom-note scenario is mislabeled")
    if "prompted_after_completion" in tags:
        require(task == "assessment" and example.get("prompt_after_attempt") is True
            and unknowns.get("independence") == "unknown",
            f"{case_id}: prompted completion must retain unknown independence")
    probe = example.get("contract_probe")
    require(isinstance(probe, dict), f"{case_id}: contract probe is missing")
    require(probe.get("source_revision_ids") == source_ids,
        f"{case_id}: probe must carry the exact selected source ids")

    parsed = parse_response(json.dumps(probe, ensure_ascii=False), task=task,
        allowed_sources=source_ids, allowed_regions=region_ids, allowed_methods=method_ids,
        attempt_legibility=example.get("attempt_legibility"))
    verify_unknown_probe(example, parsed)
    verify_rejections(example, source_ids, region_ids)
    return {"case_id": case_id, "split": split, "task": task, "source_page_id": page_id,
        "unknown_fields": sorted(example["source_unknowns"]),
        "contract_probe": "valid", "unknown_preservation_probe": "valid"}


def verify_unknown_probe(example, parsed):
    task = example["task"]
    expected = example.get("expected_unknowns", {})
    proposal = parsed["proposal"]
    if task == "question" and expected.get("printed_text_is_null"):
        require(proposal["printed_text"] is None, f"{example['case_id']}: unknown text was filled")
        require(set(expected["missing_fields"]) <= set(proposal["missing_fields"]),
            f"{example['case_id']}: blank or unreadable fields were not retained")
    elif task == "knowledge" and expected.get("conditions_empty"):
        require(proposal["conditions"] == [], f"{example['case_id']}: unknown conditions were invented")
        require(expected["definition_contains"] in proposal["definition"],
            f"{example['case_id']}: source limitation was not stated")
    elif task == "assessment":
        require(set(expected.get("dimensions", [])) == ASSESSMENT_DIMENSIONS,
            f"{example['case_id']}: five-dimension unknown probe is incomplete")
        dimensions = {item["dimension"]: item for item in proposal["dimensions"]}
        for name in expected["dimensions"]:
            item = dimensions[name]
            require(item["judgment"] == "unknown" and item["basis"] == "undetermined"
                and bool(item["unknown_reason"]),
                f"{example['case_id']}: {name} unknown was upgraded")
    else:
        expected_fields = expected.get("manual_review_fields", [])
        require(expected_fields and set(expected_fields) <= set(example["source_unknowns"]),
            f"{example['case_id']}: variant unknowns are not retained for manual review")
        require(isinstance(example.get("manual_review_note"), str)
            and example["manual_review_note"].strip(),
            f"{example['case_id']}: variant unknowns need an explicit human-review note")


def verify_rejections(example, source_ids, region_ids):
    probe = example["contract_probe"]
    bad_source = deepcopy(probe)
    bad_source["source_revision_ids"] = [*source_ids, "synthetic-unselected-revision"]
    try:
        parse_response(json.dumps(bad_source, ensure_ascii=False), task=example["task"],
            allowed_sources=source_ids, allowed_regions=region_ids,
            allowed_methods=example.get("method_revision_ids", []),
            attempt_legibility=example.get("attempt_legibility"))
    except InvalidProposal as exc:
        require(str(exc) == "response_unknown_source", f"{example['case_id']}: unexpected source rejection")
    else:
        raise ValueError(f"{example['case_id']}: parser accepted an unselected source")

    bad_shape = deepcopy(probe)
    bad_shape["proposal"]["baseline_unapproved_field"] = "must be rejected"
    try:
        parse_response(json.dumps(bad_shape, ensure_ascii=False), task=example["task"],
            allowed_sources=source_ids, allowed_regions=region_ids,
            allowed_methods=example.get("method_revision_ids", []),
            attempt_legibility=example.get("attempt_legibility"))
    except InvalidProposal as exc:
        require(str(exc) == "response_schema_invalid", f"{example['case_id']}: unexpected schema rejection")
    else:
        raise ValueError(f"{example['case_id']}: parser accepted an unapproved proposal field")

    if example["task"] == "variant":
        method_ids = example["method_revision_ids"]
        non_methods = [source for source in source_ids if source not in method_ids]
        require(non_methods, f"{example['case_id']}: variant needs a non-method rejection probe")
        bad_method = deepcopy(probe)
        bad_method["proposal"]["target_method_revision_id"] = non_methods[0]
        try:
            parse_response(json.dumps(bad_method, ensure_ascii=False), task="variant",
                allowed_sources=source_ids, allowed_regions=region_ids, allowed_methods=method_ids)
        except InvalidProposal as exc:
            require(str(exc) == "response_unknown_source", f"{example['case_id']}: unexpected method rejection")
        else:
            raise ValueError(f"{example['case_id']}: parser accepted a question as a target method")


def validate_fixtures():
    splits = {name: load_split(name) for name in ("development", "holdout")}
    split_ids = {name: {"case_id": set(), "source_page_id": set(), "source_revision_id": set()}
        for name in ("development", "holdout")}
    split_pages = {}
    records = {}
    all_tags = set()
    task_counts = {}
    unknown_annotations = 0
    probe_count = 0
    rejected_probes = 0

    for split, fixture in splits.items():
        examples = fixture["examples"]
        cases, pages, revisions = set(), set(), set()
        counts = {task: 0 for task in sorted(TASKS)}
        for example in examples:
            record = validate_example(example, split)
            require(record["case_id"] not in cases, f"{split}: duplicate case id")
            require(record["source_page_id"] not in pages, f"{split}: duplicate source page id")
            example_revisions = set(example["source_revision_ids"])
            require(not (example_revisions & revisions), f"{split}: source revisions are reused across cases")
            cases.add(record["case_id"])
            pages.add(record["source_page_id"])
            task = record["task"]
            counts[task] += 1
            all_tags.update(example["case_tags"])
            unknown_annotations += len(example["source_unknowns"])
            probe_count += 1
            rejected_probes += 2
            revisions.update(example_revisions)
            records[record["case_id"]] = record
        require(set(counts) == TASKS and all(counts.values()), f"{split}: task coverage incomplete")
        split_ids[split]["case_id"] = cases
        split_ids[split]["source_page_id"] = pages
        split_ids[split]["source_revision_id"] = revisions
        split_pages[split] = pages
        task_counts[split] = counts

    require(REQUIRED_TAGS <= all_tags, "fixture coverage lacks a required uncertainty scenario")
    dev_pages, test_pages = split_pages["development"], split_pages["holdout"]
    page_overlap = sorted(dev_pages & test_pages)
    require(not page_overlap, "development and holdout source pages overlap")
    case_overlap = sorted(split_ids["development"]["case_id"] & split_ids["holdout"]["case_id"])
    revision_overlap = sorted(split_ids["development"]["source_revision_id"]
        & split_ids["holdout"]["source_revision_id"])
    require(not case_overlap, "development and holdout case ids overlap")
    require(not revision_overlap, "development and holdout source revisions overlap")

    return {"splits": {name: {"case_count": len(splits[name]["examples"]),
            "case_ids": sorted(record["case_id"] for record in records.values()
                if record["split"] == name), "source_page_ids": sorted(split_pages[name]),
            "task_counts": task_counts[name]}
            for name in splits},
        "partition": {"source_page_overlap": page_overlap, "case_id_overlap": case_overlap,
            "source_revision_overlap": revision_overlap, "disjoint": True},
        "required_scenario_tags_present": sorted(REQUIRED_TAGS),
        "task_coverage": sorted(TASKS),
        "contract_probe_count": probe_count,
        "negative_contract_probe_count": rejected_probes,
        "fixture_unknown_annotation_count": unknown_annotations,
        "case_results": [records[key] for key in sorted(records)]}


def write_report(report):
    base = ROOT / "artifacts" / "model-baseline"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    output = base / uuid.uuid4().hex
    output.mkdir(mode=0o700)
    report_path = output / "verification.local.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.chmod(report_path, 0o600)
    return report_path


def main():
    details = validate_fixtures()
    report = {
        "report_schema_version": "study-workbench.ai-baseline-verification.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "offline_fixture_and_schema_checks": "passed",
        "provider_requests": 0,
        "real_model_tested": False,
        "model_accuracy_claimed": False,
        "mock_or_contract_probes_count_as_accuracy": False,
        "cost_usd": None,
        "cost_and_quality_validation": "deferred_to_manual_owner_run",
        **details,
    }
    report_path = write_report(report)
    print(json.dumps({"result": "passed", "report": str(report_path),
        "provider_requests": 0, "real_model_tested": False,
        "contract_probe_count": report["contract_probe_count"],
        "disjoint_holdout": report["partition"]["disjoint"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
