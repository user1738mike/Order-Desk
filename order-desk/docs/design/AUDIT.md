# Order Desk UI audit - 20 October 2026

## Scope and method

Step 1 of the supplied design brief, adapted to Order Desk after the user
confirmed the target. The agency CRM entities in the original brief are not
present in this application; no invented clients, subscription, contract or MRR
screens are proposed as UI work. No reference screenshots/apps were attached.
Retain the user's approved Outfit/Nunito Sans font pairing.

Review baseline: 8d94769. The app runs at http://127.0.0.1:8000/.
Current routes/renderers, templates and CSS were reviewed alongside real
Chromium captures at 1440px and 390px. Browser scenarios use test_orderdesk,
restricted orderdesk_app serving, synthetic identities and isolated private
storage; owner credentials are confined to fixture setup/cleanup. Main data is
not seeded, reset or restored. UI and application logic are unchanged.

## Screen coverage

- Shell/navigation, workspace choice, loading/error/empty/missing-route states.
- Sign-in and incorrect-credential feedback.
- Catalogue search, filters, pagination and admin product/CSV management.
- Draft list/detail, review/readiness, line editing, attachment/matching,
  stale edits and conversion confirmation/result.
- Document lookup, upload/list/download, extraction failure/success, CSV/text-PDF
  proposals and explicit field comparison/application.
- Purchase-order lookup, lines, submission/approval and export readiness/preview.
- Editor dialogs on desktop/mobile; keyboard skip link and dialog focus.

## Eight priorities

| Priority | Screen and element | Finding and consequence | UI remedy / boundary |
| --- | --- | --- | --- |
| 1 | Documents and Approval: order lookup | Work starts with an internal UUID. Staff must copy an ID before opening routine work; the loaded order repeats that identifier prominently. Conversion results already offer direct handoff links, but there is no general order browser. | Compact the existing lookup and demote repeated references. An order picker/search list needs a code decision because it requires data/state work. |
| 2 | Mobile catalogue and shared page header | The first catalogue record begins around y=780 in a 390x844 viewport. Navigation, introduction, workspace/role and filters take almost the whole screen; records feel secondary. | Compact repeated context and controls. Make records easier to read and show a horizontal-scroll cue where tables exceed the viewport. Keep full data accessible. |
| 3 | Document extraction: field review | Raw source, extracted value, current draft, provenance and correction controls repeat as long vertical blocks. The current one-row/two-field review capture is 4,718px tall at 390px. Comparing a mismatch requires retaining values in memory and scrolling. | Align Source / Current draft / Selected value in a consistent comparison layout. Keep every explicit checkbox, correction, decision and event binding. |
| 4 | General operation feedback | Documents, matching, review, catalogue writes and approval/export messages all receive green styling even when the message describes failure or uncertainty. Colour implies success before the message has been read. | Use neutral general feedback; retain existing red field errors and amber blockers. Adding automatic severity classification needs a code decision if it adds controller/state behavior. |
| 5 | Draft list/detail: metadata and checks | UUIDs, initiating-user ID, full timestamps and seven header fields appear ahead of requested lines. In the current one-line desktop capture, requested lines begin around y=1030. Customer context and the next blocking issue take longer to find. | Compact customer/reference header, technical-reference disclosure and stronger blocker/line hierarchy. Do not remove readiness checks or source evidence. |
| 6 | Approval/export: heading and status text | Order number, customer and approval state share one heading; export status combines profile, eligibility, artifact state and retry diagnostics. Different decisions are compressed into technical strings. | Separate order identity, approval state, export eligibility and next action visually using the existing values. Put retry/profile details in secondary disclosure. |
| 7 | Draft detail and Documents: primary actions | Create manual draft remains the strongest top action inside an existing draft; conversion is far below the requested line and suggestions. Document rows also give download and extraction equal green prominence. Starting another task competes with completing the current one. | Give the current task one clear primary action; quiet contextual/row actions and bring related review and conversion sections closer without bypassing checks. |
| 8 | Sign-in: dark introduction panel | The slogan Every order. Every detail. and repeated workflow instructions occupy half the desktop panel and about 280px above the mobile form. This still resembles a landing-page introduction and conflicts with the brief's no-hero rule. | Make authentication the focal task; shorten or remove repeated introduction content. Keep account-access help adjacent to the form. |

## Keep

The current font pair, restrained palette, shared CSS tokens, outline navigation
icons, real tables, visible keyboard focus and explicit review/approval gates are
useful foundations. A new font, decorative dashboard or blanket palette swap
would not resolve the problems above. Preserve clear business distinctions
between extracting, matching, applying, converting, approving and exporting.

## Needs code decision

1. Searchable purchase-order picker/list in place of mandatory ID entry.
2. Explicit feedback-severity metadata if semantic success/error styling cannot
   be determined from existing presentation context. Do not infer severity from
   message strings or change validation/state during UI work.
3. New operational dashboard counts/queues require real data contracts and
   queries. Agency MRR, renewals and contracts have no current data model here.

## Verification and handoff

- `node --test frontend/tests/*.test.js`: 109 PASS, zero failures (1.872s).
- `node backend/var/ui-audit-2026-10-20/workflow-audit.mjs`: PASS; existing real
  Chromium session/catalogue/edit/matching/conversion/document/extraction/
  application/revocation regressions. Private copy of the existing harness,
  alternate ports 18001/19223/19224, added 1440/390 review captures.
- `node backend/var/ui-audit-2026-10-20/screens-audit.mjs`: PASS; 22 additional
  captures, 1440/390/320px page-overflow guards, keyboard skip link/dialog focus,
  login/error, catalogue admin, editor/blockers, conversion, actual submission/
  approval, export readiness and document intake. No export artifact generated.
- Inspected fresh current-font screenshots of catalogue, drafts/editor,
  CSV/field/PDF review, sign-in, administration and approval/export.
- Synthetic fixture cleanup completed; no browser fixture manifest remained.
- No app implementation files changed relative to review baseline 8d94769.

Per the instruction to work on main, main was fast-forwarded from its older
revision to the already-existing review baseline 8d94769 after verification.
That preserves the current app and prior accepted work. The Step 1 commit itself
adds this audit and updates PROJECT_STATE only; it makes no implementation change.

Private audit screenshots/scripts are retained under ignored
backend/var/ui-audit-2026-10-20; they are synthetic verification artifacts, not
product records. Step 1 changes documentation only. No frontend build pipeline
exists: this frontend serves native JavaScript modules and CSS. Accessibility
review here is focused observation, not the final axe/Lighthouse audit requested
for Step 5.

Exact next action: Step 2 design documents (DESIGN.md, TOKENS.md, COMPONENTS.md,
COPY_GUIDE.md, SLOP_CHECKLIST.md) before any UI implementation; retain the
requested fonts and present any logic-dependent proposals separately.
