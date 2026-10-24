# Processing and approval permissions

The processor increment adds routine source/draft preparation without expanding
the existing internal-order approval or administrator reference-data boundary.
This initial matrix preserves administrator-only conversion. It is a preparation
increment; assignment, reasoned returns and reviewer work queues remain required.

| Action | Processor | Reviewer | Administrator | Viewer |
| --- | --- | --- | --- | --- |
| Read workspace catalogue, sources, drafts and customer references | Yes | Yes | Yes | Yes |
| Receive/link original sources; run/retry bounded extraction | Yes | Yes | Yes | No |
| Create/edit drafts, explicitly apply proposals and select catalogue matches | Yes | Yes | Yes | No |
| Confirm an account and delivery location on an editable draft | Yes | Yes | Yes | No |
| Record routine source review decisions | Yes | Yes | Yes | No |
| Convert source draft to an internal order | No | No | Yes | No |
| Submit an internal order for final review | No | Yes | Yes | No |
| Approve/reject internal orders; generate/read generic export artifacts | No | Yes | Yes | No |
| Maintain catalogue/customer reference data and approve permanent aliases | No | No | Yes | No |
| Manage memberships | No | No | Yes | No |

Source review/application does not approve an internal order or establish external
acceptance. Existing reviewer/administrator self-approval behavior is unchanged;
this increment does not introduce a separation-of-duties claim. Processor sessions
must remain unable to approve/reject through both HTTP services and direct SQL.
Forced tenant RLS, fresh membership after organization-lock waits, immutable
originals/conversions and bounded worker claims remain required for every role.

Verified local preparation slice: focused161 native, direct runtime66, Node130,
real Chromium processor preparation/administrator handoff and fresh candidate
896 native/66 order/115 catalogue checks, trusted production browser (four roles),
TLS/static/CSRF, storage/DB outage and recreation gates PASS. Commands, failures,
scope and timings are in PROJECT_STATE.md. Team assignment and reasoned-return
queues remain unimplemented. The independent unit arithmetic module does not
establish controlled-unit workflow readiness.
