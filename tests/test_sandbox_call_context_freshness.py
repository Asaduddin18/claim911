import pytest
from fastapi import HTTPException

from coordinator.sandbox_calls import require_current_context


class FakeConnection:
    def __init__(self,events):self.events=events
    def execute(self,sql,params):
        if 'max(sequence)' in sql:
            material=[e['sequence'] for e in self.events
                      if e['type'] not in {'VOICE_TOOL_USED','SANDBOX_PROVIDER_EXECUTION_BOUND'}]
            return type('Row',(),{'fetchone':lambda _: {'n':max(material,default=0)}})()
        contexts=[e for e in self.events if e['type']=='VOICE_TOOL_USED'
                  and e['payload'].get('call_id')==str(params[1])
                  and e['payload'].get('tool')=='claim911_context']
        row={'payload':contexts[-1]['payload']} if contexts else None
        return type('Row',(),{'fetchone':lambda _:row})()


def test_provider_execution_binding_does_not_make_fresh_case_context_stale():
    events=[
        {'sequence':9,'type':'INTAKE_CREATED','payload':{}},
        {'sequence':10,'type':'VOICE_TOOL_USED','payload':{'call_id':'call-1','tool':'claim911_context','material_sequence':9}},
        {'sequence':11,'type':'SANDBOX_PROVIDER_EXECUTION_BOUND','payload':{'call_id':'call-1','transport':'BOLNA_WEBRTC'}},
    ]
    require_current_context(FakeConnection(events),{'mode':'SANDBOX_AUDIO','incident_id':'incident-1','id':'call-1'})


def test_new_case_evidence_still_requires_a_context_refresh():
    events=[
        {'sequence':9,'type':'INTAKE_CREATED','payload':{}},
        {'sequence':10,'type':'VOICE_TOOL_USED','payload':{'call_id':'call-1','tool':'claim911_context','material_sequence':9}},
        {'sequence':11,'type':'SANDBOX_PROVIDER_EXECUTION_BOUND','payload':{'call_id':'call-1','transport':'BOLNA_WEBRTC'}},
        {'sequence':12,'type':'DOCUMENT_UPLOADED','payload':{'document_id':'doc-1'}},
    ]
    with pytest.raises(HTTPException) as error:
        require_current_context(FakeConnection(events),{'mode':'SANDBOX_AUDIO','incident_id':'incident-1','id':'call-1'})
    assert error.value.status_code==409
