"""Trusted fixed-destination Azure Speech adapter; standard library only."""
import io,re
from http.client import IncompleteRead
import json
import os
import wave
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler
from urllib.parse import urlencode
from xml.sax.saxutils import escape,quoteattr

IDENTIFIER=re.compile(r'(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+|[A-Z]+[0-9]+)(?![A-Za-z0-9])')
TIMESTAMP=r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})'
CURRENCY=r'(?:INR|₹)\s*\d[\d,]*(?:\.\d{1,2})?(?!\d|\.\d)'
SPOKEN_TOKEN=re.compile(TIMESTAMP+'|'+CURRENCY+'|'+IDENTIFIER.pattern)
DIGITS=dict(zip('0123456789',['zero','one','two','three','four','five','six','seven','eight','nine']))


def speech_markup(text):
    """Use native SSML substitution to pronounce, never rewrite, identifiers."""
    parts=[];cursor=0
    for match in SPOKEN_TOKEN.finditer(text):
        parts.append(escape(text[cursor:match.start()]))
        identifier=match.group()
        if re.fullmatch(CURRENCY,identifier):
            from num2words import num2words
            from decimal import Decimal
            amount=Decimal(re.sub(r'^(?:INR|₹)\s*','',identifier).replace(',',''))
            if amount>1_000_000_000:raise ValueError('Currency exceeds the bounded synthetic speech range')
            rupees=int(amount);paise=int((amount-rupees)*100)
            alias=num2words(rupees,lang='en')+' rupees'
            if paise:alias+=' and '+num2words(paise,lang='en')+' paise'
        elif re.fullmatch(TIMESTAMP,identifier):
            when=datetime.fromisoformat(identifier.replace('Z','+00:00'))
            minutes=int(when.utcoffset().total_seconds()/60)
            zone='UTC' if minutes==0 else f"UTC {'plus' if minutes>0 else 'minus'} {abs(minutes)//60} hours {abs(minutes)%60} minutes"
            alias=when.strftime('%d %B %Y at %I:%M %p')+', '+zone
        else:alias=' '.join('hyphen' if c=='-' else DIGITS.get(c,c) for c in identifier)
        parts.append('<sub alias='+quoteattr(alias)+'>'+escape(identifier)+'</sub>');cursor=match.end()
    parts.append(escape(text[cursor:]))
    return ''.join(parts)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Provider redirects are forbidden')


