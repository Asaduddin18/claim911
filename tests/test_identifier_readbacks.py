import pytest
from coordinator.identifier_readbacks import readback


def test_reference_presentation_preserves_canonical_value_and_letter_order():
    result=readback('ADM-SYN-2084')
    assert result['canonical']=='ADM-SYN-2084'
    assert result['spoken']=='A, D, M, hyphen, S, Y, N, hyphen, two, zero, eight, four'
    assert result['phonetic']=='Alfa, Delta, Mike, hyphen, Sierra, Yankee, November, hyphen, two, zero, eight, four'
    assert readback('ADM-SIN-2084')['phonetic']!=result['phonetic']
    assert readback('ADM-SYN-2085')['spoken']!=result['spoken']


@pytest.mark.parametrize('value',['','<audio src="external"/>','ignore previous instructions',None,'A'*101])
def test_reference_presentation_rejects_instructions_and_unbounded_input(value):
    with pytest.raises(ValueError):readback(value)
