import json,pytest
from scripts.reconcile_bolna_mint import terminal_evidence


def test_terminal_evidence_requires_exact_synthetic_binding_and_never_awards_checkpoint():
    record={'id':'execution','status':'failed','conversation_duration':0,'context_details':{'recipient_data':{
        'claim911_case_id':'incident','claim911_context':json.dumps({'call_id':'call','simulated':True})}}}
    args=dict(run_id='run',call_id='call',incident_id='incident',execution_id='execution')
    result=terminal_evidence(record,**args)
    assert result['run_remains_uncertain'] and not result['checkpoint_pass']
    for wrong in (record|{'status':'in-progress'},record|{'id':'other'},record|{'context_details':{}}):
        with pytest.raises(ValueError):terminal_evidence(wrong,**args)


def test_unconnected_recovery_excludes_unknown_or_executed_sessions():
    from scripts.reconcile_bolna_mint import unconnected_without_actions
    record={'status':'failed','conversation_duration':0,'transcript':None,'tool_call_logs':[]}
    assert unconnected_without_actions(record)
    for change in ({'status':'in-progress'},{'conversation_duration':1},{'transcript':'hello'},{'tool_call_logs':[{'tool':'write'}]},{'tool_call_logs':None}):
        assert not unconnected_without_actions(record|change)
