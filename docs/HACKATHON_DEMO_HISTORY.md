> Historical engineering notes. For the current demonstrated result and remaining limits, see the repository README and demo/evidence/completed-run.json.

# Claim911: the discharge delay nobody owns

Presentation rehearsal guide. All patient, institution, document and financial data are synthetic.

**Current release status:** not hackathon-ready. No complete 13-checkpoint Bolna case has passed. The full voice demonstration below is a storyboard until that evidence exists. Do not use partial recordings or a local fixture to imply otherwise.

## The pitch

A patient is ready to leave the hospital, but the family hears only “insurance is pending.” The problem is spread across billing, medical records, the implant store, hospital insurance, the TPA and the insurer. Nobody gives the family a complete next step.

Claim911 is a caregiver assistant that follows the people and paperwork behind that delay. Bolna conducts focused voice conversations. Claim911 carries confirmed facts between desks, coordinates missing evidence, requests permission for the exact document packet and checks whether the receiving institution actually got it. The family sees one clear next step and a source-backed explanation.

The assistant does not decide insurance coverage, sign a clinical document, impersonate hospital staff or make a payment.

## Three-minute storyboard

Use this sequence only with a complete verified run. For a replay, label the entire presentation “Recorded synthetic run” and show the original run identity and provider provenance. Do not label a replay live.

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Caregiver start and case concern | “The family is ready to leave. They paid a ₹30,000 deposit, but nobody can explain which insurance step is holding up discharge.” |
| 0:25–0:50 | Focused hospital and claims conversations | “Bolna speaks to the people who own the information. Initial authorization, enhancement and final request stay separate. The claims desk reveals an outstanding document query.” |
| 0:50–1:20 | Three document owners and unsigned-summary callback | “Billing has corrected a duplicate charge. Insurance still has the old bill. Records cannot release an unsigned summary, and the implant invoice is with another department. Claim911 coordinates the owners instead of asking the family to repeat the story.” |
| 1:20–1:45 | Exact packet permission and hospital dispatch | “Before sharing, the caregiver sees the exact documents and recipient. If a document changes, approval expires. The hospital submits through its own system.” |
| 1:45–2:10 | Separate receiving-side receipt, query closure and insurer decision | “A hospital saying ‘sent’ is not enough. Claim911 checks the receiving side, then verifies query closure and enhancement linkage. The insurer issues its own decision.” |
| 2:10–2:40 | Hospital reconciliation and caregiver outcome | “The revised bill is ₹2,48,000. Insurer payable is ₹2,30,000. Patient share is ₹18,000. Against the ₹30,000 deposit, ₹12,000 is due back. Payment remains unverified.” |
| 2:40–3:00 | Evidence and operations view | “Voice obtains the missing facts. The coordinator controls what happens next. Institution evidence determines what is true. The family sees clarity, not the machinery.” |

Keep audio excerpts short enough to hear a complete question and its relevant answer. Never splice separate attempts into one apparently continuous successful case. Keep the full original audio available for inspection.

## What judges should be able to inspect

- Caregiver: current blocker, their own next action, required documents, exact permissions and final explanation.
- Operations: proposed next action, source evidence, conversations, follow-up state, attempts and exceptions.
- Sandbox: synthetic scenario, isolated institutions, run provenance, faults and evaluation results.
- One complication and recovery, preferably the unsigned summary. The institution releases the signed document; the agent does not sign it.
- Separate records for hospital dispatch, recipient receipt, insurer decision, administrative clearance and refund payment.

## Current evidence boundaries

| Area | What currently exists | What it does not prove |
|---|---|---|
| Workflow | Local synthetic institution, checkpoint, service and worker tests | A successful Bolna end-to-end case |
| Simulator | Network-denied participant/control regression suite | Current model quality or speech recognition reliability |
| Product | Separate caregiver, controller and sandbox; local API and responsive/accessibility checks | Connected autonomous operational dispatch |
| Voice | Historical Bolna calls, component passes and preserved failed cases | Three fresh full-case passes with the current configuration |
| Legacy routing case | Preserved review disposition | Resolved routing outcome |

Paid testing is stopped. Do not top up, switch assistants or start repeated calls to complete this storyboard.

## Release checklist

- [ ] Fresh participant text admission matches the current implementation and provider image.
- [ ] Complete Bolna case passes all 13 independent checkpoints, including the complication and recovery.
- [ ] Three fresh consecutive cases pass with the same reviewed configuration.
- [ ] Human listening confirms relevance, natural replies, identifier handling and accurate tool outcomes throughout.
- [ ] Mandatory failure scenarios pass without false verification or unauthorized action.
- [ ] The UI can start and inspect the verified demonstration through the intended worker path.
- [ ] Fresh setup reproduces the complete synthetic run.
- [ ] Costs are reconciled and remaining limitations are visible.
- [ ] Guided demo and replay identify their provider, synthetic data and original run provenance.

Latest offline screening: Release readiness audit (historical local artifact, not included in this public release). It screened 71 exported reports and found the latest three full-case attempts ineligible. This is exported-report screening, not fresh provider verification.
