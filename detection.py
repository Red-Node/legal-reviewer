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
            numbers = match["single"] or match["group"]
            for number in re.findall(NUMBER, numbers):
                references.append({
                    "number": number,
                    "text": match.group(),
                    "page": page["number"],
                })

    return {"sections": sections, "references": references}
