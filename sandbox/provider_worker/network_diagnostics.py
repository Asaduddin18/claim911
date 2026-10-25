"""Classify transport failures without emitting endpoints, headers or error text."""
import errno,re,socket,ssl
from urllib.error import HTTPError,URLError

NETWORK_FAILURES={'DNS_FAILURE','NETWORK_TIMEOUT','TLS_CERTIFICATE_FAILURE','TLS_FAILURE',
 'CONNECTION_REFUSED','CONNECTION_RESET','NETWORK_UNREACHABLE','PROXY_CONNECT_400',
 'PROXY_CONNECT_403','PROXY_CONNECT_431','PROXY_CONNECT_502','PROXY_CONNECT_503','OTHER_NETWORK_FAILURE'}


def network_failure(exc):
    if isinstance(exc,HTTPError):return None
    reason=exc.reason if isinstance(exc,URLError) else exc
    if isinstance(reason,socket.gaierror):return 'DNS_FAILURE'
    if isinstance(reason,ssl.SSLCertVerificationError):return 'TLS_CERTIFICATE_FAILURE'
    if isinstance(reason,ssl.SSLError):return 'TLS_FAILURE'
    if isinstance(reason,TimeoutError):return 'NETWORK_TIMEOUT'
    if isinstance(reason,ConnectionRefusedError):return 'CONNECTION_REFUSED'
    if isinstance(reason,ConnectionResetError):return 'CONNECTION_RESET'
    if isinstance(reason,OSError) and reason.errno in {errno.ENETUNREACH,errno.EHOSTUNREACH}:return 'NETWORK_UNREACHABLE'
    if isinstance(exc,URLError):
        # urllib wraps failed CONNECT status in an OSError string. Extract only
        # a fixed status enum; never return the reason or arbitrary message.
        match=re.search(r'Tunnel connection failed: (400|403|431|502|503)(?:\s|$)',str(reason))
        return 'PROXY_CONNECT_'+match[1] if match else 'OTHER_NETWORK_FAILURE'
    return None
