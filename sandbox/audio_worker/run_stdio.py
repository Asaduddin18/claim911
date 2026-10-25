"""Pipecat runner with a bounded stdio broker channel and no network access.

Only synthetic audio and scoped operation results cross stdin/stdout. The trusted
controller associates the process with its grant; no credentials enter this image.
"""
import asyncio,base64,json,sys
from uuid import uuid4
sys.path.insert(0,'/app')
from pipecat.frames.frames import InputAudioRawFrame,UserStoppedSpeakingFrame,TTSAudioRawFrame,TextFrame,EndFrame,ErrorFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker,PipelineParams
from pipecat.workers.runner import WorkerRunner
from pipeline import BrokerSTT,BrokerConversation,BrokerTTS


class StdioBrokerClient:
    async def request(self,operation,body):
        if operation not in {'transcribe','reply','synthesize'}:raise ValueError('Unsupported scoped operation')
        id=str(uuid4())
        print(json.dumps({'type':'request','operation':operation,'body':{'request_id':id,**body}}),flush=True)
        line=await asyncio.to_thread(sys.stdin.readline,2_000_001)
        if len(line)>2_000_000:raise ValueError('Oversized broker response')
        result=json.loads(line)
        if result.get('request_id')!=id or result.get('status')!=200:raise ValueError('Scoped broker operation failed')
        return result['result']


async def main():
    input=json.loads(sys.stdin.readline(900001))
    if set(input)!={'pcm_base64','sample_rate','channels'} or input['sample_rate']!=16000 or input['channels']!=1:
        raise ValueError('Synthetic mono PCM input required')
    pcm=base64.b64decode(input['pcm_base64'],validate=True)
    if not 0<len(pcm)<=640000 or len(pcm)%2:raise ValueError('Input utterance bound exceeded')
    client=StdioBrokerClient();output={'text':[],'audio':bytearray(),'errors':[]}
    class Capture(FrameProcessor):
        async def process_frame(self,frame,direction):
            await super().process_frame(frame,direction)
            if isinstance(frame,TextFrame):output['text'].append(frame.text)
            if isinstance(frame,TTSAudioRawFrame):
                output['audio'].extend(frame.audio)
                await worker.queue_frame(EndFrame())
            if isinstance(frame,ErrorFrame):
                output['errors'].append(frame.error)
                await worker.queue_frame(EndFrame())
            await self.push_frame(frame,direction)
    worker=PipelineWorker(Pipeline([BrokerSTT(client),BrokerConversation(client),BrokerTTS(client),Capture()]),
       params=PipelineParams(audio_in_sample_rate=16000,audio_out_sample_rate=16000),
       enable_rtvi=False,enable_turn_tracking=False)
    @worker.event_handler('on_pipeline_started')
    async def started(worker,frame):
        await worker.queue_frames([InputAudioRawFrame(audio=pcm,sample_rate=16000,num_channels=1),UserStoppedSpeakingFrame()])
    runner=WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await asyncio.wait_for(runner.run(),timeout=110)
    success=bool(output['audio'] and not output['errors'])
    print(json.dumps({'type':'result','passed':success,'text':output['text'],
      'pcm_base64':base64.b64encode(output['audio']).decode(),'errors':output['errors'],
      'provenance':'PIPECAT_PIPELINE_STDIO_BROKER','sample_rate':16000,'channels':1}),flush=True)
    if not success:raise SystemExit(1)


try:asyncio.run(main())
except Exception as exc:
    print(json.dumps({'type':'result','passed':False,'error_type':type(exc).__name__}),flush=True)
    raise SystemExit(1)
