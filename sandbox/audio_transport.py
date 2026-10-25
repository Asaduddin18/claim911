"""Real Pipecat conversation adapter for the complete sandbox executor."""
import json
from pathlib import Path
from uuid import uuid4
from coordinator.model_tools import ScopedToolModel
from sandbox.audio_gateway import AudioGateway
from sandbox.conversations import converse
from sandbox.participant_model import DeskParticipant
from sandbox.scripted_desks import ScriptedDesk
from sandbox.actors import initial_knowledge
from sandbox.spend import reserve,settle

DOCUMENT_PURPOSES={'BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT'}


def caregiver_intake_reply(history):
 question=history[-1]['content'].lower() if history and isinstance(history[-1].get('content'),str) else ''
 if any(term in question for term in ('preferred language','which language','what language','language for updates')):
  return 'English is fine, thank you.'
 if any(term in question for term in ('permission to investigate','may i investigate','consent to investigate','permission to look into')):
  return 'Yes, you can investigate this synthetic case. Please ask me separately before sharing any documents.'
 if any(term in question for term in ('document sharing','share documents','share your documents','disclose documents')):
  return 'Please show me which documents and who would receive them before I decide.'
 if any(term in question for term in ('is that your concern','did i understand','have i understood','is that right')):
  return 'Yes. We are ready to leave, but the hospital says insurance clearance is still pending.'
 if any(term in question for term in ('what is holding','what happened','tell me about','what help do you need','what is your concern')):
  return 'We are ready to leave, but the hospital says insurance clearance is still pending. I need help finding what is missing.'
 return 'I can explain. Are you asking about the discharge delay or permission to investigate?'


def caregiver_handoff_reply(history):
 question=history[-1]['content'].lower() if history and isinstance(history[-1].get('content'),str) else ''
 if any(term in question for term in ('refund','paid','payment')):
  return 'Thanks. Please keep the amount due separate from any payment that has actually been made.'
 if any(term in question for term in ('anything else','any other question','would you like me to explain')):
  return 'That covers it. Please leave the refund payment as unconfirmed until there is proof.'
 if any(term in question for term in ('patient share','balance','deposit','final bill','insurer amount')):
  return 'Please show the final bill, insurer amount, patient share, deposit and any remaining balance together.'
 return 'Could you summarize what is verified and what still needs follow-up?'


def document_report_complete(audit,*,requires_release=False):
 # A confirmed unavailable document ends this conversation, not the checkpoint.
 # The executor schedules its callback and still requires owning-desk evidence.
 if requires_release:return any(a['result'].get('reported_document_result')=='UPLOADED_DOCUMENT_CHECKED' for a in audit)
 return any(a['tool']=='claim911_report_update' or
  (a['tool']=='claim911_report_document' and a['arguments'].get('ready') is False) or
  a['result'].get('reported_document_result')=='UPLOADED_DOCUMENT_CHECKED' for a in audit)


def institution_report_complete(audit,workflow,key,after_operation=0):
 return bool(workflow.get(key)) and len(audit)>after_operation and audit[-1]['tool']=='claim911_report_update'


