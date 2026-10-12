"""Offline quote-presence checks, independent of Claude and human review."""

from copy import deepcopy
import re


def _normalize_whitespace(text):
    # Only whitespace changes: preserve case, words, punctuation, and numbers.
    return " ".join(text.split())


def _count_matches(quote, page_text):
    pattern = re.escape(quote)
    # Do not accept a quoted word or number inside a longer word or number.
    if quote[0].isalnum() or quote[0] == "_":
        pattern = r"(?<!\w)" + pattern
    if quote[-1].isalnum() or quote[-1] == "_":
        pattern += r"(?!\w)"
    # Lookahead counts overlapping repetitions too; no unique location is claimed.
    return sum(1 for _ in re.finditer("(?=" + pattern + ")", page_text))


def verify_findings(analysis, pages):
    """Check original page texts and return an annotated copy of the analysis.

    Finding status describes quote presence ONLY, never a legal conclusion or
    human approval. Failures and original quotes/pages are retained. This function
    neither imports the AI client nor calls any external service.
    """
    if not isinstance(analysis, dict) or not isinstance(analysis.get("findings"), list):
        raise ValueError("Provide a structured analysis with a findings list.")
    if not isinstance(pages, list):
        raise ValueError("Provide a list of original extracted pages.")

    page_texts = {}
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("Each original page must contain a number and text.")
        number, text = page.get("number"), page.get("text")
        if type(number) is not int or number < 1 or number in page_texts:
            raise ValueError("Original page numbers must be unique positive integers.")
        if not isinstance(text, str):
            raise ValueError("Original page text must be a string.")
        page_texts[number] = _normalize_whitespace(text)

    result = deepcopy(analysis)
    for finding in result["findings"]:
        if not isinstance(finding, dict):
            raise ValueError("Each finding must be an object.")
        reasons = []
        category = finding.get("category")
        if category not in ("contradiction", "ambiguity"):
            reasons.append("Unsupported finding category.")
        evidence = finding.get("evidence")
        minimum = 2 if category == "contradiction" else 1
        if not isinstance(evidence, list) or len(evidence) < minimum:
            reasons.append(f"Finding requires at least {minimum} evidence item(s).")

        for index, item in enumerate(evidence if isinstance(evidence, list) else []):
            if not isinstance(item, dict):
                raise ValueError("Each evidence item must be an object.")
            quote, page = item.get("quote"), item.get("page")
            failure = None
            count = 0
            if not isinstance(quote, str) or not quote.strip():
                failure = "Quote is empty or is not text."
            elif type(page) is not int or page < 1:
                failure = "Claimed page number is not a positive integer."
            elif page not in page_texts:
                failure = "Claimed page was not supplied among the original pages."
            else:
                count = _count_matches(_normalize_whitespace(quote), page_texts[page])
                if count == 0:
                    failure = "Quote was not found on the claimed page after whitespace normalization."

            item["verification_status"] = "verification_failed" if failure else "verified"
            item["failure_reason"] = failure
            item["match_count"] = count
            if failure:
                reasons.append(f"Evidence {index + 1}: {failure}")

        finding["status"] = "verification_failed" if reasons else "verified"
        finding["failure_reasons"] = reasons
    return result


def verify_docx_evidence(evidence, locations):
    """Offline exact quotation checks against explicit DOCX locations, not pages.

    This supports source navigation/tests; it does not enable DOCX AI analysis or
    turn a source quotation into legal validation or a human review decision.
    """
    sources = {}
    for source in locations:
        identifier = source.get("location_id")
        if not isinstance(identifier, str) or not identifier or identifier in sources:
            raise ValueError("DOCX locations need unique nonempty identifiers.")
        if not isinstance(source.get("text"), str):
            raise ValueError("DOCX location text must be a string.")
        sources[identifier] = source
    result = deepcopy(evidence)
    for item in result:
        quote, identifier = item.get("quote"), item.get("location_id")
        failure, count = None, 0
        source = sources.get(identifier) if isinstance(identifier, str) else None
        if "page" in item:
            failure = "DOCX evidence must use a location identifier, not a page number."
        elif not isinstance(quote, str) or not quote.strip():
            failure = "Quote is empty or is not text."
        elif source is None:
            failure = "Claimed DOCX location was not supplied among the original locations."
        else:
            count = _count_matches(_normalize_whitespace(quote), _normalize_whitespace(source["text"]))
            if count == 0:
                failure = "Quote was not found at the claimed DOCX location after whitespace normalization."
        item.update(verification_status="verification_failed" if failure else "verified",
                    failure_reason=failure, match_count=count)
    return result
