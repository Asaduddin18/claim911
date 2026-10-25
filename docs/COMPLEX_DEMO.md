# Synthetic discharge rescue: the outstanding document query

This replaces the single wrong-destination story as the main demo specification. All names, identifiers, documents, amounts and institution responses are synthetic. Current status: institution APIs, coordinator, scoped voice tools and portal are implemented. One synthetic case has hosted query/document evidence and institution-API evidence through discharge clearance. A fresh manual rehearsal reproduces the full institution workflow. Hosted submission and downstream follow-ups, complete live voice proof, and remaining intake/escalation work are incomplete. Historical milestone notes below retain their original point-in-time status. The existing routing case remains a regression.

## The case

A patient has undergone fracture fixation at a network hospital. The treating team has cleared discharge. The caregiver has paid a INR 30,000 deposit. Hospital staff say final insurance approval is pending. The TPA received an earlier packet and raised a document query, while the hospital insurance desk believes the latest documents are under review.

Billing has revised the final bill after removing a duplicate INR 4,000 charge. The insurance desk still has bill v1. A discharge summary awaits the treating team's signature, and an implant invoice sits with the hospital store. An enhancement request also needs association with the existing claim. These are connected tasks within one episode, not independent disasters added for drama.

## Research basis

Medi Assist explains that initial authorization is provisional and that an information request can require hospital documents or clarification: https://blog.mediassist.in/wp-content/uploads/2025/05/Medi-Assist-Frequently-Asked-Questions-FAQs-for-Patients-Hospitals-Helpdesk.pdf

Its cashless guide describes additional information requests during interim/final processing: https://t.mediassist.in/Resource/Guide/Cashless%20Claims%20Guidelines.pdf

IRDAI's health FAQ specifies final authorization within three hours of receipt of the hospital discharge authorization request: https://irdai.gov.in/health-dept

The exact document query, unlinked enhancement, locations, revision and amounts are authored synthetic conditions. Implant documentation is a plausible case-specific query, not a universal requirement. The original receipt time is preserved. A query does not automatically restart the timer, and a demo timer is not a legal finding.

## Investigation and resolution

1. Caregiver intake captures consent, the admission and deposit receipt. The caregiver knows only that discharge is delayed. Hidden blockers are not preloaded as agent findings.
2. Hospital insurance desk confirms separate initial, enhancement and final references, plus dispatch proof. Upload acknowledgment does not establish receiving-side status.
3. TPA call discovers query IR-SYN-331, the exact missing documents, packet version received, original receipt time and unlinked enhancement. Findings link to the conversation.
4. Three hospital follow-ups obtain the revised itemized bill from billing, the institution-signed discharge summary from records and the admission-matched implant invoice from the store. Show owners, callbacks and dependencies. The agent cannot sign clinical documents.
5. Reconcile patient/admission IDs, document versions and amounts. An invoice for another admission must be rejected. Missing evidence prevents packet completion.
6. Caregiver approves disclosure of the exact packet. Approval binds recipients, case, query, revision and hash. A changed packet invalidates approval. This is coordination consent, not insurance approval.
7. Hospital submits against the existing query/claim through its own portal. Do not create a duplicate claim. The agent cannot impersonate hospital staff.
8. TPA independently acknowledges the exact packet, updates the query and confirms enhancement linkage. A hospital upload statement cannot satisfy this gate.
9. If the decision remains pending, follow up with the authorized review desk and escalate with the original receipt time. Only insurer staff issue the scripted synthetic decision. A denial branch is preserved rather than overridden.
10. Hospital billing reconciles the latest bill, final authorization and deposit. The hospital issues clearance and a refund acknowledgment. The caregiver receives a source-linked explanation. Refund due and refund paid are separate states.

## Synthetic amounts