class AzureSpeech:
    LANGUAGES={'en':('en-IN','en-IN-NeerjaNeural'),'hi':('hi-IN','hi-IN-SwaraNeural')}
    PARTICIPANT_VOICES={
        'caregiver':'en-IN-NeerjaNeural',
        'hospital_insurance':'en-IN-PrabhatNeural',
        'billing':'en-IN-KavyaNeural',
        'medical_records':'en-IN-AaravNeural',
        'implant_store':'en-IN-AnanyaNeural',
        'tpa':'en-IN-KunalNeural',
        'insurer':'en-IN-RehaanNeural',
    }
    def __init__(self,config):
        if config['sku']!='F0' or config['region']!='eastus':
            raise ValueError('Only the configured free sandbox speech resource is enabled')
        self._key=config['api_key']
        proxy=os.environ.get('CLAIM911_EGRESS_PROXY','')
        if proxy!='http://claim911-egress-proxy:3128':
            raise ValueError('Restricted sandbox egress proxy is required')
        self._opener=build_opener(ProxyHandler({'https':proxy}),NoRedirects())

    def _request(self,service,path,data=None,headers=None):
        if service not in {'tts','stt'}:raise ValueError('Unsupported speech service')
        url='https://eastus.'+service+'.speech.microsoft.com'+path
        req=Request(url,data=data,headers={'Ocp-Apim-Subscription-Key':self._key,**(headers or {})})
        # Free-tier speech is read-only. Discard a truncated response and make
        # at most two fresh reads; never retry model or institution side effects.
        # The outer provider process still enforces its total execution timeout.
        for attempt in range(3):
            try:
                with self._opener.open(req,timeout=40) as response:
                    content=response.read(3_240_001 if service=='tts' else 1_280_001)
                break
            except IncompleteRead:
                if attempt==2:raise
            except URLError as exc:
                try:
                    from .network_diagnostics import network_failure
                except ImportError:
                    from network_diagnostics import network_failure
                # Only the fixed free-tier speech read is repeated. The
                # prepared participant reply and institution action stay intact.
                if attempt==2 or network_failure(exc) not in {'DNS_FAILURE','CONNECTION_RESET',
                    'CONNECTION_REFUSED','PROXY_CONNECT_400','PROXY_CONNECT_502','PROXY_CONNECT_503'}:raise
                time.sleep(.2)
        if len(content)>(3_240_000 if service=='tts' else 1_280_000):raise ValueError('Provider response exceeds bounded audio size')
        return content

    def synthesize(self,text,language,speaker='assistant'):
        if language not in self.LANGUAGES or not isinstance(text,str) or not 0<len(text)<=4000:
            raise ValueError('Bounded English or Hindi text required')
        locale,voice=self.LANGUAGES[language]
        if speaker!='assistant':
            if language!='en' or speaker not in self.PARTICIPANT_VOICES:
                raise ValueError('Known English synthetic participant required')
            voice=self.PARTICIPANT_VOICES[speaker]
        ssml=f'<speak version="1.0" xml:lang="{locale}"><voice name="{voice}">{speech_markup(text)}</voice></speak>'
        audio=self._request('tts','/cognitiveservices/v1',ssml.encode(),{
          'Content-Type':'application/ssml+xml','X-Microsoft-OutputFormat':'riff-16khz-16bit-mono-pcm','User-Agent':'Claim911SyntheticSandbox'})
        with wave.open(io.BytesIO(audio),'rb') as wav:
            if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('Unexpected synthesized audio format')
            pcm=wav.readframes(wav.getnframes())
        return pcm

    def transcribe(self,pcm,language):
        if language not in self.LANGUAGES or not 0<len(pcm)<=1280000 or len(pcm)%2:
            raise ValueError('At most 40 seconds of 16 kHz mono PCM required')
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(pcm)
        query=urlencode({'language':self.LANGUAGES[language][0],'format':'detailed'})
        raw=self._request('stt','/speech/recognition/conversation/cognitiveservices/v1?'+query,stream.getvalue(),{
          'Content-Type':'audio/wav; codecs=audio/pcm; samplerate=16000','Accept':'application/json'})
        result=json.loads(raw)
        if result.get('RecognitionStatus')!='Success':raise ValueError('Speech recognition did not produce a final result')
        candidates=result.get('NBest')
        if isinstance(candidates,list) and candidates:
            valid=[item for item in candidates if isinstance(item,dict)
                   and isinstance(item.get('Display'),str) and item['Display'].strip()
                   and isinstance(item.get('Confidence'),(int,float))
                   and not isinstance(item.get('Confidence'),bool)
                   and 0<=item['Confidence']<=1]
            if not valid:raise ValueError('Speech recognition returned no scored transcript candidate')
            best=valid[0]
            return {'text':best['Display'].strip(),'confidence':float(best['Confidence']),
                    'alternatives':[{'text':item['Display'].strip(),'confidence':float(item['Confidence'])}
                                    for item in valid[:3]],
                    'language':language,'provider':'Azure Speech F0'}
        # Retain compatibility with a service response that omits NBest, while
        # marking it as unscored so callers can apply their own safety policy.
        text=result.get('DisplayText')
        if not isinstance(text,str) or not text.strip():
            raise ValueError('Speech recognition returned no transcript candidate')
        return {'text':text.strip(),'confidence':None,'alternatives':[],
                'language':language,'provider':'Azure Speech F0'}
