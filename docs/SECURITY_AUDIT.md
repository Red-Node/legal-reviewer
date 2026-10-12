# Milestone 9A security audit — Legal Reviewer

Audit date: **October 12, 2026**. Scope: current local source, tracked files,
reachable local Git history/configuration, offline regression tests, dependency
metadata/advisories, deployment files, and passive GET checks of the public demo.
This is a bounded coding-assistant audit, **not penetration-test certification,
independent legal review, or a claim of production-grade security**.

No Anthropic requests, production attack/fuzz uploads, environment changes,
Railway configuration changes, deployment, commits, pushes, or repository
visibility changes were performed. Benchmark PDF, answer key, and evaluation
results were not modified. Vulnerability-feed queries sent package names/versions
only; passive public checks sent no document data or credentials.

## Findings by severity

### Critical — none identified within the inspected scope

No real credentials were found in tracked files or reachable history. This is
not proof that every possible token format or remote/unreachable object is clean.

### High — resource-exhaustion gaps, mitigated locally

**H1: Oversized multipart requests could spool before file validation.**

The original `/analyze` route checked a file's size after FastAPI multipart
parsing had already created/read temporary uploads. A malicious request could
include huge or multiple parts before the route's 10 MB check ran. This is an
unauthenticated disk/memory denial-of-service risk independent of filename checks.

Fix: Starlette `RequestBodyLimitMiddleware` now bounds the entire raw HTTP body
at 10 MB plus 64 KB multipart overhead, before file data is consumed/spooled.
It counts streamed bytes as well as checking Content-Length, so missing or
underreported lengths cannot bypass the bound. The original per-file 10 MB
check remains. Starlette is explicitly pinned at the installed/tested 1.7.0
version because the broadly allowed transitive version range did not guarantee
this middleware API. No new runtime package was installed for this fix.

Tests cover declared oversize, multipart oversize before extraction, streamed
requests without Content-Length, underreported length, and closure of partially
spooled files on rejection. The default 413 message may be plain text at the
outer middleware; it contains no uploaded content or secrets.

**H2: Compressed documents could produce excessive extracted text/work.**

A small compressed PDF had no page-count or accumulated-text bound. DOCX ZIP
checks already capped expanded archive size but not extracted paragraph count or
text delivered to detection/browser rendering.

Fix: PDFs reject more than 500 pages before extracting any text. PDF and DOCX
extracted text is capped at 2 MB UTF-8 bytes. DOCX also rejects more than 10,000
source locations, including empty paragraphs. Limits reject the whole document
without silently truncating it. Existing DOCX caps remain: 10 MB upload, 50 MB
summed declared expanded ZIP size, 2,000 members, ten nesting levels, no macro
packages, encrypted/duplicate packages, or XML DTD/entity declarations.

Tests verify page-limit early exit, byte-based rather than character-based text
limits, detection not running after oversize, and empty-paragraph abuse.

**Residual limitation:** accumulated output limits act after an individual
native parser/text-extraction call. They cannot impose hard CPU/memory limits on
that call, prevent all hostile parser inputs, or stop aggregate concurrent abuse.
Worker isolation, CPU/time quotas, and edge controls require separate work.
These fixes are local and **not deployed**; the live demo retains the previous
limits until an authorized release.

### Medium — unresolved; proposed next work, not expanded here

| Finding | Why it matters | Proposed fix |
| --- | --- | --- |
| No application rate limit, global concurrency quota, authentication, or isolated parser workers | Repeated bounded or slow requests can still exhaust CPU/RAM/temp disk; upload size is not a full DoS defense | Add proxy rate/body/time limits and bounded isolated extraction workers; test them before broader public use |
| Local real-review remains a trusted-operator feature | Host/client/origin/public gates prevent normal public execution, but there is no user authentication or durable audit log; browser-supplied page text is not cryptographically bound to an upload | Keep real mode local/off by default; require authentication and provenance before any future public paid mode |
| Proxy/platform logs and retention were not accessible | No permanent application upload storage does not guarantee erasure from OS memory, temporary disks, browser caches, crash dumps, or platform logs | Review platform retention/access controls and avoid confidential data; use isolated ephemeral workers if needed |
| Transitive dependencies are not a full locked graph | Future builds may select different transitive versions even though direct imports and Starlette are pinned | Introduce a reviewed lock/upgrade process and rerun advisory checks on each release |

