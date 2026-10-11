/* Browser-memory review state. No storage, network requests, or automatic decisions. */
(function (root) {
  "use strict";

  function ruleFindings(document) {
    return [
      ...document.broken_references.map(reference => ({
        category: "Potential broken reference",
        title: `Section ${reference.number} was not found`,
        explanation: reference.explanation,
        evidence: [{quote: reference.excerpt, page: reference.page, verificationStatus: "not_applicable"}],
        verificationStatus: "not_applicable",
      })),
      ...document.potentially_undefined_terms.map(term => ({
        category: "Potentially undefined term",
        title: `Definition not found for ${term.term}`,
        explanation: term.explanation,
        evidence: [{quote: term.excerpt, page: term.page, verificationStatus: "not_applicable"}],
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

  const api = {createReview, ruleFindings, aiFindings, canAccept, findQuoteMatches};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReviewDashboard = api;
})(typeof window !== "undefined" ? window : globalThis);
