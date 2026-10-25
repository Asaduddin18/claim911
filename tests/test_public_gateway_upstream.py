import pytest
from coordinator.gateway import create_app


@pytest.mark.parametrize('url',['https://example.com','http://10.0.0.1:8120','http://127.0.0.1:8120/path','http://user:pass@127.0.0.1:8120'])
def test_voice_gateway_refuses_nonlocal_or_ambiguous_upstream(url):
 with pytest.raises(ValueError):create_app({'core_url':url,'environment':'operational'})


def test_voice_gateway_refuses_sandbox_as_default_public_upstream():
 with pytest.raises(ValueError):create_app({'core_url':'http://127.0.0.1:8121','environment':'sandbox'})
