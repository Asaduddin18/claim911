from coordinator.voice_guidance import context_guidance


def test_query_confirms_each_identifier_using_the_same_single_candidate_protocol():
 guidance=context_guidance({'uploaded_query_candidates':[{'support_status':'UPLOADED_UNVERIFIED'}]})
 assert 'ONE uploaded candidate at a time' in guidance
 for field in ['query reference','claim reference','admission ID','enhancement reference']:
  assert field in guidance
 assert 'explicit confirmation for EACH' in guidance
 assert 'Do not ask staff to dictate' in guidance
 assert 'Spoken formatting does not verify' in guidance


def test_candidate_protocol_never_injects_reference_values_or_private_fields():
 guidance=context_guidance({'uploaded_query_candidates':[{'private':'DO_NOT_COPY','reference':'FAKE-123'}]})
 assert 'DO_NOT_COPY' not in guidance and 'FAKE-123' not in guidance
 assert context_guidance({})==''
