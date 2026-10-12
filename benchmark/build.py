"""Build and independently validate the fictional benchmark, with no AI calls.

Run from the repository root: python benchmark/build.py [--validate-only]
Uses only Python's standard library and the existing PyMuPDF dependency.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

import pymupdf


DIRECTORY = Path(__file__).resolve().parent
SOURCE = DIRECTORY / "contract_source.json"
PDF = DIRECTORY / "fictional_services_agreement.pdf"
KEY = DIRECTORY / "answer_key.json"
CATEGORY_TOTALS = {"broken_reference": 6, "undefined_term": 5, "contradiction": 5, "ambiguity": 4}
HEADING = re.compile(r"^Section ([1-9]\d*(?:\.\d+)*) ([A-Za-z][^\n]*)$", re.MULTILINE)
DEFINITION = re.compile(r'(?:"([^"]+)"|“([^”]+)”)\s+(?:means|shall\s+mean)\b', re.IGNORECASE)
REFERENCE = re.compile(r"\bSection ([1-9]\d*(?:\.\d+)*)(?!\w|\.\d|\()")


def normalize(text):
    return " ".join(text.split())


def extract(pdf_path):
    with pymupdf.open(pdf_path) as pdf:
        if not pdf.is_pdf or not 5 <= len(pdf) <= 8:
            raise ValueError("Benchmark must be a PDF of 5-8 pages.")
        pages = [page.get_text("text", sort=True) for page in pdf]
    if not all(page.strip() for page in pages):
        raise ValueError("Every benchmark page must have extractable text.")
    return pages


def sections_from_pdf(pages):
    sections = {}
    for number, text in enumerate(pages, 1):
        matches = list(HEADING.finditer(text))
        for index, match in enumerate(matches):
            if match[1] in sections:
                raise ValueError("Duplicate section heading.")
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[match[1]] = {"page": number, "text": text[match.end():end]}
    return sections


def write_pdf(source, output):
    """Simple one-column contract layout with deliberate page breaks and selectable text."""
    with pymupdf.open() as document:
        total = len(source["pages"])
        for index, part in enumerate(source["pages"], 1):
            page = document.new_page(width=595.28, height=841.89)
            page.insert_text((52, 43), "Commercial services agreement", fontname="hebo", fontsize=18)
            page.insert_text((52, 62), part["subtitle"], fontsize=10, color=(0.3, 0.35, 0.4))
            y = 85
            for section in part["sections"]:
                page.insert_text((52, y), f'Section {section["number"]} {section["title"]}',
                                 fontname="hebo", fontsize=11)
                y += 8
                for paragraph in section["paragraphs"]:
                    rectangle = pymupdf.Rect(52, y, 543, 786)
                    remaining = page.insert_textbox(rectangle, paragraph, fontsize=10.5,
                                                    lineheight=1.2, align=pymupdf.TEXT_ALIGN_LEFT)
                    if remaining < 0:
                        raise ValueError(f'Page {index}, section {section["number"]} overflowed. Shorten text or change layout.')
                    y += rectangle.height - remaining + 4
                y += 7
            if y > 786:
                raise ValueError(f"Page {index} content reaches the footer.")
            page.draw_line((52, 799), (543, 799), color=(0.75, 0.78, 0.8), width=0.5)
            page.insert_text((52, 816), f"Fictional benchmark - sample only     |     Page {index} of {total}", fontsize=9)
        document.set_metadata({"title": "Fictional commercial services agreement", "author": "Legal Reviewer benchmark",
                               "subject": "Entirely fictional synthetic quality-control benchmark"})
        document.save(output, deflate=True, garbage=4, no_new_id=True)


def build(source_path=SOURCE, pdf_path=PDF, key_path=KEY):
    source = json.loads(Path(source_path).read_text())
    write_pdf(source, str(pdf_path))
    pages = extract(pdf_path)
    sections = sections_from_pdf(pages)
    issues = deepcopy(source["issues"])
    # Derive page locations from the PDF we actually wrote, never from layout estimates.
    for issue in issues:
        for evidence in issue["evidence"]:
            location = sections.get(evidence["section"])
            if location is None or normalize(evidence["quote"]) not in normalize(location["text"]):
                raise ValueError(f'{issue["id"]}: expected quote missing from its extracted section.')
            page = location["page"]
            if normalize(pages[page - 1]).count(normalize(evidence["quote"])) != 1:
                raise ValueError(f'{issue["id"]}: evidence does not identify one occurrence on its page.')
            evidence["page"] = page
    key = {"benchmark": source["name"], "version": 1, "pdf_filename": Path(pdf_path).name,
           "pdf_sha256": hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(),
           "page_count": len(pages), "category_totals": CATEGORY_TOTALS, "issues": issues}
    Path(key_path).write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n")
    return validate(pdf_path, key_path)


def validate(pdf_path=PDF, key_path=KEY):
    """Independent ground-truth checks, deliberately not an application detection score."""
    key = json.loads(Path(key_path).read_text())
    pages = extract(pdf_path)
    if key["pdf_sha256"] != hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest():
        raise ValueError("Answer key fingerprint does not match this PDF.")
    if key["page_count"] != len(pages):
        raise ValueError("Answer key page count does not match the PDF.")
    issues = key["issues"]
    ids = [issue["id"] for issue in issues]
    if len(ids) != 20 or any(not identifier for identifier in ids) or len(set(ids)) != 20:
        raise ValueError("Expected exactly 20 unique, nonempty issue IDs.")
    if dict(Counter(issue["category"] for issue in issues)) != CATEGORY_TOTALS or key["category_totals"] != CATEGORY_TOTALS:
        raise ValueError("Wrong category totals; expected 6/5/5/4.")
    sections = sections_from_pdf(pages)
    document_text = "\n".join(pages)
    definitions = {normalize(match[1] or match[2]) for match in DEFINITION.finditer(document_text)}
    broken = set()
    for text in pages:
        # Actual numbered headings are not cross-references.
        body = HEADING.sub("", text)
        broken.update(match[1] for match in REFERENCE.finditer(body) if match[1] not in sections)
    targets = set()
    undefined = set()
    for issue in issues:
        if not issue["description"].strip() or not issue["explanation"].strip():
            raise ValueError("Every issue needs a description and grading explanation.")
        evidence = issue["evidence"]
        if not evidence or (issue["category"] == "contradiction" and len(evidence) < 2):
            raise ValueError("Missing supporting evidence.")
        if set(issue["sections"]) != {item["section"] for item in evidence}:
            raise ValueError("Relevant sections do not match supporting evidence.")
        for item in evidence:
            page = item["page"]
            if type(page) is not int or not 1 <= page <= len(pages) or not item["quote"].strip():
                raise ValueError("Invalid evidence page or empty quotation.")
            if normalize(item["quote"]) not in normalize(pages[page - 1]):
                raise ValueError(f'{issue["id"]}: quote absent from its claimed page.')
            section = sections.get(item["section"])
            if section is None or section["page"] != page or normalize(item["quote"]) not in normalize(section["text"]):
                raise ValueError(f'{issue["id"]}: quotation not in its claimed section.')
        if issue["category"] == "broken_reference":
            target = issue["target_section"]
            if target in sections or not any(target == match[1] for item in evidence for match in REFERENCE.finditer(item["quote"])):
                raise ValueError("Broken target exists, or is not supported by its quotation.")
            targets.add(target)
        elif issue["category"] == "undefined_term":
            term = issue["term"]
            if term in definitions or not any(term in normalize(item["quote"]) for item in evidence):
                raise ValueError("Intentionally undefined term has a definition, or lacks a source use.")
            undefined.add(term)
    if len(targets) != 6 or targets != broken:
        raise ValueError("Broken targets do not match the six distinct missing PDF references.")
    if len(undefined) != 5:
        raise ValueError("Expected five distinct terms lacking exact explicit definitions.")
    return {"pages": len(pages), "issues": len(issues), "category_totals": CATEGORY_TOTALS}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    arguments = parser.parse_args()
    result = validate() if arguments.validate_only else build()
    print(json.dumps(result, indent=2))
