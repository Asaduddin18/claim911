"""Explain the next investigation step using collected evidence only."""
from coordinator.evidence import supports_predicate

TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'BUSY', 'NO_ANSWER', 'RECORDED'}


def next_step(incident, calls, assertions, actions, documents, receipts):
    def step(kind, reason, purpose=None, evidence=()):
        return {'kind': kind, 'reason': reason, 'purpose': purpose,
                'evidence_ids': [str(f['id']) for f in evidence],
                'automatic_dispatch': False, 'simulated': True}
    if not incident['consent_active']:
        return step('CONSENT_REQUIRED', 'Obtain current caregiver consent before investigating.')
    if incident['state'] == 'HUMAN_REVIEW':
        return step('HUMAN_REVIEW', 'Resolve the access refusal or unconfirmed submission with hospital evidence and human review.')
    if any(c['state'] not in TERMINAL for c in calls):
        return step('WAIT_FOR_CALL', 'Reconcile the active or uncertain call before another call.')
    if receipts and incident['state'] == 'BLOCKER_RESOLVED':
        return step('RESOLVED', 'Recipient receipt verified. Insurance approval remains a separate decision.')
    facts = [f for f in assertions if f['support_status'] != 'SUPERSEDED'
             and f['reference'] == incident['reference']
             and f['request_type'] == incident['request_type']]
    if any(not supports_predicate(f) for f in facts):
        return step('HUMAN_REVIEW', 'A statement label conflicts with its structured value or lacks a clear value. Clarify it before proceeding.', evidence=[f for f in facts if not supports_predicate(f)])
    def matching(role, predicate):
        return [f for f in facts if f['source_role'] == role and f['predicate'] == predicate]
    received = matching('claims', 'RECEIVED')
    missing = matching('claims', 'NOT_RECEIVED')
    if received and missing:
        return step('HUMAN_REVIEW', 'Conflicting claims statements require clarification or an explicit correction.', evidence=received + missing)
    if received:
        return step('VERIFY_RECEIPT', 'A spoken receipt claim does not prove delivery. Obtain the signed recipient receipt.', evidence=received)
    submitted = matching('hospital', 'SUBMITTED')
    if not submitted:
        return step('CALL', 'Ask the hospital whether the final authorization request was submitted and confirm its reference.', 'HOSPITAL_INITIAL')
    if not missing:
        return step('CALL', 'Ask the designated claims desk to search this same final authorization reference.', 'CLAIMS_LOOKUP', submitted)
    destinations = matching('hospital', 'DESTINATION')
    linked = [f for f in destinations if any(str(d['id']) == str(f.get('document_id')) and d['kind'] == 'dispatch' for d in documents)]
    if not linked:
        return step('COLLECT_DISPATCH', 'Ask the hospital for the exact destination and upload its dispatch proof before proposing a correction.', 'HOSPITAL_FOLLOWUP', submitted + missing)
    current = [a for a in actions if a['consent_version'] == incident['consent_version'] and a['state'] in {'PROPOSED', 'AUTHORIZED'}]
    if not current:
        return step('PROPOSE_CORRECTION', 'Compare the documented destination with the designated route before proposing an exact correction.', evidence=submitted + missing + linked)
    action = current[-1]
    if action['state'] == 'PROPOSED':
        return step('APPROVAL_REQUIRED', 'The caregiver must approve this exact correction before the hospital is contacted.')
    if any(c['purpose'] == 'CORRECTION_REQUEST' and c['state'] == 'COMPLETED' and c.get('consent_version') == incident['consent_version'] and str(c.get('action_id')) == str(action['id']) for c in calls):
        return step('VERIFY_RECEIPT', 'Obtain corrected dispatch proof and independently verify the signed recipient receipt.')
    return step('CALL', 'Ask the hospital to perform the approved correction. Only hospital staff can submit it.', 'CORRECTION_REQUEST')
