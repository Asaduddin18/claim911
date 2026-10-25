from sandbox.spoken_identifiers import normalize_identifier_speech
from sandbox.scripted_desks import ScriptedDesk


def test_spelled_identifier_is_lossless_and_near_values_are_not_repaired():
    assert normalize_identifier_speech('A D M hyphen S Y N hyphen two zero eight four')=='adm-syn-2084'
    assert normalize_identifier_speech('ADM-SIN-2084')=='adm-sin-2084'
    assert normalize_identifier_speech('ADM-SYN-2085')=='adm-syn-2085'


def test_combined_spelled_readback_requires_every_named_identifier_exactly():
    actor=ScriptedDesk('hospital_insurance',{'admission_id':'ADM-SYN-2084','references':{
        'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084','final_request':'FINAL-SYN-2084'}})
    def ask(text):return actor.reply([{'role':'user','content':text}])
    text='Admission ID A D M hyphen S Y N hyphen two zero eight four, initial approval P A hyphen S Y N hyphen two zero eight four, enhancement reference E N H hyphen S Y N hyphen two zero eight four, final request F I N A L hyphen S Y N hyphen two zero eight four. Are these references correct?'
    assert ask(text)=='Yes, that is the correct reference.'
    assert 'differs' in ask(text.replace('E N H hyphen S Y N hyphen two zero eight four','ENH-SYN-9999'))
    assert 'cannot confirm the complete readback' in ask(text.replace('E N H hyphen S Y N hyphen two zero eight four','still pending'))
