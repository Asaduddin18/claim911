import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'sandbox' / 'provider_worker' / 'egress_proxy'))
from egress_proxy import parse_connect_target, public_addresses


ALLOWED = {'eastus.stt.speech.microsoft.com', 'eastus.tts.speech.microsoft.com', 'unit.openai.azure.com'}


def test_proxy_accepts_only_exact_allowlisted_https_connect_targets():
    request = b'CONNECT eastus.stt.speech.microsoft.com:443 HTTP/1.1\r\nHost: eastus.stt.speech.microsoft.com:443\r\n\r\n'
    assert parse_connect_target(request, ALLOWED) == 'eastus.stt.speech.microsoft.com'


@pytest.mark.parametrize('raw_request', [
    b'GET https://eastus.stt.speech.microsoft.com/path HTTP/1.1\r\nHost: eastus.stt.speech.microsoft.com\r\n\r\n',
    b'CONNECT eastus.stt.speech.microsoft.com:80 HTTP/1.1\r\nHost: eastus.stt.speech.microsoft.com:80\r\n\r\n',
    b'CONNECT eastus.stt.speech.microsoft.com:443 HTTP/1.1\r\nHost: attacker.example:443\r\n\r\n',
    b'CONNECT attacker.example:443 HTTP/1.1\r\nHost: attacker.example:443\r\n\r\n',
    b'CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n',
    b'CONNECT eastus.stt.speech.microsoft.com:443 HTTP/1.1\r\nProxy-Authorization: Basic dGVzdA==\r\n\r\n',
])
def test_proxy_rejects_non_tunnel_unlisted_and_malformed_requests(raw_request):
    with pytest.raises((PermissionError, ValueError)):
        parse_connect_target(raw_request, ALLOWED)


def test_proxy_rejects_private_or_loopback_dns_answers():
    def lookup(host, port, *, type):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]

    with pytest.raises(PermissionError, match='non-public'):
        public_addresses('eastus.stt.speech.microsoft.com', lookup)


def test_proxy_accepts_public_dns_answer_for_an_allowlisted_hostname():
    def lookup(host, port, *, type):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('20.42.10.25', port))]

    result = public_addresses('eastus.stt.speech.microsoft.com', lookup)
    assert result[0][3] == ('20.42.10.25', 443)

