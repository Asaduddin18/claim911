"""Trusted one-operation provider controller. No cloud secrets enter Pipecat."""
import base64,json,subprocess,re
from uuid import uuid4
from urllib.parse import urlsplit


class ProviderOperationError(RuntimeError):
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        super().__init__('Trusted provider operation failed; account details redacted')


class DockerProvider:
    NETWORK='claim911-provider-internal'
    PROXY='http://claim911-egress-proxy:3128'

    def __init__(self,configuration):
        if configuration.get('environment')!='sandbox':raise ValueError('Synthetic provider configuration required')
        self._configuration=configuration
        resolved=subprocess.run(['docker','--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}','claim911-speech-provider:local'],capture_output=True,text=True,timeout=10)
        self.image_id=resolved.stdout.strip()
        if resolved.returncode or not re.fullmatch(r'sha256:[a-f0-9]{64}',self.image_id):raise RuntimeError('Build the trusted provider image before enabling provider requests')
        network=subprocess.run(['docker','--context','colima-claim911-sandbox','network','inspect','--format','{{.Internal}}',self.NETWORK],capture_output=True,text=True,timeout=10)
        proxy=subprocess.run(['docker','--context','colima-claim911-sandbox','inspect','--format','{{json .}}','claim911-egress-proxy'],capture_output=True,text=True,timeout=10)
        proxy_image=subprocess.run(['docker','--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}','claim911-egress-proxy:local'],capture_output=True,text=True,timeout=10)
        if network.returncode or network.stdout.strip().lower()!='true' or proxy.returncode:
            raise RuntimeError('Restricted provider egress network is unavailable')
        try:
            inspected=json.loads(proxy.stdout)
            if isinstance(inspected,list):inspected=inspected[0]
            env=dict(item.split('=',1) for item in inspected['Config']['Env'] if '=' in item)
            attached=set(inspected['NetworkSettings']['Networks'])
            model_host=urlsplit(configuration['model']['endpoint']).hostname
            allowed=set(env.get('CLAIM911_ALLOWED_HOSTS','').split(','))
            host=inspected['HostConfig']
        except (ValueError,TypeError):
            raise RuntimeError('Restricted provider egress proxy inspection failed') from None
        except (KeyError,IndexError):
            raise RuntimeError('Restricted provider egress proxy inspection failed') from None
        expected={'eastus.stt.speech.microsoft.com','eastus.tts.speech.microsoft.com',model_host}
        if (inspected.get('State',{}).get('Running') is not True or allowed!=expected
            or self.NETWORK not in attached or 'bridge' not in attached
            or host.get('NetworkMode')!='bridge' or host.get('ReadonlyRootfs') is not True
            or host.get('Privileged') is not False or host.get('Binds') not in (None,[])
            or inspected.get('Mounts') or host.get('CapDrop')!=['ALL']
            or not any('no-new-privileges' in value for value in host.get('SecurityOpt',[]))
            or inspected.get('Config',{}).get('User')!='65532:65532'
            or inspected.get('Config',{}).get('Image')!='claim911-egress-proxy:local'
            or proxy_image.returncode or inspected.get('Image')!=proxy_image.stdout.strip()):
            raise RuntimeError('Provider egress proxy does not match its exact-host isolated profile')

    def request(self,operation,body,*,reservation_id=None):
        if operation not in {'transcribe','synthesize','reply'}:raise ValueError('Unknown provider operation')
        envelope={'environment':'sandbox','operation':operation,'body':body}
        if operation=='reply':
            if not reservation_id:raise ValueError('Committed model reservation required')
            envelope.update(model=self._configuration['model'],reservation_id=str(reservation_id))
        else:envelope['speech']=self._configuration['speech']
        container='claim911-provider-'+uuid4().hex
        args=['docker','--context','colima-claim911-sandbox','run','--rm','--name',container,'-i',
          '--network',self.NETWORK,'-e','CLAIM911_EGRESS_PROXY='+self.PROXY,
          '--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
          '--pids-limit','32','--memory','128m','--cpus','0.5','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777',
          '--entrypoint','python',self.image_id,'-I','/app/one_request.py']
        try:
            result=subprocess.run(args,input=json.dumps(envelope)+'\n',capture_output=True,text=True,timeout=60)
            if result.returncode:
                diagnostic={'provider_error_type':'UnknownError','provider_http_status':None,'provider_error_code':'REDACTED_PROVIDER_FAILURE','operation':operation}
                try:
                    failure=json.loads(result.stdout[:2000])
                    if failure.get('error_code') in {'RESPONSE_TOO_LARGE','AUDIO_FORMAT_MISMATCH','INVALID_SPEECH_TEXT','NO_FINAL_TRANSCRIPT','INCOMPLETE_MODEL_RESPONSE','MODEL_CONTEXT_TOO_LARGE'}:
                        diagnostic['provider_error_code']=failure['error_code']
                    if failure.get('error_type') in {'ValueError','HTTPError','TimeoutError','URLError','KeyError','IncompleteRead'}:
                        diagnostic['provider_error_type']=failure['error_type']
                    from sandbox.provider_worker.network_diagnostics import NETWORK_FAILURES
                    if failure.get('network_failure') in NETWORK_FAILURES:
                        diagnostic['network_failure']=failure['network_failure']
                    if type(failure.get('http_status')) is int and 400<=failure['http_status']<=599:
                        diagnostic['provider_http_status']=failure['http_status']
                except (ValueError,AttributeError):pass
                raise ProviderOperationError(diagnostic)
            if len(result.stdout)>5_000_000:raise RuntimeError('Provider response exceeds boundary size')
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','--context','colima-claim911-sandbox','rm','--force',container],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            raise TimeoutError('Provider execution requires reconciliation before retry') from None

    def transcribe(self,pcm,language):
        return self.request('transcribe',{'pcm_base64':base64.b64encode(pcm).decode(),'language':language})

    def synthesize(self,text,language,*,speaker='assistant'):
        return base64.b64decode(self.request('synthesize',{'text':text,'language':language,'speaker':speaker})['pcm_base64'],validate=True)
