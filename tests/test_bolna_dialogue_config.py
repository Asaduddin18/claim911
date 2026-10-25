import copy,json
from scripts.configure_bolna import tool_config
from scripts.update_bolna_dialogue_prompt import prepare_dialogue_config,prepare_gateway_config,prepare_efficient_model
from coordinator.voice_contracts import COMMON_CALL_CLOSING_NOTE


def test_dialogue_update_preserves_provider_transport_voice_and_unrelated_tools():
    original={'tasks':[{'tools_config':{'api_tools':tool_config('https://synthetic.example.invalid','private-test'),
        'llm_agent':{'model':'gpt-4.1-nano','max_tokens':200},'synthesizer':{'voice':'reviewed'}},
        'task_config':{'hangup_after_silence':30}}], 'webhook_url':'https://synthetic.example.invalid/voice/webhook'}
    # Reproduce the older installed report schema.
    report=next(t for t in original['tasks'][0]['tools_config']['api_tools']['tools'] if t['name']=='claim911_report_update')
    for key in ('dispatch_reference','callback_at'):
        report['parameters']['properties'].pop(key);report['parameters']['required'].remove(key)
    before=copy.deepcopy(original)
    updated=prepare_dialogue_config(original)
    assert original==before
    assert updated['tasks'][0]['tools_config']['llm_agent']==original['tasks'][0]['tools_config']['llm_agent']
    assert updated['tasks'][0]['tools_config']['synthesizer']==original['tasks'][0]['tools_config']['synthesizer']
    assert updated['tasks'][0]['task_config']==original['tasks'][0]['task_config']
    assert updated['webhook_url']==original['webhook_url']
    tools=updated['tasks'][0]['tools_config']['api_tools']
    payload=json.loads(tools['tools_params']['claim911_report_update']['param'])
    assert payload['dispatch_reference']=='%(dispatch_reference)s'
    assert payload['callback_at']=='%(callback_at)s'
    assert COMMON_CALL_CLOSING_NOTE in updated['agent_prompts']['task_1']['system_prompt']
    assert prepare_dialogue_config(updated)==updated


def test_gateway_renewal_preserves_all_nonendpoint_configuration():
    original={'tasks':[{'tools_config':{'api_tools':tool_config('https://old.trycloudflare.com','private-test'),
        'llm_agent':{'model':'gpt-4.1-nano','max_tokens':200},'synthesizer':{'voice':'reviewed'}}}],
        'webhook_url':'https://old.trycloudflare.com/voice/webhook?token=retained'}
    updated=prepare_gateway_config(original,'https://new.trycloudflare.com')
    assert updated['webhook_url']=='https://new.trycloudflare.com/voice/webhook?token=retained'
    assert original['webhook_url'].startswith('https://old.')
    assert prepare_gateway_config(updated,'https://old.trycloudflare.com')==original
    import pytest
    with pytest.raises(ValueError):prepare_gateway_config(original,'http://127.0.0.1')


def test_efficient_model_change_preserves_output_bound_and_rejects_other_models():
    import pytest
    original={'tasks':[{'tools_config':{'llm_agent':{'llm_config':{
        'model':'azure/gpt-4.1-nano','provider':'azure','max_tokens':200,'temperature':0.2}}}}]}
    updated=prepare_efficient_model(original,'azure/gpt-4.1-mini')
    assert updated['tasks'][0]['tools_config']['llm_agent']['llm_config']=={
        'model':'azure/gpt-4.1-mini','provider':'azure','max_tokens':200,'temperature':0.2}
    assert original['tasks'][0]['tools_config']['llm_agent']['llm_config']['model']=='azure/gpt-4.1-nano'
    with pytest.raises(ValueError):prepare_efficient_model(original,'unreviewed-heavy-model')
