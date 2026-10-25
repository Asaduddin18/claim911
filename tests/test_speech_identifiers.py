from sandbox.provider_worker.azure_speech import speech_markup
from xml.etree import ElementTree


def test_identifier_alias_preserves_exact_source_and_speaks_hyphens_and_digits():
    rendered=speech_markup('Admission ADM42, initial PRE37 and final FIN63.')
    root=ElementTree.fromstring('<speak>'+rendered+'</speak>')
    assert [e.text for e in root.findall('sub')]==['ADM42','PRE37','FIN63']
    assert root.find('sub').attrib['alias']=='A D M four two'


def test_untrusted_markup_cannot_create_audio_fetch_or_ssml_instruction():
    rendered=speech_markup('Keep <audio src="https://outside.invalid/secret"/> & quote ADM42.')
    root=ElementTree.fromstring('<speak>'+rendered+'</speak>')
    assert root.find('audio') is None and len(root.findall('sub'))==1


def test_historical_long_codes_still_have_lossless_spoken_forms():
    root=ElementTree.fromstring('<speak>'+speech_markup('ADM-SYN-2084')+'</speak>')
    assert root.find('sub').attrib['alias']=='A D M hyphen S Y N hyphen two zero eight four'
