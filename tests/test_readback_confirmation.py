import pytest
from sandbox.readback_confirmation import unsupported_affirmation,readback_evidence

RECORD={'admission_id':'ADM-SYN-2084','references':{'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084','final_request':'FINAL-SYN-2084'}}
YES='Yes, that exact reference matches our record.'


def test_alphabetic_document_reference_requires_its_actual_separator():
 record={'documents':[{'id':'summary-signed','revision':1}]}
 assert readback_evidence('Confirm the document identifier summary hyphen signed. Is that correct?',record)['state']=='EXACT_MATCH'
 assert not unsupported_affirmation(YES,'Confirm the document identifier summary hyphen signed. Is that correct?',record)
 assert unsupported_affirmation(YES,'Confirm the document identifier summary signed. Is that correct?',record)
 assert unsupported_affirmation(YES,'Confirm the document identifier summary slash signed. Is that correct?',record)


def test_participant_speech_says_separators_only_for_its_owned_identifiers():
 from sandbox.spoken_identifiers import pronounce_role_identifiers
 record={'desk_record':{'documents':[{'id':'summary-signed'}]}}
 assert pronounce_role_identifiers('Our document is summary-signed. Follow-up is needed.',record)=='Our document is summary hyphen signed. Follow-up is needed.'
 assert pronounce_role_identifiers('Other document implant-invoice.',record)=='Other document implant-invoice.'


def test_acknowledged_reference_cannot_answer_a_new_timestamp_request():
 from sandbox.readback_confirmation import reference_confirmation_reply
 record={'references':{'enhancement':'ENH18','claim':'CLM86'}}
 question='Thanks for confirming the enhancement reference ENH18. Now please confirm the original receipt timestamp with time zone included.'
 assert readback_evidence(question,record)['state']=='NOT_APPLICABLE'
 assert reference_confirmation_reply(question,record) is None


def test_request_for_a_reference_without_a_candidate_is_not_a_wrong_readback():
 from sandbox.readback_confirmation import reference_confirmation_reply
 record={'references':{'query':'QRY25','claim':'CLM86'}}
 question='Thanks for confirming query reference QRY25. Now please confirm the claim reference for this outstanding query.'
 assert reference_confirmation_reply(question,record) is None


@pytest.mark.parametrize('spoken',['ADM42','A D M four two','Alfa Delta Mike four two'])
def test_short_reference_keeps_exact_characters_and_field_identity(spoken):
 record={'admission_id':'ADM42','references':{'preauthorization':'PRE37','enhancement':'ENH18'}}
 assert readback_evidence('Confirm admission ID '+spoken+'?',record)['state']=='EXACT_MATCH'
 assert unsupported_affirmation(YES,'Confirm admission ID ADM43?',record)
 assert unsupported_affirmation(YES,'Confirm initial request reference ENH18?',record)
 assert unsupported_affirmation('No, the reference is PRE38.','Confirm initial request reference PRE38?',record)


def test_incomplete_code_cannot_be_affirmed():
 assert unsupported_affirmation(YES,'The initial request reference is n. H hyphen syn hyphen 2084. Is that correct?',RECORD)


def test_known_code_for_wrong_field_cannot_be_affirmed():
 assert unsupported_affirmation(YES,'The initial request reference is ENH-SYN-2084. Is that correct?',RECORD)


def test_exact_spelled_readback_can_be_affirmed():
 assert not unsupported_affirmation(YES,'Confirm admission ID A D M hyphen S Y N hyphen two zero eight four?',RECORD)


def test_negative_correction_and_status_answers_are_not_reference_affirmations():
 assert not unsupported_affirmation('That does not match; ours is PA-SYN-2084.','Is initial request ENH-SYN-2084 correct?',RECORD)
 assert not unsupported_affirmation('Yes, the document is signed.','Can you confirm the summary is signed?',RECORD)


def test_negative_correction_cannot_supply_another_fields_known_code():
 assert unsupported_affirmation('That does not match. Our record shows ENH-SYN-2084.','Confirm the initial request reference ENH-SYN-2084. Is that correct?',RECORD)
 assert not unsupported_affirmation('That does not match. Our initial request reference is PA-SYN-2084.','Confirm the initial request reference ENH-SYN-2084. Is that correct?',RECORD)


import pytest
from sandbox.readback_confirmation import readback_evidence

@pytest.mark.parametrize('value',['ADM','A D M','a DM','A, D, M'])
def test_exact_admission_characters_survive_spacing_without_fuzzy_repair(value):
 question=f'To confirm, the admission ID is {value} hyphen S Y N hyphen two zero eight four. Is that correct?'
 assert readback_evidence(question,RECORD)['state']=='EXACT_MATCH'
 assert unsupported_affirmation('That is not an exact match.',question,RECORD)
 assert not unsupported_affirmation(YES,question,RECORD)


def test_glued_label_is_not_part_of_identifier():
 assert readback_evidence('Confirm admission IDADM hyphen syn hyphen 2084?',RECORD)['state']=='EXACT_MATCH'


@pytest.mark.parametrize('code',['ADN-SYN-2084','ADM-SIN-2084','ADM-SYN-2085','BADM-SYN-2084'])
def test_changed_characters_and_added_prefix_are_never_repaired(code):
 assert readback_evidence('Confirm admission ID '+code+'?',RECORD)['state']=='MISMATCH_OR_UNCLEAR'


def test_generated_phonetic_form_uses_exact_same_reference_characters():
 from coordinator.identifier_readbacks import readback
 question='Confirm admission ID '+readback('ADM-SYN-2084')['phonetic']+'?'
 assert readback_evidence(question,RECORD)['state']=='EXACT_MATCH'
 assert readback_evidence('Confirm admission ID Alfa Delta Mike hyphen Sierra India November hyphen two zero eight four?',RECORD)['state']=='MISMATCH_OR_UNCLEAR'


def test_slash_is_preserved_as_a_distinct_separator():
 record={'admission_id':'ADM/SYN/2084'}
 assert readback_evidence('Confirm admission ID A D M slash S Y N slash two zero eight four?',record)['state']=='EXACT_MATCH'
 assert readback_evidence('Confirm admission ID ADM-SYN-2084?',record)['state']=='MISMATCH_OR_UNCLEAR'


@pytest.mark.parametrize('field,code',[('initial request reference','PRE37'),('enhancement reference','ENH18'),('final request reference','FIN63')])
def test_repeated_field_after_candidate_keeps_its_exact_readback(field,code):
 from sandbox.readback_confirmation import reference_confirmation_reply
 record={'admission_id':'ADM42','references':{'preauthorization':'PRE37','enhancement':'ENH18','final_request':'FIN63'}}
 question=f'The admission ID ADM42 is confirmed. For the {field}, I have {code} from your slip. Is that the correct {field}?'
 assert reference_confirmation_reply(question,record)=='Yes, that exact reference matches our record.'
 assert reference_confirmation_reply(question.replace('I have '+code,'I have BAD99'),record)=='No, the reference in our record is '+code+'.'
 assert reference_confirmation_reply('Confirm admission ID ADM42. Now can you provide the enhancement reference?',record) is None
