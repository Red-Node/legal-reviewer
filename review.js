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
    if (finding.source === "rules") return true;
    const minimum = finding.category === "contradiction" ? 2 : 1;
    return finding.verificationStatus === "verified" && finding.evidence.length >= minimum &&
      finding.evidence.every(item => item.verificationStatus === "verified");
  }

  function createReview() {
    let generation = 0;
    let nextId = 1;
    let findings = [];
    const copy = value => JSON.parse(JSON.stringify(value));
    const key = finding => JSON.stringify([
      finding.category, finding.title, finding.explanation, finding.verificationStatus, finding.evidence,
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
          return {...copy(candidate), source, id: `review-${generation}-${nextId++}`, decision: "pending"};
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

  const api = {createReview, ruleFindings, aiFindings, canAccept};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReviewDashboard = api;
})(typeof window !== "undefined" ? window : globalThis);
