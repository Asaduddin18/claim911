import errno,json,socket,ssl
from urllib.error import URLError,HTTPError
import pytest
from sandbox.provider_worker.network_diagnostics import network_failure


@pytest.mark.parametrize('reason,expected',[
 (socket.gaierror(-3,'secret-endpoint'),'DNS_FAILURE'),
 (TimeoutError('secret-key'),'NETWORK_TIMEOUT'),
 (ssl.SSLCertVerificationError('secret-host'),'TLS_CERTIFICATE_FAILURE'),
 (ssl.SSLError('secret-host'),'TLS_FAILURE'),
 (ConnectionRefusedError('secret-host'),'CONNECTION_REFUSED'),
 (ConnectionResetError('secret-host'),'CONNECTION_RESET'),
 (OSError(errno.ENETUNREACH,'secret-host'),'NETWORK_UNREACHABLE'),
 (OSError('Tunnel connection failed: 502 endpoint secret-key'),'PROXY_CONNECT_502'),
 (OSError('unexpected secret-host secret-key'),'OTHER_NETWORK_FAILURE')])
def test_safe_network_classification_never_returns_raw_reason(reason,expected):
 result=network_failure(URLError(reason))
 assert result==expected
 assert 'secret' not in json.dumps(result)


def test_provider_http_error_is_distinct_from_transport_error():
 assert network_failure(HTTPError('https://secret-host',429,'secret-key',{},None)) is None
 assert network_failure(ValueError('secret-key')) is None
