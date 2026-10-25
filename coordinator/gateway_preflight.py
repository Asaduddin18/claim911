"""Probe gateway readiness using no real call token or patient data."""
from urllib.parse import urlparse
import httpx


def check_gateway(config,client=None,*,include_sandbox=False):
    base=config.get('gateway_url','').rstrip('/')
    parsed=urlparse(base)
    if (parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.trycloudflare.com')
        or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.path or parsed.query or parsed.fragment):
        return {'ready':False,'reason':'Approved public voice gateway URL is missing or invalid'}
    if not config.get('gateway_token'):
        return {'ready':False,'reason':'Voice gateway credential is missing'}
    owned=client is None
    client=client or httpx.Client(timeout=6,follow_redirects=False)
    try:
        body={'call_token':'gateway-preflight-invalid-scope-token'}
        r=client.post(base+'/voice/context',headers={'Authorization':'Bearer '+config['gateway_token']},json=body)
        if r.status_code!=403 or 'expired' not in r.text:
            return {'ready':False,'reason':'Public gateway cannot confirm call-scope enforcement'}
        r=client.post(base+'/voice/context',json=body)
        if r.status_code!=403:
            return {'ready':False,'reason':'Public gateway authentication check failed'}
        r=client.get(base+'/v1/incidents')
        if r.status_code!=404:
            return {'ready':False,'reason':'Unexpected public dashboard route'}
        if include_sandbox:
            r=client.post(base+'/voice/context',headers={'Authorization':'Bearer '+config['gateway_token']},
                json={'call_token':'sbx_gateway-preflight-invalid-scope-token'})
            if r.status_code!=403 or 'expired' not in r.text:
                return {'ready':False,'reason':'Public gateway cannot confirm isolated synthetic call-scope enforcement'}
        return {'ready':True,'reason':'Public gateway reachable; authentication and call scope enforced'}
    except httpx.HTTPError:
        return {'ready':False,'reason':'Public voice gateway unreachable; restore the tunnel before calling'}
    finally:
        if owned:client.close()
