"""Purpose-owned voice instructions and packet approval shared by API and worker."""
import hashlib,json
from coordinator.caregiver import caregiver_summary
from coordinator.voice_contracts import append_common_closing, CAREGIVER_INTAKE_CLOSING

WORKFLOW_ROLES={'CAREGIVER_INTAKE':'caregiver','CAREGIVER_COMPLEX_UPDATE':'caregiver','HOSPITAL_REFERENCE_DISCOVERY':'hospital',
 'QUERY_DISCOVERY':'claims','BILLING_DOCUMENT':'hospital','RECORDS_DOCUMENT':'hospital','IMPLANT_DOCUMENT':'hospital',
 'PACKET_SUBMISSION':'hospital','TPA_QUERY_FOLLOWUP':'claims','INSURER_FOLLOWUP':'claims','DISCHARGE_FOLLOWUP':'hospital'}
DOCUMENT_PURPOSES={'BILLING_DOCUMENT':'itemized_bill','RECORDS_DOCUMENT':'signed_discharge_summary','IMPLANT_DOCUMENT':'implant_invoice'}


def packet_for(row,w):
    documents=sorted(w['documents'].values(),key=lambda d:d['record']['id'])
    return {'case_id':str(row['case_id']),'patient_id':row['patient_id'],'admission_id':w['query']['admission_id'],
            'query_id':w['query']['references']['query'],'claim_id':w['query']['references']['claim'],
            'reference':row['reference'],'documents':[d['record']['id'] for d in documents],
            'document_records':[d['record'] for d in documents]}


