"""Bounded uploaded reference candidates, never silently substituted as facts."""
import json,re
from uuid import UUID
from coordinator.identifier_readbacks import readbacks


def candidate_report_conflicts(report, choices):
 """Detect cross-field substitutions without treating an upload as verified truth.

 A mismatch blocks a write for clarification or review. It never replaces the
 participant's report with an uploaded value. Each candidate is one whole slip.
 """
 if not choices:return []
 differences=[[key for key,value in report.items() if choice.get(key)!=value]
              for choice in choices]
 return [] if any(not fields for fields in differences) else min(differences,key=len)


def hospital_dispatch_reference(value):
 """Institution-issued spoken reference, with legacy UUID compatibility."""
 internal_id=str(UUID(value['id']))
 reference=value.get('submission_reference')
 if reference is not None:
  if not isinstance(reference,str) or not re.fullmatch(r'HSP[0-9]{2,4}',reference):
   raise ValueError('Invalid institution submission reference')
  return reference
 return internal_id


def dispatch_candidates(conn,incident):
 result=[]
 for row in conn.execute("SELECT id,data FROM coordinator.documents WHERE incident_id=%s AND kind='dispatch' ORDER BY created_at DESC LIMIT 10",(incident['id'],)):
  try:
   raw=bytes(row['data'])
   if len(raw)>16000:continue
   value=json.loads(raw);packet=value['packet'];reference=hospital_dispatch_reference(value)
   if packet['case_id']!=str(incident['case_id']) or packet['patient_id']!=incident['patient_id'] or packet['reference']!=incident['reference']:continue
   result.append({'document_id':str(row['id']),'dispatch_reference':reference,'spoken_readbacks':readbacks({'dispatch_reference':reference}),'support_status':'UPLOADED_UNVERIFIED'})
   if len(result)==2:break
  except (ValueError,KeyError,TypeError):continue
 return result


def candidates(conn,incident):
 rows=conn.execute('SELECT id,data FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at DESC LIMIT 30',(incident['id'],)).fetchall()
 result=[]
 for row in rows:
  try:
   raw=bytes(row['data'])
   if len(raw)>16000:continue
   value=json.loads(raw);references=value.get('references',{})
   if value.get('kind')!='hospital_reference_slip' or value.get('case_id')!=str(incident['case_id']) or value.get('patient_id')!=incident['patient_id']:continue
   if set(references)!={'preauthorization','enhancement','final_request'}:continue
   if not all(isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/-]{0,99}',v) for v in [value.get('admission_id')]+list(references.values())):continue
   result.append({'document_id':str(row['id']),'admission_id':value['admission_id'],'references':references,
    'spoken_readbacks':readbacks({'admission_id':value['admission_id'],**references}),
    'support_status':'UPLOADED_UNVERIFIED','instruction':'These are uploaded candidates. Read each relevant identifier back and obtain staff confirmation before a report. Do not silently substitute a candidate for ambiguous speech.'})
   if len(result)==2:break
  except (ValueError,TypeError,AttributeError):continue
 return result


def query_candidates(conn,incident):
 from coordinator.complex import QueryReport
 from datetime import datetime
 rows=conn.execute('SELECT id,data FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at DESC LIMIT 30',(incident['id'],)).fetchall()
 result=[]
 for row in rows:
  try:
   raw=bytes(row['data'])
   if len(raw)>16000:continue
   v=json.loads(raw)
   if v.get('kind')!='claims_query_slip' or v.get('case_id')!=str(incident['case_id']) or v.get('patient_id')!=incident['patient_id'] or v.get('final_reference')!=incident['reference']:continue
   report=QueryReport.model_validate(v['details']);d=report.model_dump()
   if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/-]{0,99}',d[k]) for k in ['query_reference','claim_reference','admission_id','enhancement_reference']):continue
   if datetime.fromisoformat(d['received_at'].replace('Z','+00:00')).tzinfo is None:continue
   if set(d['required_documents'])!={'itemized_bill','signed_discharge_summary','implant_invoice'}:continue
   result.append({'document_id':str(row['id']),'details':d,'spoken_readbacks':readbacks({key:d[key] for key in ('query_reference','claim_reference','admission_id','enhancement_reference')}),'support_status':'UPLOADED_UNVERIFIED',
    'instruction':'Confirm the outstanding query and current requirements with this claims desk. Preserve the original receiving instant; uploaded proof does not establish receipt of a new packet or insurance approval.'})
   if len(result)==2:break
  except (ValueError,TypeError,AttributeError,KeyError):continue
 return result


def document_candidates(conn,incident,kind,owner,admission):
 result=[]
 for row in conn.execute('SELECT id,data FROM coordinator.documents WHERE incident_id=%s ORDER BY created_at DESC LIMIT 30',(incident['id'],)).fetchall():
  try:
   raw=bytes(row['data'])
   if len(raw)>16000:continue
   v=json.loads(raw)
   if v.get('kind')!=kind or v.get('owner')!=owner or v.get('patient_id')!=incident['patient_id'] or v.get('admission_id')!=admission:continue
   if not isinstance(v.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/-]{0,99}',v['id']):continue
   result.append({'document_id':str(row['id']),'document_reference':v['id'],'spoken_readbacks':readbacks({'document_reference':v['id']}),'revision':v.get('revision'),'ready':v.get('ready'),
    'signature_present':bool(v.get('signed_by')),'support_status':'UPLOADED_UNVERIFIED',
    'instruction':'Ask the owning desk to confirm this exact identifier and readiness. Keep the revision separate. This upload alone does not verify the institution record.'})
   if len(result)==2:break
  except (ValueError,TypeError,AttributeError):continue
 return result
