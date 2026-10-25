"""Seeded, role-bounded replies for repeatable synthetic conversations.

Only the owning institution's scoped read result is accepted. Replies address
the assistant's latest question, use natural language and never write
coordinator facts or claim a receiving-side outcome.
"""
import re
from datetime import datetime
from sandbox.spoken_identifiers import normalize_identifier_speech

from sandbox.readback_confirmation import CODE as IDENTIFIER


def latest_question(history):
 if not history or history[-1].get('role') not in {'user','assistant'}:
  return ''
 text=history[-1].get('content')
 if not isinstance(text,str):return ''
 text=text.strip().lower()
 # "Enhancement request reference" and "enhancement reference" name the
 # same subject. Normalize that grammar for every reference family.
 text=re.sub(r'\b(enhancement|initial|final|query|claim)\s+request\s+(reference|number|identifier|id)\b',r'\1 \2',text)
 # An acknowledgement can contain an old code before a new request, even
 # when ASR omits its punctuation. Scope the reply to the new request.
 transitions=list(re.finditer(r'\b(?:now|next|finally|instead)\b[,:]?\s*',text))
 if transitions and transitions[-1].end()<len(text):
  text=text[transitions[-1].end():].strip()
 questions=re.findall(r'[^.!?]*\?',text)
 if questions:
  latest=questions[-1].strip()
  # A bare confirmation refers to the preceding readback. Other questions
  # should not inherit subjects from an earlier acknowledgement or question.
  if not re.fullmatch(r'(?:is (?:that|this|it|all of that) (?:the )?(?:right|correct)(?: (?:initial|enhancement|final|claim|query|request|admission|reference|identifier|id|number|spelling)){0,5}|are (?:those|these|all of those)(?: (?:references|identifiers|values|details|numbers))? (?:right|correct)|can you confirm(?: that| these| those)?)\?',latest):
   return latest
 return text


