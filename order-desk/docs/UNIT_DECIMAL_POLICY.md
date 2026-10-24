# Controlled product units — implementation contract, not verification

Requested quantity and unit remain source fields. Selecting a catalogue product
must not change them or infer a pack size from a description. Administrators
approve product-specific mappings from exact requested-unit tokens to controlled
selling units and optional destination units, with source/reason, actor and time.
Case and punctuation are preserved unless a separate exact alias is approved.
An unknown token, inactive mapping or ambiguous mapping is an explicit blocker.

Use positive, bounded Decimal ratios rather than floating point. A ratio has a
numerator and denominator; this can represent twelve each per case exactly.
For example12 requested each ×1/12 produces exactly1 selling case;1 each cannot
be represented as a case at a finite configured precision and must be rejected
unless a future explicitly approved rounding policy exists. Storing an approximate
decimal0.083333333333 as1/12 must not silently make12 each nearly one case.

Every selling/destination quantity needs an explicit supported scale and range.
Compute with ample local Decimal precision, then verify the candidate against the
original ratio by exact multiplication. Reject discarded nonzero precision,
zero/negative values, invalid ratios, overflow, exponent input and numeric floats.
No default round-to-nearest, truncation or guessed case/box multiplier is allowed.
Destination mapping without a real contract remains operator reference data,
never evidence of an external system's acceptance.

The operator previews both original and calculated values and deliberately
confirms the selected product/mapping. Persist immutable versioned decision
snapshots with original token/quantity, selected catalogue identity, policy
identity/version, exact ratios and formatted normalized quantities. Material line
changes retire the decision; policy/catalogue inactivity or changed reference data
requires renewed confirmation. Frozen order decisions remain unchanged by later
reference edits. Legacy generic CSV keeps its original structural contract and
does not establish controlled-unit or destination-specific readiness.

Customer product aliases are separate approvals scoped to organization and
confirmed customer account. Exact SKU evidence remains available. Product aliases
retain approval provenance, reject collisions and require deliberate selection;
correcting a draft never learns one. Changing customer identity invalidates any
customer-specific match evidence. Native PostgreSQL, restricted-role relationship/
collision/demotion races, typed client and actual-browser proofs are required
before this contract can be marked implemented.