No new rate limiter, authentication, database, AI mode, or worker architecture
was implemented. These priorities were reported before further scope expansion.

### Publication cleanup — completed locally; remaining owner decisions

| Item | Current status |
| --- | --- |
| Tracked Finder metadata | `.DS_Store` and `benchmark/.DS_Store` removed from the Git index using `git rm --cached`; local files are preserved and ignored at all directory levels. Deletions are staged, not committed. Historical copies remain; no history rewrite was performed. |
| Compatible browser headers | Normal responses, handled errors, and request-limit responses now include `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a Permissions-Policy disabling camera/microphone/geolocation. Default `Cache-Control: no-store` prevents stale code/private response caching. Clipboard permission is not blocked. No CSP or HSTS was introduced; inline scripts, styles, uploads, PDF download and local HTTP remain compatible. Generic unhandled-server-error responses still follow FastAPI's safe non-debug fallback, outside user middleware. |
| CLI deployment exclusions | `.railwayignore` now explicitly excludes Finder metadata, raw AI capture directories, and generated AI/combined evaluation exports. Git and CLI exclusions are tested independently; fictional ground truth and the rule-based baseline remain intentionally publishable. No deployment was performed. |
| Public OpenAPI docs | Remain enabled; inspected schema exposes routes, not secrets or documents. Disabling public docs is optional future hardening, not a credential-disclosure blocker. |
| Author metadata | Reachable history contains two distinct author/committer name/email identities, both with non-noreply addresses. Values are not reproduced here. Owner must decide whether that normal Git attribution is intended to become public. No identity, ownership, or history changes were made. |
| License | No project LICENSE file exists. Owner must choose whether/under what terms to grant reuse rights and review dependency licensing. No license or copyright owner was invented. |

These changes close the Finder-tracking, CLI exclusion and basic browser-header
cleanup items locally. A restrictive CSP, runtime isolation, rate limiting,
author-history rewriting, and license selection remain outside this cleanup.

## Secret and Git-history inspection

- **20 reachable commits, 104 unique reachable file blobs, 5 local refs** inspected.
  Scan used all local reachable refs (`git rev-list --objects --all`), not just
  the latest commit or working tree.
- No historical `.env` variant other than the intentionally tracked `.env.example`
  was found. No tracked/current or historical exact match for the configured local
  secret was found. Secret values were never printed, hashed into a report, or
  exported.
- Pattern checks covered Anthropic/OpenAI-style keys, GitHub tokens, AWS access
  IDs, private-key blocks, and credential-bearing HTTP URLs. One hit in
  `benchmark/test_run_real_ai.py` is an explicitly synthetic fake test credential.
  No real token finding was identified.
- Local remote configuration contains no embedded HTTP credentials or configured
  extra authorization header. No non-sample Git hooks were installed.
- Git and CLI deployment ignore checks cover real `.env` variants, virtual
  environments, raw AI captures, AI/combined evaluation exports, and Finder
  metadata. Saved real captures are not tracked. The only tracked reports are
  `rule_based_baseline.json` and `.md`, based on the fictional benchmark.
- Refreshing publication checks found no configured real secret matches or
  personal email addresses in current tracked/documentation/report content, and
  no local absolute paths in public-facing Markdown. The only tracked document
  is the six-page fictional benchmark PDF; its author metadata is a project
  benchmark label, not a person's name. Test fixtures contain deliberately fake
  tokens and generic private-path examples; they are not real credentials or
  personal paths. The answer key and assessment file are intentionally repository
  artifacts, not public HTTP endpoints. Actual author emails occur in Git history,
  not in the project documentation, and remain an owner privacy decision.
- Scope does **not** include fetching every remote branch/PR, GitHub settings or
  caches, unreachable/reflog objects, or unidentified credentials with other
  formats. Normal Git author metadata is intentionally not treated as an API key;
  the owner should review their public author identity before publication.

This does not justify rotating a key absent evidence of exposure, and it does
not justify a guarantee that no secret ever existed anywhere. Refresh the scan
before the eventual submission commit/publication. If a real exposure is found,
revoke/rotate first and separately authorize history remediation.

## PASS / WARNING / FAIL checklist

| Area | Status | Evidence / qualification |
| --- | --- | --- |
| Current tracked secrets and reachable-history check | PASS | No real findings within the scan scope; fake fixture identified without displaying its value |
| Public flag overrides paid flag at web/helper/SDK/CLI boundaries | PASS | Offline tests force `PUBLIC_DEMO_ONLY=true`, `ENABLE_REAL_AI=true`; no client instantiated |
| Public deployment start command | PASS | Forces `PUBLIC_DEMO_ONLY=true`; binds `0.0.0.0:$PORT`; no-access-log; settings unchanged |
| PDF/DOCX type, malformed/encrypted/legacy rejection | PASS | Synthetic regression suite; real format/package validation, not MIME trust |
| Wire request/file/output limits | PASS locally | New streaming/body/extraction tests; high fixes are not on Railway yet |
| DOCX expansion/entities/macros/nesting | PASS within bounded scope | Existing ZIP/XML protections plus new text/location limits; no hard worker isolation |
| Permanent application document storage | PASS with qualification | No document cache/database/files; multipart temporary files close, including rejected streams; erasure/host retention not guaranteed |
| Health response and error disclosure | PASS | Health returns only status; safe known errors, debug off, unexpected HTTP errors omit paths/tracebacks; operator logs remain a separate concern |
| Source/config/key/report paths | PASS | Local tests and passive public checks deny sensitive source/key paths; no static repository mount |
| HTML/script injection and decision protections | PASS | textContent/plain textarea/Blob; no innerHTML/eval/storage sinks; existing offline edit/evidence/letter tests |
| CORS/debug configuration | PASS | No permissive CORS middleware; debug false. CORS does not stop nonbrowser clients or every form POST |
| Public prototype/privacy warning | PASS | Visible in served live HTML and tested locally |
| Dependency advisories | PASS within feed scope | OSV queried 26 installed active runtime dependency versions; no advisory IDs returned; not proof against unknown vulnerabilities |
| Dependency/build compatibility | PASS with qualification | pip check passes; Linux Python 3.13 wheels found for all eight declared direct packages plus lxml; actual Railway rebuild was not performed |
| Aggregate DoS / platform privacy controls | WARNING | Isolation, rate/concurrency limits and operator retention review remain outstanding |
| Compatible browser headers and cache policy | PASS locally | Normal/handled/error-limit responses tested; no CSP or clipboard restriction introduced |
| Finder tracking / CLI build hygiene | PASS locally | Two cached removals staged; Git and CLI exclusions tested; historical metadata remains |
| Author privacy / license | WARNING | Owner decisions required; no emails reproduced and no ownership/license changes made |
| Live release contains new high-severity mitigations | WARNING | No deployment authorized or performed; passive checks do not prove the old deployment has the new limits |
| Independently certified/production-grade security | NOT CLAIMED | No certification or exhaustive audit |

No unresolved credential-disclosure FAIL was identified. PASS entries describe
specific evidence, not whole-system security guarantees.

## Verification performed

- **383 offline tests passed**, including 7 new publication/header tests, 19
  security tests, and all 357 existing PDF/DOCX/AI/mock/human-review/benchmark
  regression tests. No API/network calls were made for this publication cleanup.
- `python -m pip check`: no broken requirements.
- Passive live GET checks returned: `/` 200 with DOCX UI and confidentiality
  warning; `/health` 200 with status only; `/review.js` 200; `/.env`, `/.git/config`,
  `/benchmark/answer_key.json`, and saved baseline path 404; `/ai-review-config`
  403. No production uploads, paid endpoint POSTs, or production DoS probes were used for the audit.
- Public read checks do not expose Railway environment variables or fully prove
  production paid-mode state; the inspected forced start command plus local
  gate tests establish code behavior. Runtime settings were not changed.
- The previously running local project server was identified by command and working
  directory, stopped, and replaced with the audited code on port 8000. Local
  health and the fictional DOCX smoke upload passed; both expected findings were
  returned. Process flags keep public-demo-only true and real AI false without
  changing `.env`. This local restart is not a Railway deployment.
- OSV feed returned no advisory IDs for the 26 installed versions queried.
  Optional development packages, OS libraries, unknown vulnerabilities, supply
  chain authenticity, and future resolver output are outside that result.
- Wheel check downloaded all eight declared production packages and installed-version
  lxml for Linux x86_64 / Python 3.13 into a temporary directory only. Starlette
  1.7.0, already installed and now explicitly declared, also has a verified
  pure-Python wheel.
  No production dependencies were upgraded. A Linux container/native runtime
  test and actual Railway build still remain.

The framework's [whole-body request limits](https://www.starlette.io/requests/)
include multipart file bytes; per-route file-size checks alone occur too late to
bound spooling. Advisory information came from the
[OSV API](https://google.github.io/osv.dev/api/).

## Before repository publication and live submission

The audited tree is **conditionally suitable for a public hackathon source
submission**, not for confidential legal work. No real secret remediation is
currently indicated, but do not treat this report as blanket permission to publish.

1. Review/include the local high-severity fixes and documentation in the eventual
   submission state, then rerun tests and secret checks. Nothing was committed here.
2. Finder metadata is now untracked/ignored in the current index; review these
   two staged removals and the remaining submission files. Decide whether Git
   author attribution/emails and retained historical metadata are intended to be
   public. Real `.env` and raw captures must stay excluded.
3. Confirm any intentionally shared report/capture is fictional and reviewed;
   answer-key publication in the repository is intentional, HTTP exposure is not.
4. Choose the intended project license and review dependency terms; no license
   was chosen by this audit.
5. Independently verify remote refs/history and GitHub secret-scanning settings
   when available. No remote administration/visibility change was attempted.
6. Before advertising the live deployment as containing these fixes, separately
   authorize a release and verify the limits and paid-mode guard afterward. Keep
   the current public warning and use fictional samples until then.

## Local browser checks

Start/restart from the repository root with `PUBLIC_DEMO_ONLY=true` and
`ENABLE_REAL_AI=false`, then open `http://127.0.0.1:8000/`:

1. Confirm “PDF or DOCX” and the no-confidential-documents warning. In browser
   Developer Tools → Network, reload and inspect the main document response:
   expect `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
   `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. There is no CSP.
   These headers require the updated local server; no live deployment occurred.
2. Upload the fictional DOCX in the README; check Section 9.9 / Delivery Window,
   paragraph labels, highlighting, and unavailable DOCX AI controls.
3. Upload the downloadable synthetic demo PDF, run the free Demo action, and
   confirm the invented-evidence finding cannot be accepted.
4. Edit/accept an eligible finding, draft questions, and check accepted-only text;
   changing a decision should mark the draft outdated.
5. Try a text file renamed to `.pdf` or `.docx` and a file over 10 MB; expect safe
   errors. Rejection of 500+ pages/excessive expansion is exercised offline rather
   than asking a beginner to create abusive documents or probe the live service.

No real Claude request is needed for these checks.
