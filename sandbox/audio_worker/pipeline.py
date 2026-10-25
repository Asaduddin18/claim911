"""Pipecat audio stages backed only by the trusted synthetic speech broker.

The worker never receives cloud credentials, institution credentials or model
deployment choices. The broker owns conversation context and scoped tool writes.
"""
import base64
from datetime import datetime,timezone
import httpx
from uuid import uuid4
from pipecat.frames.frames import (
    InputAudioRawFrame,UserStoppedSpeakingFrame,TranscriptionFrame,TextFrame,
    TTSAudioRawFrame,LLMFullResponseStartFrame,LLMFullResponseEndFrame,
    InterruptionFrame,ErrorFrame,
)
from pipecat.processors.frame_processor import FrameProcessor,FrameDirection


class SpeechBrokerClient:
    def __init__(self,capability):
        self._client=httpx.AsyncClient(base_url='http://speech-broker:8080',
            headers={'Authorization':'Bearer '+capability},timeout=45,
            trust_env=False,follow_redirects=False)

    async def request(self,operation,body):
        if operation not in {'transcribe','reply','synthesize'}:
            raise ValueError('Unknown synthetic speech operation')
        response=await self._client.post('/audio/'+operation,json={'request_id':str(uuid4()),**body})
        response.raise_for_status()
        if len(response.content)>2_000_000:raise ValueError('Oversize broker response')
        return response.json()

    async def close(self):await self._client.aclose()


class BrokerSTT(FrameProcessor):
    def __init__(self,client,**kwargs):
        super().__init__(**kwargs);self.client=client;self._audio=bytearray();self._overflow=False

    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction!=FrameDirection.DOWNSTREAM:
            await self.push_frame(frame,direction);return
        if isinstance(frame,InterruptionFrame):
            self._audio.clear();self._overflow=False
        if isinstance(frame,InputAudioRawFrame):
            if frame.sample_rate!=16000 or frame.num_channels!=1:
                self._audio.clear();self._overflow=True
                await self.push_frame(ErrorFrame(error='Sandbox audio must be 16 kHz mono PCM'));return
            if len(self._audio)+len(frame.audio)>640000:
                self._audio.clear();self._overflow=True;return
            if not self._overflow:self._audio.extend(frame.audio)
            return
        if isinstance(frame,UserStoppedSpeakingFrame):
            audio=bytes(self._audio);self._audio.clear()
            if self._overflow:
                self._overflow=False
                await self.push_frame(ErrorFrame(error='Sandbox utterance exceeded 20 seconds'));return
            if audio:
                try:
                    result=await self.client.request('transcribe',{'pcm_base64':base64.b64encode(audio).decode(),'sample_rate':16000,'channels':1})
                    text=result['text']
                    if not isinstance(text,str) or len(text)>4000:raise ValueError()
                    if text.strip():await self.push_frame(TranscriptionFrame(text=text,user_id='synthetic-participant',timestamp=datetime.now(timezone.utc).isoformat(),finalized=True))
                except Exception:
                    await self.push_frame(ErrorFrame(error='Sandbox transcription unavailable; turn was not executed'))
        await self.push_frame(frame,direction)


class BrokerConversation(FrameProcessor):
    def __init__(self,client,**kwargs):super().__init__(**kwargs);self.client=client

    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction==FrameDirection.DOWNSTREAM and isinstance(frame,TranscriptionFrame):
            try:
                result=await self.client.request('reply',{'text':frame.text})
                text=result['text']
                if not isinstance(text,str) or len(text)>4000:raise ValueError()
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(TextFrame(text=text))
                await self.push_frame(LLMFullResponseEndFrame())
            except Exception:
                # Do not retry: a scoped tool may have executed before failure.
                await self.push_frame(ErrorFrame(error='Sandbox conversation result uncertain; reconcile before retry'))
            return
        await self.push_frame(frame,direction)


class BrokerTTS(FrameProcessor):
    def __init__(self,client,**kwargs):super().__init__(**kwargs);self.client=client

    async def process_frame(self,frame,direction):
        await super().process_frame(frame,direction)
        if direction==FrameDirection.DOWNSTREAM and isinstance(frame,TextFrame) and not isinstance(frame,TranscriptionFrame):
            try:
                result=await self.client.request('synthesize',{'text':frame.text})
                audio=base64.b64decode(result['pcm_base64'],validate=True)
                if result['sample_rate']!=16000 or len(audio)>1_280_000 or len(audio)%2:raise ValueError()
                await self.push_frame(frame,direction)
                await self.push_frame(TTSAudioRawFrame(audio=audio,sample_rate=16000,num_channels=1))
            except Exception:
                await self.push_frame(ErrorFrame(error='Sandbox speech unavailable; text is not audio proof'))
            return
        await self.push_frame(frame,direction)
