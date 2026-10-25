"""Trusted, case-scoped institution operations for the complete synthetic runner.

Models and package workers receive function results, never credentials. Voice
reports are separate from proof uploads and independent verification endpoints.
"""
import json
from uuid import UUID
from sandbox.actors import InstitutionActor

DOCUMENT_ROLES={'billing':'itemized_bill','medical_records':'signed_discharge_summary','implant_store':'implant_invoice'}


class WorkflowServices:
 def __init__(self,core,institutions,*,incident_id,case_id,tokens,authorized):
  self.core=core;self.institutions=institutions;self.incident_id=str(UUID(str(incident_id)));self.case_id=str(UUID(str(case_id)))
  self._tokens=tokens;self.authorized=authorized;self.audit=[]
  for client in [core,institutions]:
   response=client.get('/health');response.raise_for_status()
   if response.json().get('environment')!='sandbox':raise PermissionError('Both services must use isolated sandbox storage')
  self._read_snapshot()

 def _check(self):
  if not self.authorized():raise PermissionError('Synthetic run authorization is no longer current')

 def snapshot(self):
  self._check();return self._read_snapshot()

 def _read_snapshot(self):
  response=self.core.get('/v1/incidents/'+self.incident_id);response.raise_for_status();data=response.json();i=data['incident']
  if not i['is_test'] or not i['consent_active'] or str(i['case_id'])!=self.case_id:
   raise PermissionError('Consented case-bound synthetic workflow required')
  return data

 def actor(self,role):
  self._check()
  issuer='hospital' if role in {'hospital_insurance','billing','medical_records','implant_store'} else 'insurer' if role=='insurer' else 'claims' if role=='tpa' else None
  if issuer is None:raise PermissionError('Institution role required')
  return InstitutionActor(role,self.case_id,self.institutions,self._tokens[issuer],authorize_dispatch=self._dispatch_allowed if role=='hospital_insurance' else None)

 def _upload(self,name,value,kind='other'):
  self.snapshot();response=self.core.post(f'/v1/incidents/{self.incident_id}/documents',
   files={'file':(name,json.dumps(value,sort_keys=True,separators=(',',':')).encode(),'application/json')},data={'kind':kind})
  response.raise_for_status();result=response.json()
  self.audit.append({'operation':'upload_institution_evidence','document_id':result['document_id'],'name':name})
  return result['document_id']

 def publish_document(self,role):
  self.snapshot()
  if role not in DOCUMENT_ROLES:raise PermissionError('Only the document-owning desk may publish this evidence')
  records=self.actor(role).execute('read_status')['documents']
  own=[d for d in records if d['owner']==role and d['kind']==DOCUMENT_ROLES[role]]
  if len(own)!=1 or not own[0]['ready']:raise ValueError('A current institution-released document is required')
  d=own[0]
  if d['patient_id']!=self.snapshot()['incident']['patient_id']:raise PermissionError('Institution document patient mismatch')
  return {'uploaded':True,'document_reference':d['id'],'revision':d['revision'],'document_id':self._upload(d['id']+'.json',d)}

 def release_summary(self):
  self.snapshot();result=self.actor('medical_records').execute('release_signed_summary');self._check()
  self.audit.append({'operation':'institution_summary_released','document_reference':result['id'],'signed':bool(result.get('signed_by'))})
  return result

 def _dispatch_allowed(self,args):
  w=self.snapshot().get('complex_workflow') or {};p=w.get('packet')
  return bool(w.get('approval_current') and p and set(args)=={'query_id','claim_id','reference','documents','idempotency_key'}
   and all(args[k]==p[k] for k in ['query_id','claim_id','reference','documents']))

 def dispatch(self,idempotency_key):
  w=self.snapshot().get('complex_workflow') or {};p=w.get('packet')
  if not w.get('approval_current') or not p:raise PermissionError('Current exact packet approval required')
  args={k:p[k] for k in ['query_id','claim_id','reference','documents']};args['idempotency_key']=str(UUID(str(idempotency_key)))
  result=self.actor('hospital_insurance').execute('dispatch_approved_packet',args);self._check()
  did=self._upload('hospital-dispatch.json',result,'dispatch')
  from coordinator.reference_evidence import hospital_dispatch_reference
  return {'dispatch_reference':hospital_dispatch_reference(result),'dispatch_document_id':did,'status':result['status'],'receipt_verified':False}

 def receive(self):
  data=self.snapshot();w=data.get('complex_workflow') or {}
  if not w.get('approval_current'):raise PermissionError('Packet approval changed before receiving-side verification')
  reports=[r for r in w.get('reports',[]) if r['purpose']=='PACKET_SUBMISSION' and r['details'].get('dispatch_reference')]
  if not reports:raise ValueError('Attributed hospital dispatch report required')
  reference=reports[-1]['details']['dispatch_reference'];dispatch=None
  for d in reversed(data['documents']):
   if d['kind']!='dispatch':continue
   response=self.core.get(f'/v1/incidents/{self.incident_id}/documents/{d["id"]}');response.raise_for_status();body=response.json()
   from coordinator.reference_evidence import hospital_dispatch_reference
   if hospital_dispatch_reference(body)==reference:dispatch=(d,body);break
  if not dispatch:raise ValueError('Uploaded proof matching the reported dispatch is required')
  receipt=self.actor('tpa').execute('acknowledge_packet',{'submission_id':dispatch[1]['id']});self._check()
  response=self.core.post(f'/v1/incidents/{self.incident_id}/complex/verify',json={'dispatch_document_id':str(dispatch[0]['id']),'receipt':receipt})
  response.raise_for_status();self.audit.append({'operation':'receiving_side_receipt_verified','receipt_id':receipt['envelope']['receipt_id']})
  return response.json()

 def _issue_and_verify(self,role,operation,endpoint,filename):
  self.snapshot();result=self.actor(role).execute(operation);self._check()
  did=self._upload(filename,result)
  response=self.core.post(f'/v1/incidents/{self.incident_id}/complex/'+endpoint,json={'document_id':str(did)})
  response.raise_for_status();self.audit.append({'operation':operation,'verified_endpoint':endpoint,'document_id':str(did)})
  return result

 def link_enhancement(self):return self._issue_and_verify('tpa','link_enhancement','query-resolution','tpa-resolution.json')
 def issue_decision(self):return self._issue_and_verify('insurer','issue_fixed_decision','decision','insurer-decision.json')
 def reconcile(self):return self._issue_and_verify('billing','reconcile','clearance','hospital-reconciliation.json')

 def approve_synthetic_packet(self,expected_hash):
  # This explicit fixture is outside the model's institution tools. It cannot be
  # used for a telephone call and never grants a real caregiver's permission.
  w=self.snapshot().get('complex_workflow') or {}
  if not w.get('packet') or w.get('packet_hash')!=expected_hash:raise PermissionError('Exact displayed synthetic packet changed')
  response=self.core.post(f'/v1/incidents/{self.incident_id}/complex/approve',json={'accepted':True,'packet_hash':expected_hash,
   'source':'SYNTHETIC_REHEARSAL_FIXTURE','confirmation':'Explicit synthetic caregiver fixture approves only this displayed case-bound packet for the synthetic TPA.'})
  response.raise_for_status();self.audit.append({'operation':'synthetic_caregiver_exact_packet_approved','packet_hash':expected_hash})
  return response.json()
