"""Small human-facing projections of evidence events. Never expose raw payloads."""
EVENTS={
 'INTAKE_CREATED':('Getting started','Your request was saved'),
 'CONSENT_GRANTED':('Getting started','Investigation permission confirmed'),
 'FOLLOWUP_CANCELLED':('Follow-ups','A coordinator cancelled a waiting follow-up'),
 'CONSENT_REVOKED':('Permissions','Investigation permission withdrawn'),
 'CAREGIVER_INTAKE_REPORTED':('Getting started','Your concern was confirmed in conversation'),
 'HOSPITAL_REFERENCES_REPORTED':('Investigation','Hospital references were recorded'),
 'DOCUMENT_QUERY_RECORDED':('Investigation','The claims desk’s document request was recorded'),
 'DOCUMENT_UPLOADED':('Documents','A document was uploaded'),
 'QUERY_DOCUMENT_COLLECTED':('Documents','Hospital evidence was checked and linked'),
 'QUERY_PACKET_APPROVED':('Permissions','The exact document packet was approved'),
 'QUERY_PACKET_APPROVAL_REVOKED':('Permissions','Document sharing approval was withdrawn'),
 'QUERY_RESPONSE_RECEIPT_VERIFIED':('Claims review','The receiving claims desk confirmed the packet'),
 'TPA_QUERY_AND_ENHANCEMENT_VERIFIED':('Claims review','The TPA confirmed query completion and enhancement linkage'),
 'INSURER_DECISION_VERIFIED':('Outcome','An institution-issued insurer decision was verified'),
 'DISCHARGE_RECONCILIATION_VERIFIED':('Outcome','The hospital reconciliation was verified'),
 'SANDBOX_AUDIO_CONVERSATION_ARCHIVED':('Conversations','A synthetic audio conversation was archived'),
 'SANDBOX_AUDIO_CALL_ABORTED':('Conversations','An interrupted audio conversation was closed for review'),
}

CHECKPOINTS={
 'caregiver_intake_confirmed':'Caregiver concern confirmed',
 'hospital_references_reported':'Hospital references confirmed',
 'claims_query_discovered':'Claims query discovered',
 'bill_checked':'Revised bill checked',
 'signed_summary_checked':'Signed discharge summary checked',
 'implant_invoice_checked':'Implant invoice checked',
 'exact_packet_approved':'Exact document sharing approved',
 'hospital_dispatch_recorded':'Hospital dispatch recorded',
 'recipient_receipt_verified':'Receiving-side receipt verified',
 'query_and_enhancement_verified':'Query answered and enhancement linked',
 'insurer_decision_verified':'Insurer decision verified',
 'hospital_reconciliation_verified':'Hospital reconciliation verified',
 'caregiver_handoff_completed':'Caregiver handoff completed',
}


def activity(event):
 item=EVENTS.get(event['type'])
 if not item:return None
 return {'id':event['sequence'],'stage':item[0],'title':item[1],'at':str(event['created_at'])}


def financials(workflow):
 clearance=(workflow or {}).get('clearance')
 if not clearance:return None
 e=clearance['envelope']
 return {**{k:e[k] for k in ['bill_inr','insurer_payable_inr','patient_payable_inr','deposit_inr','balance_due_inr','refund_due_inr','discharge_clearance','refund_payment_state']},
         'source':{'issuer':e['source'],'kind':'hospital_reconciliation','id':e['decision_id']}}


def caregiver_progress(snapshot):
 """Project the current shared workflow gate, without implying active dispatch."""
 from coordinator.reasoning import propose
 row=snapshot['incident'];workflow=snapshot.get('complex_workflow') or {}
 if row['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:
  return {'status':'A coordinator needs to review this case','next_action':'Review the latest updates. Protected work remains on hold.','stage':0}
 if not row['consent_active']:
  return {'status':'Permission needed','next_action':'Allow Claim911 to investigate this case.','stage':0}
 clearance=workflow.get('clearance')
 if clearance:
  envelope=clearance['envelope']
  if envelope['discharge_clearance']=='ISSUED':
   return {'status':'Hospital administrative clearance confirmed',
           'next_action':'Review the verified reconciliation and any refund still due.','stage':3}
  return {'status':'A patient balance remains outstanding',
          'next_action':'Review the hospital reconciliation and confirm the next step with hospital billing.','stage':2}
 proposal=propose(snapshot)[0]
 messages={
  'hospital_references_reported':('Your request is saved','A coordinator needs to confirm the hospital’s request details.',0),
  'claims_query_discovered':('The reason for the hold needs confirmation','The next step is to ask the claims desk what is outstanding.',0),
  'bill_checked':('The corrected bill is still needed','Hospital billing owns the revised itemized bill. Review the document checklist.',1),
  'signed_summary_checked':('The signed discharge summary is still needed','The treating team must sign the summary before medical records can release it.',1),
  'implant_invoice_checked':('The implant invoice is still needed','The implant store owns this invoice. Review the document checklist.',1),
  'exact_packet_approved':('Your document-sharing approval is needed','Review the exact documents and recipient in Permissions before deciding.',1),
  'hospital_dispatch_recorded':('Your approved packet is ready for hospital submission','The hospital must submit the approved packet. Receiving-side receipt remains a separate check.',2),
  'recipient_receipt_verified':('The hospital reported dispatch; receipt is still unconfirmed','The receiving claims desk must independently confirm the exact packet.',2),
  'query_and_enhancement_verified':('The claims desk received your response','Query closure and enhancement linkage still need confirmation.',2),
  'insurer_decision_verified':('The insurer’s decision is still pending verification','An institution-issued decision is needed before final hospital reconciliation.',2),
  'hospital_reconciliation_verified':('The insurer’s decision has been verified','Hospital billing still needs to reconcile the decision, bill and deposit.',2),
 }
 status,next_action,stage=messages.get(proposal.expected_checkpoint,('A coordinator needs to review the next step','Review the latest activity for unresolved items.',0))
 return {'status':status,'next_action':next_action,'stage':stage}
