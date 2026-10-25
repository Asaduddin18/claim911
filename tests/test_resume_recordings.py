import json
from scripts.run_sandbox_workflow import preserved_bolna_conversations


def test_resume_retains_only_successful_calls_from_same_case_and_configuration(tmp_path):
 config={'transport':'BOLNA_WEBRTC','assistant_config_sha256':'reviewed'}
 passed={'call_id':'caregiver','archived':True,'provenance':'BOLNA_WEBRTC','assistant_config_sha256':'reviewed','semantic_dialogue_evaluation':{'conversation_quality_passed':True}}
 failed=passed|{'call_id':'failed-query','archived':False}
 report={'run_id':'same-case','provider_configuration':config,'failure':{'error_type':'RuntimeError'},'conversations':[passed,failed]}
 (tmp_path/'Claim911_Run_same-case_first.json').write_text(json.dumps(report))
 (tmp_path/'Claim911_Run_same-case_wrong-config.json').write_text(json.dumps(report|{'provider_configuration':{'assistant_config_sha256':'other'}}))
 (tmp_path/'Claim911_Run_other-case_first.json').write_text(json.dumps(report|{'run_id':'other-case'}))
 calls,sources=preserved_bolna_conversations(tmp_path,'same-case',config)
 assert [c['call_id'] for c in calls]==['caregiver']
 assert len(sources)==1


def test_gateway_rotation_retains_original_fingerprint_only_when_explicitly_reviewed(tmp_path):
 old={'transport':'BOLNA_WEBRTC','assistant_config_sha256':'old'}
 new=old|{'assistant_config_sha256':'new'}
 call={'call_id':'previous','archived':True,'provenance':'BOLNA_WEBRTC','assistant_config_sha256':'old','semantic_dialogue_evaluation':{'conversation_quality_passed':True}}
 (tmp_path/'Claim911_Run_case_original.json').write_text(json.dumps({'run_id':'case','provider_configuration':old,'conversations':[call]}))
 assert preserved_bolna_conversations(tmp_path,'case',new)[0]==[]
 retained,_=preserved_bolna_conversations(tmp_path,'case',new,{'old','new'})
 assert retained==[call] and retained[0]['assistant_config_sha256']=='old'
