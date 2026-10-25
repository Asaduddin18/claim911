"""Bind a prepared run without exposing institution credentials or hidden facts."""
from sandbox import runs

LEGACY_PROVIDER={'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'}


def bind(conn,run_id,*,core,institutions,seed_token,provider_configuration=None):
 row=runs.get(conn,run_id,True)
 if row['state']!='PREPARED':return row
 for client in [core,institutions]:
  health=client.get('/health');health.raise_for_status()
  if health.json().get('environment')!='sandbox':raise PermissionError('Isolated sandbox services required')
 seed=institutions.post('/sandbox/scenarios/'+str(run_id),headers={'Authorization':'Bearer '+seed_token},json={'faults':row['faults']});seed.raise_for_status();seed=seed.json()
 if not seed.get('synthetic') or str(seed['case_id'])!=str(run_id):raise PermissionError('Seed identity mismatch')
 intake=core.post('/v1/intakes',headers={'Idempotency-Key':'sandbox-'+str(run_id)},json={
  'case_id':seed['case_id'],'patient_id':seed['patient_id'],'reference_known':False,'title':'Synthetic audio discharge coordination'})
 intake.raise_for_status();incident_id=intake.json()['incident_id']
 consent=core.post('/v1/incidents/'+incident_id+'/consent',json={'accepted':True,
  'confirmation':'Explicit synthetic caregiver fixture permits this isolated rehearsal. Exact document disclosure is approved separately. No telephone calls are permitted.'})
 consent.raise_for_status()
 return runs.attach_case(conn,run_id,incident_id=incident_id,institution_case_id=seed['case_id'],
                         provider_configuration=provider_configuration or LEGACY_PROVIDER)
