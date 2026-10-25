"""Small provider adapter. Dispatch timeouts are uncertain, never blindly retried."""
import re
import json
from uuid import UUID
import httpx


class DispatchUnknown(RuntimeError):
    pass


class ProviderRejected(RuntimeError):
    pass


class Bolna:
    def __init__(self,api_key,client=None):
        self.api_key=api_key
        self.client=client or httpx.Client(base_url='https://api.bolna.ai',timeout=20)

    def web_session(self,agent_id,user_data):
        """Mint one short-lived browser session; never dispatch a phone call."""
        UUID(agent_id)
        if not isinstance(user_data,dict) or len(json.dumps(user_data).encode())>12000:
            raise ValueError('Bounded server-owned browser context required')
        try:
            response=self.client.post('/web-call/freeswitch-session',headers={'Authorization':'Bearer '+self.api_key},
                                      json={'agent_id':agent_id,'user_data':user_data},follow_redirects=False)
        except httpx.TransportError as exc:
            raise DispatchUnknown('Browser session result unknown; no automatic retry') from exc
        if response.status_code>=500:raise DispatchUnknown('Browser session mint result uncertain')
        if response.status_code>=300:raise ProviderRejected('Browser voice is unavailable for this account or agent')
        try:
            body=response.json()
            fields={'run_id','agent_id','sip_username','sip_password','sip_domain','wss_url','sip_register','expires_in','ice_servers'}
            session={k:body[k] for k in fields}
            UUID(session['run_id'])
            if UUID(session['agent_id'])!=UUID(agent_id):raise ValueError()
            if type(session['expires_in']) is not int or not 0<session['expires_in']<=180 or type(session['sip_register']) is not bool:raise ValueError()
            if not all(isinstance(session[k],str) and 0<len(session[k])<=2048 for k in ['sip_username','sip_password','sip_domain','wss_url']):raise ValueError()
            target=httpx.URL(session['wss_url'])
            if target.scheme!='wss' or not target.host or not (target.host=='bolna.ai' or target.host.endswith('.bolna.ai')) or target.userinfo or target.fragment:raise ValueError()
            if not isinstance(session['ice_servers'],list) or len(session['ice_servers'])>8:raise ValueError()
            if self.api_key and self.api_key in json.dumps(session):raise ValueError()
            return session
        except (ValueError,KeyError,TypeError) as exc:
            raise DispatchUnknown('Provider returned an invalid ephemeral browser session; reconcile before another mint') from exc

    def agent_configuration_fingerprint(self,agent_id):
        """Read the current assistant configuration without returning its secrets."""
        UUID(agent_id)
        try:
            response=self.client.get('/v2/agent/'+agent_id,headers={'Authorization':'Bearer '+self.api_key},follow_redirects=False)
        except httpx.TransportError as exc:
            raise DispatchUnknown('Assistant configuration could not be checked; voice session withheld') from exc
        if response.status_code>=300:
            raise ProviderRejected('Assistant configuration is unavailable for review')
        try:
            from coordinator.agent_fingerprint import fingerprint
            agent=response.json()
            if str(agent.get('id'))!=agent_id:raise ValueError()
            return fingerprint(agent)
        except (ValueError,TypeError) as exc:
            raise DispatchUnknown('Assistant configuration response could not be validated') from exc

    def call(self,agent_id,phone,user_data):
        UUID(agent_id)
        if not re.fullmatch(r'\+[1-9]\d{7,14}',phone):
            raise ValueError('Recipient must use E.164 phone format')
        try:
            data=dict(user_data) if isinstance(user_data,dict) else {}
            data.setdefault('claim911_greeting',"Hello, this is Claim911 calling about a synthetic insurance coordination case. May I speak with the assigned desk?")
            r=self.client.post('/call',headers={'Authorization':'Bearer '+self.api_key},json={
                'agent_id':agent_id,'recipient_phone_number':phone,'user_data':data})
        except httpx.TransportError as exc:
            raise DispatchUnknown('Provider dispatch result unknown; reconcile before another attempt') from exc
        if r.status_code>=500:
            raise DispatchUnknown('Provider server error after dispatch; reconcile before another attempt')
        if r.status_code>=400:
            raise ProviderRejected('Provider rejected call configuration or access')
        try:
            execution_id=r.json()['execution_id']
            UUID(execution_id)
        except (ValueError,KeyError,TypeError) as exc:
            raise DispatchUnknown('Provider accepted call without a usable execution identifier') from exc
        return execution_id

    def stop(self,execution_id):
        UUID(execution_id)
        r=self.client.post('/call/'+execution_id+'/stop',headers={'Authorization':'Bearer '+self.api_key})
        r.raise_for_status()
        payload=r.json()
        if payload.get('execution_id')!=execution_id or payload.get('status')!='stopped':
            raise ValueError('Provider did not confirm this execution stopped')
        return payload

    def execution(self,execution_id):
        UUID(execution_id)
        r=self.client.get('/executions/'+execution_id,headers={'Authorization':'Bearer '+self.api_key})
        r.raise_for_status()
        return r.json()

    def recording(self,execution_id):
        UUID(execution_id)
        # The provider redirects to its recording bucket. Never forward the API key there.
        url='https://api.bolna.ai/recordings/call/'+execution_id
        for _ in range(4):
            target=httpx.URL(url)
            if target.scheme!='https' or target.host not in {'api.bolna.ai','bolna-recordings-india.s3.amazonaws.com'} or target.port not in (None,443) or target.userinfo:
                raise ValueError('Untrusted recording destination')
            headers={'Authorization':'Bearer '+self.api_key} if target.host=='api.bolna.ai' else {}
            with self.client.stream('GET',url,headers=headers,follow_redirects=False) as r:
                if r.status_code in {301,302,303,307,308}:
                    location=r.headers.get('location')
                    if not location:
                        raise ValueError('Recording redirect missing destination')
                    url=str(target.join(location))
                    continue
                r.raise_for_status()
                mime=r.headers.get('content-type','').split(';')[0]
                if not mime.startswith('audio/') and mime!='application/octet-stream':
                    raise ValueError('Provider did not return an audio recording')
                chunks=[];length=0
                for chunk in r.iter_bytes():
                    length+=len(chunk)
                    if length>25*1024*1024:
                        raise ValueError('Recording exceeds demo playback limit')
                    chunks.append(chunk)
                return b''.join(chunks),mime or 'audio/wav'
        raise ValueError('Too many recording redirects')
