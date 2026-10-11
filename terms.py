"""Detect terms and flag potential issues when an exact definition is not found."""

import re

TERM_NAME = r"[A-Za-z][A-Za-z\s’'\-]{0,99}"
DEFINITION = re.compile(
    rf'(?:"(?P<straight>{TERM_NAME})"|“(?P<curly>{TERM_NAME})”)'
    r"\s+(?:means|shall\s+mean)\b(?=\s+[A-Za-z0-9(])",
    re.IGNORECASE,
)
CAPITALIZED_WORD = r"[A-Z][A-Za-z]*(?:[-’'][A-Za-z]+)*"
CANDIDATE_USE = re.compile(
    rf"(?<![\w’'\-]){CAPITALIZED_WORD}(?:[ \t]+{CAPITALIZED_WORD}){{1,5}}(?![\w’'\-])"
)
# Remove common sentence prefixes: "The Closing Date" becomes "Closing Date".
SENTENCE_PREFIXES = {
    "a", "an", "the", "this", "that", "these", "those", "each", "any", "such",
    "if", "when", "unless", "under", "see", "pursuant", "as", "for", "on",
    "in", "at", "by", "and", "or", "to", "from", "please",
}


def short_excerpt(text, start, end):
    """Keep the matching text and nearby context, joining PDF line breaks."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    excerpt_start = max(line_start, start - 40)
    excerpt_end = min(line_end, end + 80)
    excerpt = " ".join(text[excerpt_start:excerpt_end].split())
    return ("…" if excerpt_start > line_start else "") + excerpt + ("…" if excerpt_end < line_end else "")


def detect_terms(pages):
    """Return every definition and capitalized multi-word candidate occurrence.

    Definition labels are excluded from candidate uses. Uses inside a definition's
    body may still refer to another term. No undefined-term validation is performed.
    """
    defined_terms = []
    candidate_term_uses = []

    for page in pages:
        text = page["text"]
        definition_spans = []
        for match in DEFINITION.finditer(text):
            term = " ".join((match["straight"] or match["curly"]).split())
            defined_terms.append({
                "term": term,
                "page": page["number"],
                "excerpt": short_excerpt(text, match.start(), match.end()),
            })
            definition_spans.append((match.start(), match.end()))

        for match in CANDIDATE_USE.finditer(text):
            if any(start < match.end() and match.start() < end for start, end in definition_spans):
                continue
            words = list(re.finditer(CAPITALIZED_WORD, match.group()))
            while words and words[0].group().lower() in SENTENCE_PREFIXES:
                words.pop(0)
            if len(words) < 2:
                continue
            start = match.start() + words[0].start()
            candidate_term_uses.append({
                "term": " ".join(word.group() for word in words),
                "page": page["number"],
                "excerpt": short_excerpt(text, start, match.end()),
            })

    return {"defined_terms": defined_terms, "candidate_term_uses": candidate_term_uses}


def normalize_term_name(term):
    """Remove surrounding quotes and extra whitespace, preserving case and words."""
    term = term.strip()
    if len(term) >= 2 and (term[0], term[-1]) in {('"', '"'), ("“", "”")}:
        term = term[1:-1].strip()
    return " ".join(term.split())


def is_numbered_section_reference(candidate, references):
    """Ignore phrases such as 'Refer To Section' immediately before a number."""
    words = normalize_term_name(candidate["term"]).split()
    if not words or words[-1].lower() not in {"section", "sections"}:
        return False
    pattern = r"\b" + r"\s+".join(re.escape(word) for word in words) + r"\s+\d"
    if re.search(pattern, candidate["excerpt"]):
        return True
    # A number may wrap onto the next line, outside the candidate's excerpt.
    # Use the existing reference detector's page and original context to confirm it.
    for reference in references:
        if reference["page"] == candidate["page"] and re.match(
            re.escape(candidate["excerpt"]) + r"\s+\d", reference["excerpt"]
        ):
            return True
    return False


def validate_terms(defined_terms, candidate_term_uses, sections=(), references=()):
    """Compare complete names after all pages have been read; retain every use.

    A missing detected definition is only a potential issue. Recognized heading
    occurrences are ignored using their page, term, and original excerpt together.
    """
    if not defined_terms:
        return {
            "potentially_undefined_terms": [],
            "term_validation_warning": (
                "No explicit term definitions were detected. Term validation is unreliable, "
                "so potential undefined-term issues could not be determined."
            ),
        }

    defined_names = {normalize_term_name(item["term"]) for item in defined_terms}
    # Detect candidates in each known heading to identify its exact occurrences.
    # This also handles long headings whose candidate excerpts are truncated.
    heading_uses = set()
    for section in sections:
        heading_terms = detect_terms([{"number": section["page"], "text": section["text"]}])
        for candidate in heading_terms["candidate_term_uses"]:
            heading_uses.add((candidate["term"], candidate["page"], candidate["excerpt"]))

    findings = []
    for candidate in candidate_term_uses:
        occurrence = (candidate["term"], candidate["page"], candidate["excerpt"])
        if occurrence in heading_uses or is_numbered_section_reference(candidate, references):
            continue
        term = normalize_term_name(candidate["term"])
        if term not in defined_names:
            findings.append({
                **candidate,
                "term": term,
                "status": "Definition not found",
                "explanation": "Potential issue: no matching definition was detected. A definition may have been missed.",
            })

    return {"potentially_undefined_terms": findings, "term_validation_warning": None}