def packet_hash(row,w):
    return hashlib.sha256(json.dumps(packet_for(row,w),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def approval_valid(row,w,expected=None):
    a=w.get('approval')
    return bool(a and row['consent_active'] and a['consent_version']==row['consent_version']
                and a['packet_hash']==packet_hash(row,w) and (expected is None or a['packet_hash']==expected))


def approval_allows_call(w,mode):
    return not (mode=='BOLNA' and (w.get('approval') or {}).get('source')=='SYNTHETIC_REHEARSAL_FIXTURE')


def prepare_context(row,w,purpose):
    if purpose=='CAREGIVER_INTAKE':
        if w:raise ValueError('The query is already known; use a caregiver follow-up')
        objective=f'CAREGIVER INTAKE. Speak English. The caregiver’s investigation permission is already active when investigation_consent_active is true. Browser recording permission was collected before this call. Do not ask for either permission again. After the caregiver describes the blocker, briefly summarize the core concern and ask once whether you understood it correctly. Allow their confirmation or correction before calling claim911_report_update. If it remains unclear, stop for review. Put only the caregiver’s confirmed concern in summary. Do not ask another intake question, request references or documents, or claim you accessed institution systems. After the tool succeeds, say: “{CAREGIVER_INTAKE_CLOSING}” This is the complete final utterance; do not ask another question. If the tool fails, say you could not save the update and stop. Never invent a result.'
        return {'objective':append_common_closing(objective),
                'workflow':{'state':'CAREGIVER_INTAKE','reported_facts_only':True},'allowed_statement_predicates':['ACCESS_REFUSED']}
    if purpose=='HOSPITAL_REFERENCE_DISCOVERY':
        if w:
            raise ValueError('Query is already known; use a follow-up purpose')
        if row['reference']!='UNCONFIRMED_FINAL_REFERENCE':
            return {'objective':append_common_closing('The hospital references have been recorded. Close with the reported status and explain claims receipt still needs independent verification. Do not restart reference discovery.'),
                'allowed_statement_predicates':['ACCESS_REFUSED'],'workflow':{'state':'HOSPITAL_REFERENCES_RECORDED','reported_facts_only':True}}
        objective=f'Ask hospital insurance staff to locate the admission for {row["patient_id"]}. Obtain the admission ID and separate initial, enhancement and final request references, one at a time. If uploaded candidates are available, read back one candidate at a time for staff confirmation instead of asking for spelling again. Otherwise acknowledge each supplied identifier once and clarify only uncertainty. Do not recap all four together. After staff confirm all required references, immediately use claim911_report_references. If a reference is unavailable, report the blocker with claim911_report_update; never invent it. Do not investigate claims queries or infer hospital submission or claims receipt in this conversation.'
        return {'objective':append_common_closing(objective),
            'allowed_statement_predicates':['ACCESS_REFUSED'],'workflow':{'state':'HOSPITAL_REFERENCE_DISCOVERY','reported_facts_only':True}}
    if purpose=='QUERY_DISCOVERY':
        if row['reference']=='UNCONFIRMED_FINAL_REFERENCE':
            raise ValueError('Discover the final reference from the hospital before claims lookup')
        if w and (w.get('source_mode')!='SANDBOX_AUDIO' or w.get('documents') or w.get('approval') or w.get('receipt')):
            raise ValueError('Query already discovered; use the follow-up purpose')
        objective=f'This claims call concerns final request {row["reference"]} for {row["patient_id"]}. The greeting already asked whether an information request is outstanding; process the answer without repeating it. When uploaded_query_candidates is present, offer its query reference, claim reference, admission ID and enhancement reference ONE at a time using their provided spoken_readbacks, asking whether each is correct. Do not first ask staff to dictate a value already on the slip and then repeat it again. Acknowledge each confirmation briefly and move on without recapping old codes. Confirm the original discharge-request receipt date, time and timezone in ordinary speech, the exact required documents, and whether the enhancement is linked. Use claim911_report_query immediately after all required facts are confirmed. Preserve canonical values in tool arguments. An uploaded slip alone is not confirmation. If a field is unavailable or disputed, clarify once or report the blocker. Never invent a reference or record NOT_RECEIVED for an outstanding query. Ask one short question at a time.'
        if w:
            objective='The earlier claims call saved its report but did not finish verification. Reconfirm the existing report with staff; do not change its facts, original receipt time or target time. '+objective
        return {'objective':append_common_closing(objective),
                'workflow':{'state':'QUERY_RECONFIRMATION' if w else 'QUERY_NOT_YET_KNOWN','reported_query':w['query'] if w else None,'reported_facts_only':True},'allowed_statement_predicates':['ACCESS_REFUSED']}
    if not w:
        raise ValueError('Discover the claims query before task follow-ups')
    q=w['query'];refs=q['references']
    common=f'Final request {row["reference"]}, query {refs["query"]}, claim {refs["claim"]}, admission {q["admission_id"]}. '
    if purpose in DOCUMENT_PURPOSES:
        kind=DOCUMENT_PURPOSES[purpose]
        signature_rule=' Require the treating team signature; never sign it yourself.' if kind=='signed_discharge_summary' else ''
        objective=common+f'Your only document task is {kind}. Ask this hospital desk whether that document is ready, its exact identifier and revision. Preserve the exact identifier; version is separate and must never be appended to the identifier.{signature_rule} Immediately call claim911_report_document after staff confirm readiness and identifier, before saying it was noted or recorded. Previous reports do not count as a tool result for this call. If proof is missing, ask staff to upload this document and explain it remains pending. When staff confirm upload, call claim911_report_document again to check the uploaded proof. If the backend returns REFERENCE_CONFIRMATION_REQUIRED, ask staff to confirm the exact uploaded identifier and report again; do not silently substitute. Only announce linked or complete after that tool returns UPLOADED_DOCUMENT_CHECKED. If unavailable, use claim911_report_update for the stated blocker or agreed callback. Do not ask about documents owned by another desk or restart the broader query checklist. Close with only the backend-confirmed document status.'
    elif purpose=='PACKET_SUBMISSION':
        if not approval_valid(row,w):
            raise ValueError('Current exact packet approval required before hospital submission call')
        objective=common+'Ask hospital insurance staff to submit ONLY the displayed approved packet against the existing query and claim through their hospital portal. Do not create a new claim. Read back the query reference. Record their confirmed dispatch identifier with claim911_report_update. You cannot send documents, submit as hospital, approve a packet or verify recipient receipt. Close by saying receiving-side confirmation remains separate.'
    elif purpose=='TPA_QUERY_FOLLOWUP':
        if not w.get('receipt'):
            raise ValueError('Exact response receipt must be verified before query-closure follow-up')
        objective=common+'Ask claims staff whether the exact response packet answered the information request and whether the enhancement is linked to this claim. If either remains pending, ask staff to resolve the query and link the existing enhancement using the received response in their own institution system. Ask for the actual result before recording their confirmed status with claim911_report_update. Request the signed institution confirmation upload. Spoken closure is reported only; backend signature verification is required. Do not promise insurer approval.'
    elif purpose=='INSURER_FOLLOWUP':
        if not w.get('query_resolution'):
            raise ValueError('Verified query closure and enhancement linkage required')
        objective=common+'Ask the authorized insurer review desk whether the final decision has been issued. If pending, ask the reviewer whether the complete packet is eligible for their review now and request their own review and institution-issued decision. Never choose the outcome or amount yourself. Confirm its outcome, approved amount and reason. A short institution-issued business reference may be confirmed if provided; keep internal UUIDs in the evidence upload and do not ask staff to dictate or read them aloud. Record claim911_report_update and request the signed decision upload. Never decide coverage or change the institution outcome. If staff cannot review now, record their stated blocker or agreed callback without inventing a commitment.'
        if w.get('decision'):
            objective=common+'The signed institution-issued decision is already independently verified in workflow.decision. This follow-up must confirm its outcome and payable amount with the insurer desk, then record claim911_report_update. Do not ask for another review, reissue the decision, dictate internal UUIDs, or restart the earlier checklist. If the desk disputes the verified decision, record the discrepancy and stop for human review. Only the uploaded institution evidence establishes the decision.'
    elif purpose=='CAREGIVER_COMPLEX_UPDATE':
        objective='Explain the verified caregiver_summary in plain English, at most 55 words per turn. Do not speak identifiers, JSON fields or technical source names. Attribute facts naturally to the insurer or hospital. First explain receipt, insurer decision and administrative clearance, then ask to continue. In the next turn explain bill, insurer payable, patient share, deposit and balance. In the third turn explain refund due and that payment is unverified. Ask whether they have a question or need human help. Only after these short sections use claim911_report_update to record their confirmed question or handoff request. Do not promise a callback, decide coverage, request payment, say a refund was paid, or give clinical advice.'
    elif purpose=='DISCHARGE_FOLLOWUP':
        if not w.get('decision'):
            raise ValueError('Verified insurer decision required before final billing follow-up')
        objective=common+'Ask hospital billing to reconcile the institution-issued final decision, latest bill and deposit. Ask for discharge clearance, patient balance, refund due and refund payment status separately. Record claim911_report_update and request the signed reconciliation upload. Do not collect money, make payments or treat a refund due as paid.'
        if w.get('clearance'):
            objective=common+'The signed hospital reconciliation is already verified in workflow.clearance. Confirm the result with billing in three short sections: discharge clearance; final bill and balance; refund due and refund payment status. Use ordinary amount words, never a string of digits. The signed evidence retains insurer payable, patient share and deposit for the later caregiver explanation; do not repeat the entire earlier checklist here. Then record claim911_report_update. Do not ask billing to perform another reconciliation, collect money, pay a refund, or dictate internal UUIDs. Refund due and refund payment status remain separate. A disputed amount requires human review.'
    else:
        raise ValueError('Unsupported complex workflow purpose')
    return {'objective':append_common_closing(objective),'allowed_statement_predicates':['ACCESS_REFUSED'],
            'tool_policy':{'required_report_tool':'claim911_report_document' if purpose in DOCUMENT_PURPOSES else 'claim911_report_update',
                           'document_complete_requires':'UPLOADED_DOCUMENT_CHECKED' if purpose in DOCUMENT_PURPOSES else None,
                           'verbal_acknowledgment_is_not_a_saved_report':True},
            'workflow':{'caregiver_summary':caregiver_summary(row,w) if purpose=='CAREGIVER_COMPLEX_UPDATE' else None,'query_reference':refs['query'],'claim_reference':refs['claim'],'admission_id':q['admission_id'],
                        'original_received_at':q.get('received_at'),'target_at':q.get('target_at'),
                        'assigned_document_kind':DOCUMENT_PURPOSES.get(purpose),
                        'collected_document_kinds':[k for k in sorted(w['documents']) if purpose not in DOCUMENT_PURPOSES or k==DOCUMENT_PURPOSES[purpose]],
                        'reported_updates':[] if purpose=='CAREGIVER_COMPLEX_UPDATE' else [r for r in w.get('reports',[]) if purpose not in DOCUMENT_PURPOSES or r['purpose']==purpose],
                        'approval_current':approval_valid(row,w),'approved_packet':packet_for(row,w) if purpose=='PACKET_SUBMISSION' else None,
                        'receipt_verified':bool(w.get('receipt')),'query_completion_verified':bool(w.get('query_resolution')),
                        'decision':w.get('decision',{}).get('envelope') if purpose not in DOCUMENT_PURPOSES else None,
                        'clearance':w.get('clearance',{}).get('envelope') if purpose not in DOCUMENT_PURPOSES else None}}
