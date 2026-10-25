import io
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'sandbox' / 'provider_worker'))
from azure_speech import AzureSpeech


def wave_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\x00\x00' * 80)
    return stream.getvalue()


@pytest.mark.parametrize('role,voice', sorted(AzureSpeech.PARTICIPANT_VOICES.items()))
def test_role_voice_is_allowlisted_and_used_for_synthesis(role, voice, monkeypatch):
    monkeypatch.setenv('CLAIM911_EGRESS_PROXY', 'http://claim911-egress-proxy:3128')
    speech = AzureSpeech({'sku': 'F0', 'region': 'eastus', 'api_key': 'test-only'})
    requests = []
    speech._request = lambda service, path, data, headers: requests.append((service, data)) or wave_bytes()

    result = speech.synthesize('A natural synthetic reply.', 'en', speaker=role)

    assert result == b'\x00\x00' * 80
    assert len(requests) == 1
    assert ('<voice name="' + voice + '">').encode() in requests[0][1]


def test_assistant_voice_default_is_unchanged(monkeypatch):
    monkeypatch.setenv('CLAIM911_EGRESS_PROXY', 'http://claim911-egress-proxy:3128')
    speech = AzureSpeech({'sku': 'F0', 'region': 'eastus', 'api_key': 'test-only'})
    requests = []
    speech._request = lambda service, path, data, headers: requests.append(data) or wave_bytes()

    speech.synthesize('A Claim911 assistant reply.', 'en')

    assert b'<voice name="en-IN-NeerjaNeural">' in requests[0]


def test_participant_voice_cannot_be_selected_for_deferred_hindi(monkeypatch):
    monkeypatch.setenv('CLAIM911_EGRESS_PROXY', 'http://claim911-egress-proxy:3128')
    speech = AzureSpeech({'sku': 'F0', 'region': 'eastus', 'api_key': 'test-only'})
    with pytest.raises(ValueError, match='Known English synthetic participant'):
        speech.synthesize('A synthetic reply.', 'hi', speaker='caregiver')
    with pytest.raises(ValueError, match='Known English synthetic participant'):
        speech.synthesize('A synthetic reply.', 'en', speaker='unknown')


def test_trusted_provider_bridge_carries_only_the_selected_role_voice():
    from sandbox.provider_control import DockerProvider

    provider = DockerProvider.__new__(DockerProvider)
    captured = []
    provider.request = lambda operation, body: captured.append((operation, body)) or {'pcm_base64': 'AA=='}

    provider.synthesize('The bill is corrected.', 'en', speaker='billing')

    assert captured == [('synthesize', {'text': 'The bill is corrected.', 'language': 'en', 'speaker': 'billing'})]


def test_speech_adapter_requires_internal_provider_proxy(monkeypatch):
    monkeypatch.delenv('CLAIM911_EGRESS_PROXY', raising=False)
    with pytest.raises(ValueError, match='Restricted sandbox egress proxy'):
        AzureSpeech({'sku': 'F0', 'region': 'eastus', 'api_key': 'test-only'})