class ScriptedDesk:
 def __init__(self,role,record):
  if role not in {'caregiver','hospital_insurance','billing','medical_records','implant_store','tpa','insurer'}:raise ValueError('Scripted role not implemented')
  self.role=role;self.record=record

 def reply(self,history):
  question=latest_question(history)
  if not question:return 'I can check that for you. Which reference or document are you asking about?'
  record=self.record;refs=record.get('references',{})
  if record.get('available') is False:
   return record.get('availability_reason') or 'The responsible staff member is unavailable. I cannot confirm a completed action.'
  own_kind={'billing':'itemized_bill','medical_records':'signed_discharge_summary','implant_store':'implant_invoice'}.get(self.role)
  own=next((d for d in record.get('documents',[]) if d.get('kind')==own_kind),None) if own_kind else None
  other_reference=any(x in question for x in ('admission','claim reference','query reference','final request','initial approval','enhancement reference'))
  if own and not other_reference and any(x in question for x in ('identifier','reference','revision','version','document id')):
   if not own.get('ready'):
    return 'The document has not been released yet. I cannot confirm a released document reference.'
   if not own.get('id') or own.get('revision') is None:
    return 'I cannot confirm the exact document reference and revision from this record.'
   known_other={str(record.get('patient_id','')).casefold(),str(record.get('admission_id','')).casefold()}
   heard={value.casefold() for value in IDENTIFIER.findall(question)}-known_other
   if any(x in question for x in ('correct','right','match','confirm')) and heard and heard!={own['id'].casefold()}:
    return 'That document reference differs from our record. The exact reference is '+own['id']+'.'
   return f"The document reference is {own['id']}, revision {own['revision']}. It has been released."
  if self.role=='caregiver':
   if any(x in question for x in ('which language','what language','language do you prefer','speak english')):
    return 'English, please.'
   if any(x in question for x in ('shall i continue','should i continue','may i continue','can i continue','like me to continue','like to continue','ready for the next','like to hear the next')):
    return 'Yes, please continue.'
   if record.get('verified_update') and any(x in question for x in ('any questions','a question','human help','anything else')):
    return 'No more questions right now. Please leave the confirmed summary in the app.'
   if any(x in question for x in ('what is holding','what happened','what do you know','why is discharge')):
    return 'The family is ready to leave, but the hospital says final insurance clearance is pending and we need help finding out why.'
   if any(x in question for x in ('consent','permission','may we investigate','agree to proceed','proceed with this coordination','synthetic demonstration')):
    return 'Yes, I agree to investigate this synthetic case.'
   if any(x in question for x in ('document','information','waiting for','what is missing','what\'s missing')):
    return 'They have not told us what is missing, so please check with the hospital and insurer for us.'
   if (any(x in question for x in ('ask the hospital','ask the insurer','contact the hospital','contact the insurer','check with the hospital','check with the insurer'))
       or re.search(r'\b(?:find out|investigate|look into|check)\b.{0,100}\b(?:reason|hospital|insurer|clearance|hold)\b',question)):
    return 'Yes, please check with them for us because we do not know which approval is still pending.'
   if any(x in question for x in ('is that right','is that correct','still ready','ready to leave')):
    return 'Yes, the family is ready to leave. We are waiting for the hospital to explain the insurance hold.'
   if question.strip(' .!') in {'thanks','thank you','thanks for clarifying','i understand','got it'}:
    return 'That is right, we do not know what is missing yet, so please check with the hospital and insurer.'
   if any(x in question for x in ('how are you feeling','anything else','would you like a summary','next steps')):
    return 'Please explain what has been confirmed, what is still waiting, and whether any refund is actually paid.'
   return 'I did not understand which detail you need. Could you ask that again?'
  if self.role=='billing':
   docs=record.get('documents',[]);bill=next((d for d in docs if d.get('kind')=='itemized_bill'),None)
   if any(x in question for x in ('duplicate','double charge','bill version','revised bill','corrected bill','bill total','itemized bill')):
    if not bill:return 'I cannot confirm a revised bill from this billing record. Please check with the billing team.'
    amount=bill.get('amount_inr')
    revision=bill.get('revision')
    if amount is not None:return f'The current itemized bill is revision {revision}, for INR {amount:,}. The duplicate charge has been removed.'
    return f'The current itemized bill is revision {revision} and is {"ready" if bill.get("ready") else "still being corrected"}.'
   if any(x in question for x in ('deposit','refund','paid already')):
    amount=record.get('deposit_inr')
    if amount is not None:return f'I can confirm an INR {amount:,} deposit in the billing record. Any refund amount depends on the final reconciliation.'
   return 'I can confirm the bill and deposit recorded by billing. Which one would you like me to check?'
  if self.role=='medical_records':
   doc=next((d for d in record.get('documents',[]) if d.get('kind')=='signed_discharge_summary'),None)
   if any(x in question for x in ('signature','signed','discharge summary','summary')):
    if doc and doc.get('ready'):
     suffix=f" Its reference is {doc['id']}, revision {doc['revision']}." if doc.get('id') and doc.get('revision') is not None else ''
     return 'The signed discharge summary has been released by medical records.'+suffix
    return 'The discharge summary is waiting for the treating team to sign it. Medical records cannot sign on the clinician’s behalf.'
   return 'I can check the discharge summary. It needs the treating team’s signature before medical records can release it.'
  if self.role=='implant_store':
   doc=next((d for d in record.get('documents',[]) if d.get('kind')=='implant_invoice'),None)
   if any(x in question for x in ('implant','invoice','device')):
    if doc and doc.get('ready'):
     suffix=f" Its reference is {doc['id']}, revision {doc['revision']}." if doc.get('id') and doc.get('revision') is not None else ''
     return 'The implant invoice is available in the implant store record and matches this admission.'+suffix
    return 'I cannot release the implant invoice yet. The admission and issue record need to match first.'
   return 'I can check the implant invoice against its admission and issue record. What would you like me to confirm?'
  if self.role=='insurer':
   decision=record.get('decision')
   if any(x in question for x in ('decision','approved','authorization','authorisation','payable','coverage')):
    if decision:
     amount=decision.get('payable_inr')
     return f'The insurer record shows {decision.get("outcome", "a decision")}' + (f' with INR {amount:,} payable.' if amount is not None else '.')
    return 'The insurer has not issued a final decision. The current packet and enhancement linkage still need review.'
   return 'I can check the insurer review. A final decision is shown only after it is issued in the insurer record.'
  # Prefer the most specific subject. Initial and final authorization remain
  # distinct and the TPA query reference is never substituted for either.
  if self.role=='tpa':
   if any(x in question for x in ('required document','which document','what document','documents do you need','documents are needed','what do you require')):
    if record.get('query_state')=='ANSWERED':return 'The query has been answered. Our record shows no outstanding document request.'
    names={'itemized_bill':'revised itemized bill','itemized_bill_v2':'revised itemized bill','signed_discharge_summary':'signed discharge summary','implant_invoice':'implant invoice'}
    required=record.get('required_documents',[])
    if not required or any(kind not in names for kind in required):return 'I cannot confirm the exact document list from this record.'
    return 'We still need '+', '.join(names[kind] for kind in required)+'.'
   if any(x in question for x in ('original request','when did','what time','received at','received on','arrival time','date and time')):
    at=datetime.fromisoformat(record['received_at']);offset=at.strftime('%z')
    zone='UTC '+offset[:3]+':'+offset[3:] if offset else 'UTC'
    return 'The original discharge request arrived on '+at.strftime('%d %B %Y at %H:%M')+' '+zone+'.'
   if any(x in question for x in ('enhancement linked','linked to the claim','link the enhancement')):
    if record.get('enhancement_linked') is True:return 'Yes. The enhancement is linked to the claim in our record.'
    if record.get('enhancement_linked') is False:return 'No. The enhancement is not linked to the claim yet.'
    return 'I cannot confirm the enhancement linkage from this record.'
   if any(x in question for x in ('outstanding','information request','query status','query open','query closed','closed','answered','resolved')):
    if record.get('query_state')=='ANSWERED':
     return 'The query has been answered.'+(' The enhancement is linked to the claim.' if record.get('enhancement_linked') is True else ' Enhancement linkage still needs a separate check.')
    if record.get('query_state')=='OPEN':
     return 'The query is still open and remains outstanding.'+(' The enhancement is not linked.' if record.get('enhancement_linked') is False else '')
    return 'I cannot confirm the query status from this record. Could you check with the claims team?'
  if self.role=='hospital_insurance' and any(x in question for x in ('receiving','receipt','reach the claims','arrive at claims')):
   return 'I can confirm the hospital record, but the claims desk has to verify its own receipt.'
  if self.role=='hospital_insurance' and any(x in question for x in ('dispatch','submitted','submission')):
   dispatches=record.get('dispatches',[])
   if not dispatches:return 'Our hospital record shows the final response packet has not been submitted yet.'
   latest=dispatches[-1]
   return f"Our hospital record shows the packet was submitted as {latest.get('id', 'a recorded dispatch')}. The claims desk still needs to confirm receipt."
  fields=(
   (('query reference','query identifier','query number','query id'), 'query reference',refs.get('query')),
   (('claim reference','claim identifier','claim number','claim id'), 'claim reference',refs.get('claim')),
   (('admission id','admission identifier','admission number'), 'admission ID',record.get('admission_id')),
   (('enhancement reference','enhancement identifier','enhancement number'), 'enhancement reference',refs.get('enhancement')),
   (('final request','final authorization','final reference','final'), 'final request reference',refs.get('final_request')),
   (('initial approval','preauthorization','pre-authorization','initial'), 'initial approval reference',refs.get('preauthorization')),
  )
  if any(x in question for x in ('correct','right reference','match our record','read that back','read-back','spelling')):
   heard={value.casefold() for value in IDENTIFIER.findall(normalize_identifier_speech(question)) if value.casefold()!=str(record.get('patient_id','')).casefold()}
   known={value.casefold() for _,_,value in fields if value}
   if heard:
    required={value.casefold() for markers,_,value in fields if value and any(marker in question for marker in markers)}
    if not heard<=known:return 'That reference differs from what I see. Could you check it once more?'
    if required and not required<=heard:return 'I cannot confirm the complete readback. One of the requested references is missing; please check it separately.'
    return 'Yes, that is the correct reference.'
  requested=[(label,value) for markers,label,value in fields
             if value and any(marker in question for marker in markers)]
  if len(requested)>1:return 'Could you ask me about one identifier at a time?'
  if requested:
   label,value=requested[0]
   return 'The '+label+' is '+value+'.'
  if self.role=='tpa' and any(x in question for x in ('reference','identifier','number')):
   return 'Which one do you need, the query reference, claim reference or admission ID?'
  return 'I can check that. Are you asking about the final request or the earlier approval?'
