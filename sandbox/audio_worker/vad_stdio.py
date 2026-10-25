"""Silero speech boundaries only. No assistant, tools, network or credentials."""
import asyncio
import base64
import json
import sys
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams


async def main():
    vad=SileroVADAnalyzer(sample_rate=16000,params=VADParams(confidence=0.6,start_secs=0.12,stop_secs=0.7,min_volume=0))
    vad.set_sample_rate(16000)
    pending=bytearray();samples=0;previous='QUIET'
    print(json.dumps({'ready':True,'detector':'SILERO_PIPECAT','sample_rate':16000}),flush=True)
    try:
        for request_index in range(3000):
            line=sys.stdin.readline(900001)
            if not line:break
            if len(line)>900000:raise ValueError('VAD input bound exceeded')
            request=json.loads(line)
            if set(request)!={'id','pcm_base64'} or type(request['id']) is not int:raise ValueError('VAD request invalid')
            pcm=base64.b64decode(request['pcm_base64'],validate=True)
            if len(pcm)>640000 or len(pcm)%2:raise ValueError('Bounded 16 kHz mono PCM required')
            pending.extend(pcm);events=[]
            while len(pending)>=1024:
                frame=bytes(pending[:1024]);del pending[:1024];samples+=512
                if samples>16000*300:raise ValueError('VAD conversation limit reached')
                state=(await vad.analyze_audio(frame)).name
                if state!=previous:
                    events.append({'state':state,'audio_ms':samples/16});previous=state
            print(json.dumps({'id':request['id'],'events':events,'state':previous,'audio_ms':samples/16}),flush=True)
    finally:await vad.cleanup()


asyncio.run(main())