Initial provisional authorization is INR 150,000. The enhancement requests a total ceiling of INR 250,000, not another INR 250,000. Bill v1 is INR 252,000. Removing a duplicate INR 4,000 produces bill v2 of INR 248,000. The scripted insurer-issued final authorization is INR 230,000, leaving an institution-confirmed patient share of INR 18,000. Deposit paid is INR 30,000, so INR 12,000 is refundable. The agent checks arithmetic and explains issued documents; it does not decide coverage or make payment.

## Why voice and agents are necessary

The caregiver otherwise has to discover the query, locate three document owners, repeat references, chase signatures, carry documents back, confirm receipt and reconcile billing. Focused voice conversations obtain information unavailable in the caregiver's portal. Shared agent memory carries confirmed references, evidence and commitments between desks. A dependency graph prevents premature submission or a false success announcement.

## Failure branches

- Desk unavailable: bounded callback with owner and time, no blind repeat dialing.
- Summary unsigned: await the institution's signature.
- Invoice belongs to another admission: reject and escalate.
- Packet changes after approval: approval becomes stale.
- Upload accepted but no recipient acknowledgment: delivery stays unverified.
- Only old bill received: query stays open.
- Receipt exists but decision pending: do not announce approval.
- Partial authorization or denial: preserve institution decision and reasons.
- Consent withdrawn: block protected actions.
- Deadline reached: evidence-backed escalation using the original receipt time.
- Deposit receipt missing: refund remains unverified.
- Refund acknowledged but unpaid: show payment pending.

## Build order and proof

First extend institution data and operations: role-private documents, query state, packet versions, owner availability, enhancement linking, insurer decision, billing and refund acknowledgment. Then implement coordinator task dependencies and authorization invariants, scoped voice tools and dashboard views. Run hosted-model text regressions before a bounded consented voice demonstration.

Completion requires one reproducible run whose evidence proves each gate: discovered query; three correct documents; current packet approval; hospital submission; independently attested exact receipt; query and enhancement updates; institution-issued decision; billing clearance and correct refund due. Receipt, query closure, approval, discharge clearance and refund payment must remain separate. Scripted institution events and text tests must never be represented as real phone conversations. No real hospital, insurer or patient is contacted.


## Institution milestone verified

The running local services completed an 18-operation direct API rehearsal on 23 October. Evidence: outputs/Claim911_Complex_Institution_Rehearsal.json. Hospital dispatch stayed distinct from receiving-side acknowledgment; the Ed25519 receipt signature and packet hash were verified. Unsigned summary and premature billing reconciliation were blocked. The scripted insurer decision produced INR 18,000 patient share and INR 12,000 refund due, with refund payment NOT_VERIFIED. The full backend suite passed 84 checks. This run involved zero agent conversations and zero telephone calls. Hospital desk names are view filters under hospital organization authentication, not separate staff credentials. The insurer has a dedicated API credential. Core database credentials have no institution-table access. Caregiver packet approval and task orchestration remain to be implemented for this complex case.


## Coordinator milestone verified

The coordinator now supports source-linked query intake, three document tasks, exact-packet caregiver approval recording and independent signed receipt verification. A running-service manual rehearsal linked five documents and a signed exact-packet receipt. Insurance remains PENDING; the next step is query and enhancement follow-up. The dashboard has a Discharge workflow tab and source evidence links. Revision, consent and mismatch checks are included in the 88 passing backend checks. This is a manual reconstruction, not an agent conversation or a real voice run. Complex-case voice tools, final decision tracking and discharge/refund tracking remain incomplete.


## Final institution evidence milestone verified

The coordinator now verifies separately signed TPA query closure/enhancement linkage, insurer decision and hospital reconciliation. Distinct issuer keys separate insurer and hospital attestations from recipient receipts. The full manual rehearsal reached DISCHARGE_CLEARED with insurer AUTHORIZED and INR 12,000 refund due. Refund payment remains unverified. A denial test instead remains DENIED with patient balance pending. Replayed earlier evidence cannot regress a later state. Backend suite: 91 passed; dashboard build and visible final-state checks passed. This remains a manual reconstruction; hosted-agent and real voice execution for the complex workflow are not yet proved.
