# Offline benchmark baseline

Mode: **rule-based only**. No AI analysis or API requests.

| Category | Status | Ground truth | Predictions | TP | FP | FN | Precision | Recall |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Broken references | evaluated | 6 | 6 | 6 | 0 | 0 | 100.00% | 100.00% |
| Undefined terms | evaluated | 5 | 11 | 5 | 6 | 0 | 45.45% | 100.00% |
| Contradictions | not evaluated | 5 | N/A | N/A | N/A | N/A | N/A | N/A |
| Ambiguities | not evaluated | 4 | N/A | N/A | N/A | N/A | N/A | N/A |

Rule-based overall: **11 TP, 6 FP, 0 FN**; precision **64.71%**, recall **100.00%**.
Only 11 rule-based issues are scored. The 9 AI issues are not evaluated and are not false negatives.

Predictions are raw warnings; one-to-one issue matching prevents duplicates adding true positives. Additional warnings for a matched issue remain false positives and are labeled as duplicates. Undefined denominators are N/A.

## Matched issues

### BR01 matched by P001

Category: broken_reference; exact identifier: 12.8; Page 1, Section 1.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> …e Supplier shall use the escalation route stated in Section 12.8 for a disputed Acceptance Record. Until

Ground-truth supporting quote:

> The Supplier shall use the escalation route stated in Section 12.8 for a disputed Acceptance Record.

### BR02 matched by P002

Category: broken_reference; exact identifier: 13.6; Page 2, Section 2.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> …invoice classification code shall be assigned under Section 13.6. The code shall appear beside the

Ground-truth supporting quote:

> The invoice classification code shall be assigned under Section 13.6.

### BR03 matched by P003

Category: broken_reference; exact identifier: 14.2; Page 3, Section 3.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> …ccess-register review shall follow the procedure in Section 14.2. The review entry shall identify the

Ground-truth supporting quote:

> The access-register review shall follow the procedure in Section 14.2.

### BR04 matched by P004

Category: broken_reference; exact identifier: 15.4; Page 4, Section 4.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The change-request review sequence is set out in Section 15.4. Every proposed change shall state the

Ground-truth supporting quote:

> The change-request review sequence is set out in Section 15.4.

### BR05 matched by P005

Category: broken_reference; exact identifier: 16.9; Page 5, Section 5.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> …ermination-dispute referral process is specified in Section 16.9. A dispute entry shall identify the

Ground-truth supporting quote:

> The termination-dispute referral process is specified in Section 16.9.

### BR06 matched by P006

Category: broken_reference; exact identifier: 17.3; Page 6, Section 6.6.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> in Section 17.3.

Ground-truth supporting quote:

> The document-service protocol for court correspondence is stated in Section 17.3.

### UT01 matched by P007

Category: undefined_term; exact identifier: Delivery Window; Page 1, Section 1.4.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The Supplier shall include the Delivery Window in each monthly service schedule. The schedule shall be

Ground-truth supporting quote:

> The Supplier shall include the Delivery Window in each monthly service schedule.

### UT02 matched by P010

Category: undefined_term; exact identifier: Payment Reserve; Page 2, Section 2.5.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The Customer shall record the Payment Reserve in its monthly reconciliation entry. The entry shall

Ground-truth supporting quote:

> The Customer shall record the Payment Reserve in its monthly reconciliation entry.

### UT03 matched by P011

Category: undefined_term; exact identifier: Security Baseline; Page 3, Section 3.3.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The Supplier shall record the Security Baseline in the access register before enabling a user account.

Ground-truth supporting quote:

> The Supplier shall record the Security Baseline in the access register before enabling a user account.

### UT04 matched by P013

Category: undefined_term; exact identifier: Service Credit; Page 4, Section 4.3.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The Supplier shall show the Service Credit as a separate item in the monthly performance report. The

Ground-truth supporting quote:

> The Supplier shall show the Service Credit as a separate item in the monthly performance report.

### UT05 matched by P014

Category: undefined_term; exact identifier: Exit Package; Page 5, Section 5.3.

Matching reason: Same category and exact identifier; a uniquely located source mention is inside the ground-truth quote on the same page and section.

Detector excerpt:

> The Supplier shall deliver the Exit Package to the Customer within 7 calendar days after termination.

Ground-truth supporting quote:

> The Supplier shall deliver the Exit Package to the Customer within 7 calendar days after termination.

## Missed rule-based issues

None among evaluated categories.

## Unmatched predictions / false positives

### P008: undefined_term - Business Days

Page 2; source sections: 2.1. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …d in the shared ticket queue within two Business Days of transfer. A bank reference

### P009: undefined_term - Business Days

Page 2; source sections: 2.4. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …sponding withholding record within five Business Days after payment. This provision

### P012: undefined_term - Business Days

Page 3; source sections: 3.6. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …ier shall provide that copy within five Business Days. The copy shall omit authentication secrets and

### P015: undefined_term - Business Days

Page 5; source sections: 5.3. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …stomer shall confirm receipt within two Business Days after the export entry is posted. A failed

### P016: undefined_term - Business Days

Page 5; source sections: 5.4. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …s clause shall last no longer than five Business Days. The Supplier shall then

### P017: undefined_term - Business Days

Page 5; source sections: 5.5. No ground-truth issue matches this category, exact identifier, page, section, and supporting source mention.

> …deliver the requested copy within five Business Days. Delivering a copy does not

## AI issues not evaluated

- CT01: Conflicting invoice due dates
- CT02: Conflicting exclusive fee currencies
- CT03: Deletion conflicts with mandatory retention
- CT04: Subcontracting prohibited and required
- CT05: Conflicting termination notice periods
- AM01: Subjective acceptance standard
- AM02: Unspecified priority response timeframe
- AM03: Unbounded reasonableness standard for expenses
- AM04: Undefined material-change threshold for suspension

No claim is made about detecting all planted issues. This clean synthetic contract is not representative of all legal documents. Matching is strict and may under-credit ambiguous/truncated source snippets; the full audit data is in the JSON report.

## Reproducibility

```json
{
  "benchmark": "fictional-commercial-services-v1",
  "benchmark_version": 1,
  "pdf_sha256": "99a9153c692284744f319030309565a37388175d93a4c9c1b319b2392d76ce4c",
  "answer_key_sha256": "fdd0519c93aa60a7dd0547bc91b99049fde22d4c9ed9dea96a605b3cfc6d5206",
  "pipeline": "main.analyze_document (unchanged production function)",
  "code_sha256": {
    "main.py": "cfb94e6ce6a108e0f5768d41e6aa33c208139bf18b5e9be6e6a73ecf4442cc85",
    "detection.py": "63f3ca0753397d607e4a5571d509b00429914aa56bdb59ef7296ff013dbd2550",
    "terms.py": "71ac18614bb8cd4b71738c054d6ada2d9e70423025599bc23977e1aea4097e32",
    "benchmark/build.py": "1e7d731029d8bbc473e6cb1604b7cd0564314a2ea5ec971b31dc6bf654d4ecb7",
    "benchmark/evaluate.py": "99abf2eb91c355656a707633452bde623d88ee5ab0a1fad6184b8c9077daf650"
  },
  "python_version": "3.13.1",
  "pymupdf_version": "1.28.2"
}
```

Pipeline warnings: {"references": null, "terms": null}
