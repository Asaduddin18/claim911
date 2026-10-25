from copy import deepcopy
from sandbox.release_evidence import screen,consecutive
from sandbox.actors import scenario_manifest
from sandbox.executor import PHASES


def evidence(n):
 keys=scenario_manifest()['checkpoints'];fp='a'*64
 return {'run_id':str(n),'incident_id':str(n),'started_at':f'2026-10-24T10:0{n}:00+00:00',
  'finished_at':f'2026-10-24T10:0{n}:59+00:00','state':'COMPLETED','full_case_completed':True,
  'scenario_faults':['unsigned_summary'],'verified_checkpoints':13,'required_checkpoints':13,'failure':None,'assistant_transport':'bolna-browser',
  'provider_configuration':{'transport':'BOLNA_WEBRTC','assistant_config_sha256':fp},
  'independent_evaluation':{'required_audio_provenance':'BOLNA_WEBRTC','fixture_audio_allowed':False,'passed':True,'incident_id':str(n),'checks':[
   {'checkpoint':k,'passed':True,'evidence_references':['synthetic:test']} for k in keys]},
  'conversations':[{'purpose':p,'followup':False,'archived':True,'provenance':'BOLNA_WEBRTC','assistant_config_sha256':fp,
   'semantic_dialogue_evaluation':{'conversation_quality_passed':True,'critical_failures':[]}}
   for p,_ in PHASES.values() if p]+[{'purpose':'RECORDS_DOCUMENT','followup':True,'archived':True,'provenance':'BOLNA_WEBRTC','assistant_config_sha256':fp,'semantic_dialogue_evaluation':{'conversation_quality_passed':True,'critical_failures':[]}}]}


def test_three_fresh_full_cases_and_same_configuration_required():
 reports=[evidence(n) for n in range(3)]
 assert consecutive(reports)['three_consecutive_full_cases_passed']
 reports[-1]['provider_configuration']['assistant_config_sha256']='b'*64
 assert not consecutive(reports)['three_consecutive_full_cases_passed']


def test_component_cannot_qualify_even_with_forged_completed_flag():
 r=evidence(0);r['execution_scope']='COMPONENT'
 assert not screen(r)['eligible']
 assert not consecutive([r,r,r])['three_consecutive_full_cases_passed']


def test_failed_latest_full_run_breaks_streak():
 reports=[evidence(n) for n in range(4)];reports[-1]['failure']={'error_type':'TimeoutError'}
 assert not consecutive(reports)['three_consecutive_full_cases_passed']


def test_missing_gate_or_conversation_quality_fails():
 for mutate in [lambda r:r['independent_evaluation']['checks'].pop(),
                lambda r:r['conversations'][0]['semantic_dialogue_evaluation'].update(conversation_quality_passed=False),
                lambda r:r['conversations'].clear()]:
  r=evidence(0);mutate(r);assert not screen(r)['eligible']


def test_one_resumed_case_is_never_three_fresh_cases():
 r=evidence(0)
 assert not consecutive([r,deepcopy(r),deepcopy(r)])['three_consecutive_full_cases_passed']


def test_fixture_tolerant_verification_never_qualifies():
 r=evidence(0);r['independent_evaluation']['fixture_audio_allowed']=True
 assert not screen(r)['eligible']


def test_case_without_required_complication_or_callback_is_not_release_eligible():
 for change in ['fault','callback']:
  report=evidence(0)
  if change=='fault':report['scenario_faults']=[]
  else:report['conversations']=[c for c in report['conversations'] if not c.get('followup')]
  assert 'UNSIGNED_SUMMARY_RECOVERY_REQUIRED' in screen(report)['reasons']
