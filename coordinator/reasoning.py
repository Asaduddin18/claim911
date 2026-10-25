"""Public decision summaries and independent policy checks, never private reasoning."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Observation(Contract):
    reference: str
    status: Literal['reported', 'uploaded', 'verified', 'system']
    summary: str = Field(min_length=1, max_length=500)


class ActionProposal(Contract):
    version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    context_hash: str
    consent_version: int
    action: Literal['investigate', 'collect_document', 'request_permission', 'request_submission',
                    'verify_receipt', 'verify_query', 'verify_decision', 'verify_reconciliation', 'handoff', 'human_review']
    desk: Literal['hospital_insurance', 'billing', 'medical_records', 'implant_store', 'tpa', 'insurer', 'caregiver', 'operator']
    purpose: str
    evidence_references: list[str] = Field(min_length=1)
    expected_checkpoint: str
    summary: str = Field(min_length=1, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PolicyDecision(Contract):
    proposal_id: UUID
    state: Literal['permitted', 'approval_required', 'blocked', 'human_review']
    reason: str
    dispatch_authorized: Literal[False] = False


class ExecutionResult(Contract):
    proposal_id: UUID
    state: Literal['queued', 'reported', 'verified', 'failed', 'uncertain', 'cancelled']
    evidence_references: list[str]
    summary: str


def context_hash(snapshot):
    # Include evidence and workflow changes, not only incident version.
    protected = {k:snapshot.get(k) for k in ('incident','documents','events','complex_workflow','calls')}
    return hashlib.sha256(json.dumps(protected, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def observations(snapshot):
    row = snapshot['incident']
    result = [Observation(reference='incident:'+str(row['id']), status='system', summary='Case state: '+row['state'])]
    for document in snapshot.get('documents', []):
        result.append(Observation(reference='document:'+str(document['id']), status='uploaded',
                                  summary='Uploaded evidence: '+document['filename'][:400]))
    for event in snapshot.get('events', []):
        result.append(Observation(reference='event:'+str(event['sequence']), status='system', summary=event['type'][:500]))
    return result


def propose(snapshot):
    """Deterministic baseline planner. A model may propose only the same typed actions.

    No hidden scenario facts, institution credentials or private desk views enter
    this function. Document verification and approvals remain core responsibilities.
    """
    row = snapshot['incident']; workflow = snapshot.get('complex_workflow')
    evidence = observations(snapshot)
    base = dict(incident_id=row['id'], context_hash=context_hash(snapshot), consent_version=row['consent_version'],
                evidence_references=[x.reference for x in evidence])
    def action(kind, desk, purpose, checkpoint, summary):
        return ActionProposal(**base, action=kind, desk=desk, purpose=purpose, expected_checkpoint=checkpoint, summary=summary)
    if not row['consent_active']:
        return [action('request_permission','caregiver','INVESTIGATION_CONSENT','consent_active','Ask the caregiver for permission before investigation.')]
    if row['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:
        return [action('human_review','operator','REVIEW_HOLD','human_review_resolved','The case is held for a coordinator to review.')]
    if not workflow:
        if row['reference']=='UNCONFIRMED_FINAL_REFERENCE':
            return [action('investigate','hospital_insurance','HOSPITAL_REFERENCE_DISCOVERY','hospital_references_reported','Ask the hospital for the distinct admission and authorization references.')]
        return [action('investigate','tpa','QUERY_DISCOVERY','claims_query_discovered','Ask the claims desk what is holding up the final request.')]
    pending = [t for t in workflow.get('tasks',[]) if t['state']!='EVIDENCE_COLLECTED']
    if pending:
        purposes={'itemized_bill':'BILLING_DOCUMENT','signed_discharge_summary':'RECORDS_DOCUMENT','implant_invoice':'IMPLANT_DOCUMENT'}
        return [action('collect_document', t['owner'], purposes[t['kind']], {'itemized_bill':'bill_checked','signed_discharge_summary':'signed_summary_checked','implant_invoice':'implant_invoice_checked'}[t['kind']],
                       'Ask the responsible desk for '+t['kind'].replace('_',' ')+' and verify the uploaded evidence.') for t in pending]
    if not workflow.get('approval_current'):
        return [action('request_permission','caregiver','EXACT_PACKET_APPROVAL','exact_packet_approved','Show the exact documents and recipient for disclosure approval.')]
    if not workflow.get('receipt'):
        dispatch_reported = any(r.get('purpose')=='PACKET_SUBMISSION' and r.get('details',{}).get('dispatch_reference') for r in workflow.get('reports',[]))
        if dispatch_reported:
            return [action('verify_receipt','tpa','RECEIPT_VERIFICATION','recipient_receipt_verified','Check the receiving desk receipt independently of hospital dispatch.')]
        return [action('request_submission','hospital_insurance','PACKET_SUBMISSION','hospital_dispatch_recorded','Ask the hospital to submit only the currently approved packet.')]
    if not workflow.get('query_resolution'):
        return [action('verify_query','tpa','TPA_QUERY_FOLLOWUP','query_and_enhancement_verified','Verify query closure and enhancement linkage with institution evidence.')]
    if not workflow.get('decision'):
        return [action('verify_decision','insurer','INSURER_FOLLOWUP','insurer_decision_verified','Ask the insurer for its decision and verify the signed record.')]
    if not workflow.get('clearance'):
        return [action('verify_reconciliation','billing','DISCHARGE_FOLLOWUP','hospital_reconciliation_verified','Ask billing to reconcile the decision, bill and deposit.')]
    return [action('handoff','caregiver','CAREGIVER_COMPLEX_UPDATE','caregiver_handoff_completed','Explain the verified outcome and distinguish refund due from refund payment.')]


def evaluate(proposal, snapshot):
    """Validate again immediately before execution; a proposal itself grants nothing."""
    def decision(state, reason):
        return PolicyDecision(proposal_id=proposal.id, state=state, reason=reason)
    row=snapshot['incident']
    if str(proposal.incident_id)!=str(row['id']) or proposal.context_hash!=context_hash(snapshot) or proposal.consent_version!=row['consent_version']:
        return decision('blocked','The case changed. Refresh evidence and propose again.')
    if proposal.created_at.tzinfo is None:
        return decision('blocked','A timezone-aware proposal timestamp is required.')
    age=(datetime.now(timezone.utc)-proposal.created_at).total_seconds()
    if age < 0 or age > 300:
        return decision('blocked','The proposal expired. Refresh the case.')
    refs={o.reference for o in observations(snapshot)}
    if not set(proposal.evidence_references).issubset(refs):
        return decision('blocked','A cited evidence reference is not in this case.')
    candidates=propose(snapshot)
    if not any((p.action,p.desk,p.purpose,p.expected_checkpoint)==(proposal.action,proposal.desk,proposal.purpose,proposal.expected_checkpoint) for p in candidates):
        return decision('blocked','The proposed action does not satisfy the current workflow gate.')
    if proposal.action=='human_review':return decision('human_review','A coordinator must resolve the hold.')
    if proposal.action=='request_permission':return decision('approval_required','Only an explicit caregiver action can grant permission.')
    if not row['consent_active']:return decision('blocked','Investigation permission is inactive.')
    return decision('permitted','The next action is eligible. Execution still requires fresh scoped tool authorization.')


def decision_view(snapshot):
    proposals=propose(snapshot)
    return {'version':1, 'engine':'deterministic_baseline', 'context_hash':context_hash(snapshot),
            'observations':[o.model_dump(mode='json') for o in observations(snapshot)],
            'proposals':[p.model_dump(mode='json') for p in proposals],
            'policy_decisions':[evaluate(p,snapshot).model_dump(mode='json') for p in proposals],
            'automatic_dispatch':False}
