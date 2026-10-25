import copy
import pytest
from scripts.tune_bolna_turn_timing import timing_profile


def test_timing_profile_preserves_identity_prompt_voice_and_scoped_tools():
    agent={'agent_name':'Claim911 | Insurance Coordination Demo','agent_prompts':{'task_1':{'system_prompt':'Existing reviewed prompt'}},
           'tasks':[{'tools_config':{'transcriber':{'provider':'deepgram','model':'nova-3','endpointing':200},
                     'synthesizer':{'provider':'elevenlabs','voice_id':'reviewed-voice'},'api_tools':{'tools':['scoped-tool']}},
                    'task_config':{'incremental_delay':300,'optimize_latency':True,'number_of_words_for_interruption':2}}]}
    original=copy.deepcopy(agent);updated=timing_profile(agent)
    assert agent==original
    updated['tasks'][0]['tools_config']['transcriber']['endpointing']=200
    updated['tasks'][0]['task_config'].update(incremental_delay=300,optimize_latency=True)
    assert updated==original


def test_timing_profile_refuses_another_agent_or_unreviewed_transcriber():
    with pytest.raises(ValueError):timing_profile({'agent_name':'Another assistant','tasks':[{}]})
    with pytest.raises(ValueError):timing_profile({'agent_name':'Claim911 | Insurance Coordination Demo',
        'tasks':[{'tools_config':{'transcriber':{'provider':'another-provider'}}}]})


def test_simulation_timing_bounds_idle_wait_without_changing_conversation_authority():
    agent={'agent_name':'Claim911 | Insurance Coordination Demo','tasks':[{'tools_config':{
        'transcriber':{'provider':'deepgram'},'llm_agent':{'model':'existing'},'api_tools':{'tools':['scoped']}},'task_config':{}}]}
    result=timing_profile(agent,simulation=True)
    config=result['tasks'][0]['task_config']
    assert config['trigger_user_online_message_after']==45 and config['hangup_after_silence']==60
    assert config['call_terminate']==300
    assert result['tasks'][0]['tools_config']['llm_agent']==agent['tasks'][0]['tools_config']['llm_agent']
    assert result['tasks'][0]['tools_config']['api_tools']==agent['tasks'][0]['tools_config']['api_tools']
