"""Offline issue-level baseline using the unchanged production PDF analysis function.

Run from the repository root: python -m benchmark.evaluate
No AI calls, synthetic mock findings, network requests, or detector improvements.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re

from fastapi import UploadFile
import pymupdf

from main import analyze_document
from terms import normalize_term_name
from benchmark.build import DIRECTORY, HEADING, KEY, PDF, normalize, validate


ROOT = DIRECTORY.parent
RULE_CATEGORIES = ("broken_reference", "undefined_term")
AI_CATEGORIES = ("contradiction", "ambiguity")
RESULTS = DIRECTORY / "results"
REPORT_STEM = "rule_based_baseline"


def production_predictions(pdf_path):
    """Call the actual application function, including sorted PDF extraction and checks."""
    with Path(pdf_path).open("rb") as stream:
        analysis = analyze_document(UploadFile(file=stream, filename=Path(pdf_path).name))
    predictions = []
    for category, field in [("broken_reference", "broken_references"), ("undefined_term", "potentially_undefined_terms")]:
        for raw in analysis[field]:
            predictions.append({"id": f"P{len(predictions) + 1:03}", "category": category,
                                "identity": raw["number"] if category == "broken_reference" else normalize_term_name(raw["term"]),
                                "page": raw["page"], "excerpt": raw["excerpt"], "raw": raw})
    return predictions, analysis


def section_blocks(pages):
    """Independent grading locations; do not use detected headings as ground truth."""
    blocks = []
    for page in pages:
        headings = list(HEADING.finditer(page["text"]))
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(page["text"])
            blocks.append({"section": heading[1], "page": page["number"],
                           "text": normalize(page["text"][heading.end():end])})
    return blocks


def literal_occurrences(text, value):
    if not value:
        return []
    return [match.start() for match in re.finditer("(?=" + re.escape(value) + ")", text)]


def prediction_locations(prediction, blocks):
    """Locate the detector's original snippet and its exact identifier inside that snippet.

    The detector inserts ellipses at clipped edges, sometimes mid-word. Remove only
    those edge markers; preserve case, punctuation, numbers, and all remaining text.
    """
    excerpt = prediction["excerpt"].removeprefix("…").removesuffix("…")
    fragment = normalize(excerpt)
    identity = prediction["identity"]
    if prediction["category"] == "broken_reference":
        marker = re.compile(r"\bSection\s+" + re.escape(identity) + r"(?!\w|\.\d|\()", re.IGNORECASE)
    else:
        marker = re.compile(r"(?<!\w)" + re.escape(normalize_term_name(identity)) + r"(?!\w)")
    locations = []
    for block in blocks:
        if block["page"] != prediction["page"]:
            continue
        for start in literal_occurrences(block["text"], fragment):
            for match in marker.finditer(fragment):
                locations.append({"section": block["section"], "page": block["page"],
                                  "start": start + match.start(), "end": start + match.end()})
    return locations


def matching_reason(prediction, issue, locations, blocks):
    if prediction["category"] != issue["category"] or len(locations) != 1:
        return None
    identity = issue["target_section"] if issue["category"] == "broken_reference" else normalize_term_name(issue["term"])
    actual_identity = prediction["identity"] if issue["category"] == "broken_reference" else normalize_term_name(prediction["identity"])
    if identity != actual_identity:
        return None
    location = locations[0]
    for evidence in issue["evidence"]:
        if evidence["page"] != location["page"] or evidence["section"] != location["section"]:
            continue
        block = next(block for block in blocks if block["page"] == location["page"] and block["section"] == location["section"])
        quote = normalize(evidence["quote"])
        for start in literal_occurrences(block["text"], quote):
            if start <= location["start"] and location["end"] <= start + len(quote):
                return {"category": issue["category"], "exact_identity": identity,
                        "page": location["page"], "section": location["section"],
                        "expected_quote": evidence["quote"],
                        "criterion": "Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section."}
    return None


def one_to_one_assignment(candidates):
    """Deterministic maximum-cardinality assignment over evidence-supported edges only."""
    owner = {}

    def assign(prediction_index, seen):
        for issue_id in candidates[prediction_index]:
            if issue_id in seen:
                continue
            seen.add(issue_id)
            if issue_id not in owner or assign(owner[issue_id], seen):
                owner[issue_id] = prediction_index
                return True
        return False

    for index in range(len(candidates)):
        assign(index, set())
    return {prediction_index: issue_id for issue_id, prediction_index in owner.items()}


def metrics(truth_count, prediction_count, true_positives):
    return {"ground_truth_count": truth_count, "predictions_produced": prediction_count,
            "true_positives": true_positives, "false_positives": prediction_count - true_positives,
            "false_negatives": truth_count - true_positives,
            "precision": true_positives / prediction_count if prediction_count else None,
            "recall": true_positives / truth_count if truth_count else None}


def grade_predictions(predictions, issues, pages):
    if any(prediction["category"] not in RULE_CATEGORIES for prediction in predictions):
        raise ValueError("This evaluator accepts rule-based categories only; AI is not evaluated.")
    if len({p["id"] for p in predictions}) != len(predictions) or len({i["id"] for i in issues}) != len(issues):
        raise ValueError("Prediction and ground-truth IDs must be unique.")
    blocks = section_blocks(pages)
    rules = [issue for issue in issues if issue["category"] in RULE_CATEGORIES]
    locations = [prediction_locations(prediction, blocks) for prediction in predictions]
    reasons = [{issue["id"]: reason for issue in rules
                if (reason := matching_reason(prediction, issue, locations[index], blocks))}
               for index, prediction in enumerate(predictions)]
    assignment = one_to_one_assignment([list(reason) for reason in reasons])
    owners = {issue_id: predictions[index]["id"] for index, issue_id in assignment.items()}
    matched, unmatched = [], []
    for index, prediction in enumerate(predictions):
        if index in assignment:
            issue_id = assignment[index]
            matched.append({"issue_id": issue_id, "prediction": prediction, "matching_reason": reasons[index][issue_id]})
        else:
            candidates = list(reasons[index])
            if candidates:
                reason = "Additional warning for an already matched issue; counted as a false positive, not another true positive."
            elif len(locations[index]) > 1:
                reason = "Source excerpt has multiple possible mention locations; no automatic match awarded."
            elif not locations[index]:
                reason = "Exact identifier and source excerpt could not be located together on the claimed page."
            else:
                reason = "No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention."
            unmatched.append({"prediction": prediction, "source_locations": locations[index], "reason": reason,
                              "candidate_issue_ids": candidates,
                              "duplicate_of_prediction_ids": [owners[identifier] for identifier in candidates if identifier in owners]})
    categories = {}
    for category in RULE_CATEGORIES:
        count = sum(match["matching_reason"]["category"] == category for match in matched)
        categories[category] = {"status": "evaluated", **metrics(
            sum(issue["category"] == category for issue in issues),
            sum(prediction["category"] == category for prediction in predictions), count)}
    for category in AI_CATEGORIES:
        categories[category] = {"status": "not_evaluated", "ground_truth_count": sum(issue["category"] == category for issue in issues),
            "predictions_produced": None, "true_positives": None, "false_positives": None,
            "false_negatives": None, "precision": None, "recall": None,
            "reason": "Requires AI analysis; no real or mock AI run is included in this offline baseline."}
    return {"mode": "rule_based_only", "categories": categories,
            "matching_policy": {
                "identity": "Exact category and reference number or complete term; whitespace/surrounding term quotes normalized, case and plurals preserved.",
                "evidence": "Detector excerpt must uniquely locate its identifier on the claimed page; source mention must lie inside a key quote in the same section.",
                "offsets": "Source start/end offsets are relative to whitespace-normalized section body text, not PDF coordinates.",
                "duplicates": "One-to-one maximum-cardinality assignment; extra warnings for matched issues remain false positives with duplicate labels.",
                "ai": "Contradictions and ambiguities excluded from scoring, with null prediction/metric fields.",
            },
            "overall": {"scope": list(RULE_CATEGORIES), **metrics(len(rules), len(predictions), len(matched)),
                        "total_ground_truth_count": len(issues),
                        "not_evaluated_ground_truth_count": sum(issue["category"] in AI_CATEGORIES for issue in issues)},
            "matched_issues": matched, "missed_issues": [issue for issue in rules if issue["id"] not in owners],
            "unmatched_predictions": unmatched,
            "not_evaluated_issues": [issue for issue in issues if issue["category"] in AI_CATEGORIES]}


def percentage(value):
    return "N/A" if value is None else f"{value:.2%}"


def render_markdown(report):
    labels = {"broken_reference": "Broken references", "undefined_term": "Undefined terms",
              "contradiction": "Contradictions", "ambiguity": "Ambiguities"}
    lines = ["# Offline benchmark baseline", "", "Mode: **rule-based only**. No AI analysis or API requests.", "",
             "| Category | Status | Ground truth | Predictions | TP | FP | FN | Precision | Recall |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for category, result in report["categories"].items():
        numbers = [str(result[field]) if result[field] is not None else "N/A" for field in
                   ["ground_truth_count", "predictions_produced", "true_positives", "false_positives", "false_negatives"]]
        lines.append(f'| {labels[category]} | {result["status"].replace("_", " ")} | ' + " | ".join(numbers) +
                     f' | {percentage(result["precision"])} | {percentage(result["recall"])} |')
    overall = report["overall"]
    lines += ["", f'Rule-based overall: **{overall["true_positives"]} TP, {overall["false_positives"]} FP, {overall["false_negatives"]} FN**; '
              f'precision **{percentage(overall["precision"])}**, recall **{percentage(overall["recall"])}**.',
              f'Only {overall["ground_truth_count"]} rule-based issues are scored. '
              f'The {overall["not_evaluated_ground_truth_count"]} AI issues are not evaluated and are not false negatives.',
              "", "Predictions are raw warnings; one-to-one issue matching prevents duplicates adding true positives. Additional warnings for a matched issue remain false positives and are labeled as duplicates. Undefined denominators are N/A.",
              "", "## Matched issues", ""]
    for match in report["matched_issues"]:
        prediction, reason = match["prediction"], match["matching_reason"]
        lines += [f'### {match["issue_id"]} matched by {prediction["id"]}', "",
                  f'Category: {prediction["category"]}; exact identifier: {reason["exact_identity"]}; '
                  f'Page {reason["page"]}, Section {reason["section"]}.', "",
                  f'Matching reason: {reason["criterion"]}', "", "Detector excerpt:", ""]
        lines.extend(quoted_lines(prediction["excerpt"]))
        lines += ["", "Ground-truth supporting quote:", ""]
        lines.extend(quoted_lines(reason["expected_quote"]))
        lines.append("")
    if not report["matched_issues"]:
        lines += ["None.", ""]
    lines += ["## Missed rule-based issues", ""]
    for issue in report["missed_issues"]:
        lines += [f'### {issue["id"]}: {issue["description"]}', "", issue["explanation"], ""]
        for evidence in issue["evidence"]:
            lines.append(f'Page {evidence["page"]}, Section {evidence["section"]}:')
            lines.extend(quoted_lines(evidence["quote"]))
            lines.append("")
    if not report["missed_issues"]:
        lines += ["None among evaluated categories.", ""]
    lines += ["## Unmatched predictions / false positives", ""]
    for item in report["unmatched_predictions"]:
        prediction = item["prediction"]
        sections = ", ".join(dict.fromkeys(location["section"] for location in item["source_locations"])) or "unlocated"
        lines += [f'### {prediction["id"]}: {prediction["category"]} - {prediction["identity"]}', "",
                  f'Page {prediction["page"]}; source sections: {sections}. {item["reason"]}', ""]
        if item["duplicate_of_prediction_ids"]:
            lines.append("Duplicates matched predictions: " + ", ".join(item["duplicate_of_prediction_ids"]))
        lines.extend(quoted_lines(prediction["excerpt"]))
        lines.append("")
    if not report["unmatched_predictions"]:
        lines += ["None.", ""]
    lines += ["## AI issues not evaluated", ""]
    lines.extend(f'- {issue["id"]}: {issue["description"]}' for issue in report["not_evaluated_issues"])
    lines += ["", "No claim is made about detecting all planted issues. This clean synthetic contract is not representative of all legal documents. Matching is strict and may under-credit ambiguous/truncated source snippets; the full audit data is in the JSON report.", "",
              "## Reproducibility", "", "```json", json.dumps(report.get("provenance", {}), indent=2), "```", "",
              "Pipeline warnings: " + json.dumps(report.get("pipeline_warnings", {})), ""]
    return "\n".join(lines)


def quoted_lines(text):
    # Keep report content literal, even when viewed by a Markdown renderer.
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped = re.sub(r"([\\`*_{}\[\]()#+!|~])", r"\\\1", escaped)
    return ["> " + line for line in escaped.splitlines()]


def run_evaluation(pdf_path=PDF, key_path=KEY):
    validate(pdf_path, key_path)  # Reject stale or corrupt ground truth; do not regenerate it.
    key = json.loads(Path(key_path).read_text())
    predictions, analysis = production_predictions(pdf_path)
    report = grade_predictions(predictions, key["issues"], analysis["pages"])
    report["provenance"] = {"benchmark": key["benchmark"], "benchmark_version": key["version"],
        "pdf_sha256": hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
        "answer_key_sha256": hashlib.sha256(Path(key_path).read_bytes()).hexdigest(),
        "pipeline": "main.analyze_document (unchanged production function)",
        "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                        for name in ["main.py", "detection.py", "terms.py", "benchmark/build.py", "benchmark/evaluate.py"]},
        "python_version": platform.python_version(), "pymupdf_version": pymupdf.VersionBind}
    report["pipeline_warnings"] = {"references": analysis["validation_warning"], "terms": analysis["term_validation_warning"]}
    return report


def write_reports(report, directory=RESULTS):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = directory / f"{REPORT_STEM}.json", directory / f"{REPORT_STEM}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=RESULTS)
    arguments = parser.parse_args()
    evaluation = run_evaluation()
    write_reports(evaluation, arguments.output_dir)
    print(json.dumps({"mode": evaluation["mode"], "categories": evaluation["categories"],
                      "overall": evaluation["overall"]}, indent=2))