class AudioConversation:
 def __init__(self,*,core,services,provider,db,run_id,language,journal_root,participant_mode='scripted'):
  if participant_mode not in {'scripted','adaptive'}:raise ValueError('Known participant mode required')
  self.core=core;self.services=services;self.provider=provider;self.db=db;self.run_id=str(run_id)
  self.language=language;self.journal_root=Path(journal_root);self.participant_mode=participant_mode;self.reports=[]
  self.journal_root.mkdir(mode=0o700,parents=True,exist_ok=True)

 def __call__(self,*,purpose,role,operations,followup,authorized):
  if not authorized():raise PermissionError('Current run permission required')
  incident=self.services.snapshot()['incident'];id=str(incident['id']);case=str(incident['case_id']);version=incident['consent_version']
  language=self.language if role=='caregiver' else 'en';active={'report_after_operation':0}
  opened=self.core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':purpose,'audio_provenance':'PIPECAT_STDIO'});opened.raise_for_status();call=opened.json()
  journal=self.journal_root/str(call['call_id']);gateway=None
  def permitted(r,c,v):return r==self.run_id and c==case and v==version and authorized()
  def reserve_cost(request_id,run_id,operation):
   if not authorized():raise PermissionError('Run permission changed')
   with self.db() as db:
    reservation=reserve(db,request_id=request_id,run_id=run_id,phase='development',operation=operation,maximum_micro=100000)
    if not reservation['new_reservation']:raise RuntimeError('Prior provider operation requires reconciliation')
   active['request_id']=request_id
  def settle_cost(request_id):
   with self.db() as db:settle(db,request_id)
  def persona_invoke(messages,tools):
   request_id=str(uuid4());reserve_cost(request_id,self.run_id,'persona')
   try:return self.provider.request('reply',{'messages':messages,'tools':tools},reservation_id=request_id)
   finally:settle_cost(request_id)
  def save_turn(value):
   active['completed_turns']=value['pipecat_turns']
   temporary=journal.with_suffix('.tmp');temporary.write_text(json.dumps(value));temporary.chmod(0o600);temporary.replace(journal)
  def archive(turns,*,completed):
   response=self.core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':turns,'outcome':'COMPLETED' if completed else 'INTERRUPTED'});response.raise_for_status();return response.json()
  try:
   bridge=ScopedToolModel(self.core,call['call_token'],lambda messages,tools:self.provider.request('reply',{'messages':messages,'tools':tools},reservation_id=active['request_id']),authorized=authorized,language=language)
   gateway=AudioGateway(speech=self.provider,model=bridge,reserve_cost=reserve_cost,finish_cost=settle_cost,consent_active=permitted)
   context='Follow only the current desk objective. Use uploaded proof for exact reference read-backs and obtain spoken confirmation. Institution outcomes require independent verification.'
   if followup:context+=' This is the scheduled records follow-up. Ask the desk to follow up with the treating team, then upload its institution-released signed summary. You cannot sign it yourself.'
   capability=gateway.issue(run_id=self.run_id,case_id=case,role=role,language=language,consent_version=version,context=context,ttl=600)
   if role=='caregiver':
    if purpose=='CAREGIVER_INTAKE':
     greeting=('मैं देखभाल करने वाला हूँ। मरीज छुट्टी के लिए तैयार है, लेकिन अस्पताल कहता है कि बीमा मंजूरी बाकी है। यही मेरी परेशानी है।' if language=='hi' else 'I am the caregiver and prefer English updates. We are medically ready for discharge, but the hospital says insurance approval is pending. I confirm this concern.')
     actor_reply=caregiver_intake_reply
    else:
     greeting='कृपया हमें अंतिम स्थिति समझाएं।' if language=='hi' else 'Please explain the verified outcome and anything still unconfirmed.'
     actor_reply=caregiver_handoff_reply
   else:
    actor=self.services.actor(role);desk=actor.execute('read_status')
    if purpose=='HOSPITAL_REFERENCE_DISCOVERY':
     self.services._upload('hospital-reference-slip.json',{'kind':'hospital_reference_slip','case_id':case,'patient_id':desk['patient_id'],'admission_id':desk['admission_id'],'references':desk['references'],'synthetic':True})
    elif purpose=='QUERY_DISCOVERY':
     q=desk['references'];self.services._upload('claims-query-slip.json',{'kind':'claims_query_slip','case_id':case,'patient_id':desk['patient_id'],'final_reference':q['final_request'],
      'details':{'query_reference':q['query'],'claim_reference':q['claim'],'admission_id':desk['admission_id'],'enhancement_reference':q['enhancement'],'received_at':desk['received_at'],'required_documents':desk['required_documents'],'enhancement_linked':desk['enhancement_linked']}})
    if purpose in {'HOSPITAL_REFERENCE_DISCOVERY','QUERY_DISCOVERY'} and self.participant_mode=='scripted':
     participant=ScriptedDesk(role,desk);actor_reply=participant.reply
    else:
     def tracked(operation):
      def execute():
       result=operation();active['report_after_operation']=len(bridge.audit);return result
      return execute
     participant=DeskParticipant(actor,persona_invoke,authorized=authorized,brief=initial_knowledge(role)['knowledge'],operations={name:tracked(operation) for name,operation in operations.items()});actor_reply=participant.reply
    greeting='This is the synthetic '+role.replace('_',' ')+' desk. How can I help?'
   def done():
    if purpose=='HOSPITAL_REFERENCE_DISCOVERY':return any(a['tool']=='claim911_report_references' for a in bridge.audit)
    if purpose=='QUERY_DISCOVERY':return any(a['tool']=='claim911_report_query' for a in bridge.audit)
    if purpose in DOCUMENT_PURPOSES:
     return document_report_complete(bridge.audit,requires_release=purpose=='RECORDS_DOCUMENT' and followup)
    if purpose=='PACKET_SUBMISSION':return any(a['arguments'].get('dispatch_reference') and a['result'].get('recorded') is True for a in bridge.audit)
    if purpose=='CAREGIVER_COMPLEX_UPDATE':return active.get('completed_turns',0)>=4 and any(a['tool']=='claim911_report_update' for a in bridge.audit)
    if purpose in {'TPA_QUERY_FOLLOWUP','INSURER_FOLLOWUP','DISCHARGE_FOLLOWUP'}:
     key={'TPA_QUERY_FOLLOWUP':'query_resolution','INSURER_FOLLOWUP':'decision','DISCHARGE_FOLLOWUP':'clearance'}[purpose]
     return institution_report_complete(bridge.audit,self.services.snapshot().get('complex_workflow',{}),key,active['report_after_operation'])
    return any(a['tool']=='claim911_report_update' for a in bridge.audit)
   result=converse(gateway=gateway,capability=capability,speech=self.provider,actor_reply=actor_reply,initial_text=greeting,language=language,done=done,max_turns=16 if purpose=='QUERY_DISCOVERY' else 12,on_turn=save_turn,on_progress=save_turn)
   archive(result['turns'],completed=result['completed_objective'])
   if not result['completed_objective']:raise RuntimeError('Conversation exhausted its bounded turns without the required report')
   report={'call_id':call['call_id'],'purpose':purpose,'role':role,'language':language,'archived':True,'provenance':'PIPECAT_STDIO',
    'participant_mode':self.participant_mode if purpose in {'HOSPITAL_REFERENCE_DISCOVERY','QUERY_DISCOVERY'} else 'ADAPTIVE_INSTITUTION' if role!='caregiver' else 'SCRIPTED_CAREGIVER',
    'pipecat_turns':result['pipecat_turns'],'tool_audit':bridge.audit,'provider_image':self.provider.image_id,'model_settings':{'model':'gpt-5-mini','reasoning_effort':'low','max_completion_tokens':2048},
    'conversation':[{k:v for k,v in turn.items() if k!='pcm_base64'} for turn in result['turns']]}
   self.reports.append(report);return report
  except Exception:
   if journal.exists():
    interrupted=json.loads(journal.read_text());pending=interrupted.get('pending',{});turns=list(interrupted['turns'])
    if pending.get('recognized_text') and pending.get('pcm_base64'):
     turns.append({'speaker':'participant','text':pending['recognized_text'],'pcm_base64':pending['pcm_base64']})
    interrupted['tool_audit']=bridge.audit if 'bridge' in locals() else []
    save_turn(interrupted)
    recovery=self.core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':turns,'outcome':'INTERRUPTED'})
    if recovery.status_code!=200:self.core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/abort')
   else:self.core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/abort')
   raise
  finally:
   if gateway:gateway.revoke_run(self.run_id)
