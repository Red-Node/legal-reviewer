"""Simple, deterministic rules for numbered headings and explicit references."""

import re

# Bare headings need a dotted number. Explicit "Section" headings may use integers.
NUMBER = r"[1-9]\d*(?:\.\d+)*"
DOTTED_NUMBER = r"[1-9]\d*(?:\.\d+)+"
HEADING = re.compile(
    rf"^\s*(?:Section\s+(?P<labeled>{NUMBER})|(?P<bare>{DOTTED_NUMBER}))"
    r"(?:\s*[:—–-]\s*|\s+)(?P<title>\S.*?)\s*$",
    re.IGNORECASE,
)

# Do not extract part of an identifier such as 3.1(a), 3.1b, or a numeric range.
REFERENCE_NUMBER = rf"{NUMBER}(?![\w%]|\.\d|\(|\s*[-–—]\s*\d)"
LIST_SEPARATOR = r"(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or|&)\s+)"
REFERENCE = re.compile(
    rf"\b(?:Sections\s+(?P<group>{REFERENCE_NUMBER}(?:{LIST_SEPARATOR}{REFERENCE_NUMBER})*)"
    rf"|Section\s+(?P<single>{REFERENCE_NUMBER}))",
    re.IGNORECASE,
)
TITLE_CONNECTORS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "under", "between"}
QUANTITY_WORDS = {"usd", "eur", "gbp", "thb", "dollars", "percent", "percentage", "million", "billion", "days", "months", "years", "kg", "km"}


def is_heading_title(title):
    """Prefer short title-style text, rather than sentences or decimal amounts."""
    if len(title) > 100 or not re.fullmatch(r"[A-Za-z][A-Za-z &'’(),/\-]*", title):
        return False
    words = re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", title)
    if not words or len(words) > 12 or words[0].lower() in QUANTITY_WORDS:
        return False
    return words[0][0].isupper() and all(
        word[0].isupper() or word.lower() in TITLE_CONNECTORS for word in words
    )


def reference_excerpt(text, start, end, reference_start):
    """Keep a short piece of the original page around a reference number."""
    # Use the line containing the label, including wrapped reference numbers.
    line_start = text.rfind("\n", 0, reference_start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    excerpt_start = max(line_start, start - 60)
    excerpt_end = min(line_end, end + 60)
    excerpt = " ".join(text[excerpt_start:excerpt_end].split())
    return ("…" if excerpt_start > line_start else "") + excerpt + ("…" if excerpt_end < line_end else "")


def detect_sections_and_references(pages):
    """Return separate lists with section numbers, matching text, and PDF pages.

    Each reference target is a separate result, including targets in plural lists.
    Repeated occurrences are kept. No check is made that a target exists.
    """
    sections = []
    references = []

    for page in pages:
        text = page["text"]
        heading_spans = []
        offset = 0
        for line in text.splitlines(keepends=True):
            match = HEADING.fullmatch(line.strip())
            if match and is_heading_title(match["title"]):
                number = match["labeled"] or match["bare"]
                # A date-like bare number should not become a section heading.
                date_like = re.fullmatch(r"(?:19|20)\d{2}\.\d{1,2}\.\d{1,2}", number)
                if match["labeled"] or not date_like:
                    sections.append({
                        "number": number,
                        "title": match["title"],
                        "text": line.strip(),
                        "page": page["number"],
                    })
                    leading_space = len(line) - len(line.lstrip())
                    heading_spans.append((offset + leading_space, offset + leading_space + match.start("title")))
            offset += len(line)

        for match in REFERENCE.finditer(text):
            # The "Section 2.1" label of an actual heading is not a reference.
            if any(start <= match.start() < end for start, end in heading_spans):
                continue
            group = "single" if match["single"] else "group"
            for number_match in re.finditer(NUMBER, match[group]):
                start = match.start(group) + number_match.start()
                end = match.start(group) + number_match.end()
                references.append({
                    "number": number_match.group(),
                    "text": match.group(),
                    "page": page["number"],
                    "excerpt": reference_excerpt(text, start, end, match.start()),
                })

    return {"sections": sections, "references": references}


def validate_references(sections, references):
    """Compare exact number strings against headings from the whole document.

    Missing targets are potential errors because heading detection can miss text.
    Keep every occurrence, including repeated references on the same page.
    """
    if not sections:
        return {
            "broken_references": [],
            "validation_warning": (
                "No section headings were detected. Reference validation is unreliable, "
                "so potential broken references could not be determined."
            ),
        }

    section_numbers = {section["number"] for section in sections}
    broken_references = []
    for reference in references:
        # Strings preserve exact identifiers: "2.1" differs from "2.10" and "2".
        if reference["number"] not in section_numbers:
            broken_references.append({
                **reference,
                "excerpt": reference.get("excerpt", reference["text"]),
                "status": "Not found",
                "explanation": (
                    f"No heading numbered {reference['number']} was detected in this document. "
                    "The heading may have been missed; this is a potential error."
                ),
            })

    return {"broken_references": broken_references, "validation_warning": None}
