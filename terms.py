"""Detect explicit definitions and candidate term uses without judging validity."""

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
