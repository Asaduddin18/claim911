"""Bounded synthetic desk dialogue using the same isolated Pipecat audio path."""
import base64
from sandbox.stdio_control import run_worker


def converse(*,gateway,capability,speech,actor_reply,initial_text,language,done,max_turns=20,on_turn=None,on_progress=None):
    if type(max_turns) is not int or not 1<=max_turns<=20:raise ValueError('Bounded conversation turns required')
    utterance=initial_text;turns=[];events=[];actor_history=[]
    for _ in range(max_turns):
        if not isinstance(utterance,str) or not 0<len(utterance)<=2000:raise ValueError('Bounded role-private actor response required')
        audio=speech.synthesize(utterance,language)
        if not 0<len(audio)<=640000 or len(audio)%2:
            raise ValueError("PARTICIPANT_AUDIO_EXCEEDS_20_SECONDS")
        pending={'participant_text':utterance,'pcm_base64':base64.b64encode(audio).decode()}
        def progress(current_events):
            for event in current_events:
                if event['operation']=='transcribe' and event.get('text'):pending['recognized_text']=event['text']
                if event['operation']=='reply' and event.get('text'):pending['assistant_text']=event['text']
            if on_progress is not None:on_progress({'turns':turns,'events':events+current_events,'pending':pending,'pipecat_turns':len(turns)//2})
        if on_progress is not None:
            progress([])
            result=run_worker(gateway,capability,audio,on_event=progress)
        else:result=run_worker(gateway,capability,audio)
        recognized=next(e['text'] for e in result['events'] if e['operation']=='transcribe')
        turns.extend([{'speaker':'participant','text':recognized,'pcm_base64':base64.b64encode(audio).decode()},
                      {'speaker':'assistant','text':result['text'],'pcm_base64':base64.b64encode(result['audio']).decode()}])
        events.extend(result['events'])
        if on_turn is not None:on_turn({'turns':turns,'events':events,'pipecat_turns':len(turns)//2})
        actor_history.extend([{'role':'assistant','content':utterance},{'role':'user','content':result['text']}])
        if done():return {'turns':turns,'events':events,'completed_objective':True,'pipecat_turns':len(turns)//2}
        if len(turns)//2==max_turns:break
        utterance=actor_reply(actor_history)
    return {'turns':turns,'events':events,'completed_objective':False,'pipecat_turns':max_turns}
