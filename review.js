/* Browser-memory review state. No storage, network requests, or automatic decisions. */
(function (root) {
  "use strict";

  function ruleLocation(item) {
    return item.location_id ? {locationId: item.location_id, locationLabel: item.location_label} : {page: item.page};
  }

  function ruleFindings(document) {
    return [
      ...document.broken_references.map(reference => ({
        category: "Potential broken reference",
        title: `Section ${reference.number} was not found`,
        explanation: reference.explanation,
        evidence: [{quote: reference.excerpt, referenceText: reference.text, referenceNumber: reference.number,
          displayExcerpt: true, ...ruleLocation(reference), verificationStatus: "not_applicable"}],
        verificationStatus: "not_applicable",
      })),
      ...document.potentially_undefined_terms.map(term => ({
        category: "Potentially undefined term",
        title: `Definition not found for ${term.term}`,
        explanation: term.explanation,
        evidence: [{quote: term.excerpt, displayExcerpt: true, ...ruleLocation(term), verificationStatus: "not_applicable"}],
        verificationStatus: "not_applicable",
      })),
    ];
  }

  function aiFindings(findings) {
    return findings.map(finding => ({
      category: finding.category,
      title: finding.title,
      explanation: finding.explanation,
      verificationStatus: finding.status,
      evidence: finding.evidence.map(item => ({
        quote: item.quote, page: item.page,
        verificationStatus: item.verification_status,
        failureReason: item.failure_reason || null,
      })),
    }));
  }

  function canAccept(finding) {
    if (finding.verificationStatus === "verification_failed" ||
        finding.evidence.some(item => item.verificationStatus === "verification_failed")) return false;
    if (finding.source === "rules") return true;
    const minimum = finding.category === "contradiction" ? 2 : 1;
    return finding.verificationStatus === "verified" && finding.evidence.length >= minimum &&
      finding.evidence.every(item => item.verificationStatus === "verified");
  }

  // Collapse only whitespace, keeping an offset back to every original character.
  // This is the same whitespace and whole-word matching used by quote_verifier.py.
  function findQuoteMatches(text, quote) {
    const whitespace = /[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
    function normalize(value) {
      let normalized = "";
      const starts = [], ends = [];
      for (let i = 0; i < value.length;) {
        const start = i;
        if (whitespace.test(value[i])) {
          while (i < value.length && whitespace.test(value[i])) i++;
          if (!normalized || i === value.length) continue;
          normalized += " "; starts.push(start); ends.push(i);
        } else {
          normalized += value[i]; starts.push(i); ends.push(++i);
        }
      }
      return {normalized, starts, ends};
    }
    const source = normalize(text), target = normalize(quote).normalized;
    if (!target) return [];
    const word = /[\p{L}\p{N}_]/u;
    const letters = [...target];
    const escaped = target.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = (word.test(letters[0]) ? "(?<![\\p{L}\\p{N}_])" : "") + escaped +
      (word.test(letters[letters.length - 1]) ? "(?![\\p{L}\\p{N}_])" : "");
    return [...source.normalized.matchAll(new RegExp(`(?=${pattern})`, "gu"))].map(match => ({
      start: source.starts[match.index], end: source.ends[match.index + target.length - 1],
    }));
  }

  // Navigation only. AI quotes always retain exact matching; this never verifies evidence.
  function findEvidenceMatches(text, evidence, source) {
    const exact = findQuoteMatches(text, evidence.quote);
    if (source !== "rules" || !evidence.displayExcerpt) return exact;

    // The detectors add edge ellipses after slicing a display excerpt, sometimes
    // through a word. Drop those partial edge words, never alter interior text.
    let context = evidence.quote.trim();
    const leading = /^(?:…|\.{3})/.test(context);
    const trailing = /(?:…|\.{3})$/.test(context);
    if (leading) context = context.replace(/^(?:…|\.{3})\s*\S*\s*/, "");
    if (trailing) context = context.replace(/\s*\S*?(?:…|\.{3})$/, "");
    const distinctive = context.length >= 40 && context.split(/\s+/).length >= 6;
    const contexts = exact.length ? exact : (distinctive ? findQuoteMatches(text, context) : []);

    // Original detector reference text + target identifier, not a guessed phrase
    // extracted from the finding title. Return every plausible source occurrence.
    if (typeof evidence.referenceText === "string" &&
        /^[1-9]\d*(?:\.\d+)*$/.test(evidence.referenceNumber || "")) {
      const references = findQuoteMatches(text, evidence.referenceText).filter(match =>
        !/^(?:\.\d|[\p{L}\p{N}_]|\()/u.test(text.slice(match.end)));
      const contextual = references.filter(reference => contexts.some(context =>
        reference.start >= context.start && reference.end <= context.end));
      return contextual.length ? contextual : references;
    }
    return contexts;
  }

  function buildCounselLetter(findings, pages = []) {
    const accepted = findings.filter(finding => finding && finding.decision === "accepted");
    const eligible = accepted.filter(finding => {
      if (typeof finding.title !== "string" || typeof finding.explanation !== "string" ||
          !finding.title.trim() || !finding.explanation.trim() || !Array.isArray(finding.evidence) ||
          !finding.evidence.length) return false;
      const validEvidence = finding.evidence.every(item => item && typeof item.quote === "string" &&
        item.quote.trim() && (
          (Number.isInteger(item.page) && item.page > 0 && !item.locationId) ||
          (finding.source === "rules" && typeof item.locationId === "string" && !Object.hasOwn(item, "page") &&
            pages.some(source => source.location_id === item.locationId && source.location_label === item.locationLabel))));
      if (!validEvidence) return false;
      if (finding.source === "rules") return ["Potential broken reference", "Potentially undefined term"].includes(finding.category) &&
        finding.verificationStatus === "not_applicable" &&
        finding.evidence.every(item => item.verificationStatus === "not_applicable");
      if (!["demo", "real"].includes(finding.source) ||
          !["contradiction", "ambiguity"].includes(finding.category) || !canAccept(finding)) return false;
      // Recheck original text, so a manipulated acceptance decision cannot bypass evidence checks.
      return finding.evidence.every(item => {
        const page = pages.find(page => page && page.number === item.page);
        return !item.failureReason && page && typeof page.text === "string" &&
          findQuoteMatches(page.text, item.quote).length > 0;
      });
    });
    if (!eligible.length) return {text: "", count: 0, excludedCount: accepted.length};
    // Presentation only: explanations and source evidence remain separate in review state.
    // Choose neutral questions by category without inferring new contract details.
    const clarificationQuestions = {
      contradiction: "Could you please clarify how these provisions are intended to apply together?",
      ambiguity: "Could you please clarify the intended meaning or obligation?",
      "Potential broken reference": "Could you please confirm the intended section reference?",
      "Potentially undefined term": "Could you please clarify the intended meaning of this term and where it is defined?",
    };
    const questions = eligible.map((finding, index) => {
      const evidence = finding.evidence.map(item => `   “${item.quote}” (${item.locationId ? item.locationLabel : `Page ${item.page}`})`).join("\n");
      return `${index + 1}. ${finding.title}\n   ${finding.explanation}\n${evidence}\n` +
        `   ${clarificationQuestions[finding.category]}`;
    });
    return {count: eligible.length, excludedCount: accepted.length - eligible.length, text:
      "Subject: Questions Regarding Draft Agreement\n\nDear Counsel,\n\n" +
      "Following our preliminary review of the draft agreement, we would appreciate your clarification on the following points.\n\n" +
      questions.join("\n\n") + "\n\nThank you for your assistance.\n\nBest regards,\nDocument Review Team"};
  }

  function createCounselDraft() {
    let text = "", snapshot = null, outdated = false;
    return {
      clear() { text = ""; snapshot = null; outdated = false; },
      check(findings) {
        if (snapshot !== null && snapshot !== JSON.stringify(findings)) outdated = true;
      },
      generate(findings, pages) {
        this.check(findings);
        const result = buildCounselLetter(findings, pages);
        if (result.count) {
          text = result.text; snapshot = JSON.stringify(findings); outdated = false;
        }
        return result;
      },
      edit(value) { text = value; },
      state: () => ({text, exists: snapshot !== null, outdated}),
    };
  }

  function createReview() {
    let generation = 0;
    let nextId = 1;
    let findings = [];
    const copy = value => JSON.parse(JSON.stringify(value));
    const key = finding => JSON.stringify([
      finding.category, finding.originalTitle ?? finding.title,
      finding.originalExplanation ?? finding.explanation, finding.verificationStatus, finding.evidence,
    ]);

    return {
      token: () => generation,
      reset() {
        generation += 1;
        nextId = 1;
        findings = [];
      },
      replaceSource(source, candidates, token) {
        if (token !== generation) return false; // Ignore responses from an older document.
        if (!["rules", "demo", "real"].includes(source)) throw new Error("Unknown review source.");
        const previous = new Map();
        for (const finding of findings.filter(item => item.source === source)) {
          const signature = key(finding);
          if (!previous.has(signature)) previous.set(signature, []);
          previous.get(signature).push(finding);
        }
        const updated = candidates.map(candidate => {
          const same = previous.get(key(candidate));
          if (same && same.length) return same.shift();
          return {...copy(candidate), originalTitle: candidate.title, originalExplanation: candidate.explanation,
            source, id: `review-${generation}-${nextId++}`, decision: "pending"};
        });
        findings = [...findings.filter(item => item.source !== source), ...updated];
        return true;
      },
      decide(id, decision) {
        if (!["pending", "accepted", "rejected"].includes(decision)) throw new Error("Unknown human decision.");
        const finding = findings.find(item => item.id === id);
        if (!finding || (decision === "accepted" && !canAccept(finding))) return false;
        finding.decision = decision;
        return true;
      },
      edit(id, title, explanation) {
        const finding = findings.find(item => item.id === id);
        if (!finding || typeof title !== "string" || typeof explanation !== "string" ||
            !title.trim() || !explanation.trim()) return false;
        // Only wording can change. IDs, source evidence, and verification stay intact.
        finding.title = title.trim();
        finding.explanation = explanation.trim();
        if (finding.decision === "accepted") finding.decision = "pending";
        return true;
      },
      findings: () => copy(findings),
      counts() {
        return {
          total: findings.length,
          pending: findings.filter(item => item.decision === "pending").length,
          accepted: findings.filter(item => item.decision === "accepted").length,
          rejected: findings.filter(item => item.decision === "rejected").length,
        };
      },
    };
  }

  const api = {createReview, ruleFindings, aiFindings, canAccept, findQuoteMatches, findEvidenceMatches, buildCounselLetter, createCounselDraft};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReviewDashboard = api;
})(typeof window !== "undefined" ? window : globalThis);
