from sandbox.conversations import converse


def test_confirmation_question_does_not_end_the_dialogue_before_a_saved_report(monkeypatch):
    state={'turns':0,'saved':False};actor_history=[]
    class Speech:
        def synthesize(self,text,language):return b'\0\0'*160
    def worker(gateway,capability,audio):
        state['turns']+=1
        if state['turns']==2:state['saved']=True
        text='Please confirm the concern.' if state['turns']==1 else 'The confirmed report is recorded.'
        return {'text':text,'audio':b'\0\0'*160,'events':[{'operation':'transcribe','text':'Synthetic participant turn'}]}
    def actor(history):actor_history.extend(history);return 'Yes, that concern is correct.'
    monkeypatch.setattr('sandbox.conversations.run_worker',worker)
    result=converse(gateway=None,capability='fixture',speech=Speech(),actor_reply=actor,
        initial_text='My synthetic concern.',language='en',done=lambda:state['saved'],max_turns=3)
    assert result['completed_objective'] and result['pipecat_turns']==2
    assert len(result['turns'])==4
    assert actor_history[-1]['content']=='Please confirm the concern.'


def test_exhausted_dialogue_remains_incomplete_instead_of_claiming_success(monkeypatch):
    class Speech:
        def synthesize(self,*a):return b'\0\0'*160
    monkeypatch.setattr('sandbox.conversations.run_worker',lambda *a:{'text':'Still checking.','audio':b'\0\0'*160,'events':[{'operation':'transcribe','text':'Synthetic turn'}]})
    actor_calls=[]
    result=converse(gateway=None,capability='fixture',speech=Speech(),actor_reply=lambda history:actor_calls.append(history) or 'Please clarify.',
        initial_text='Hello.',language='en',done=lambda:False,max_turns=2)
    assert not result['completed_objective'] and result['pipecat_turns']==2
    assert len(actor_calls)==1 # Never buy an unused persona turn after exhaustion.


def test_oversized_participant_audio_stops_before_worker_or_model_request(monkeypatch):
    import pytest
    class Speech:
        def synthesize(self,*a):return b'\0\0'*320001
    invoked=[]
    monkeypatch.setattr('sandbox.conversations.run_worker',lambda *a:invoked.append(True))
    with pytest.raises(ValueError,match='PARTICIPANT_AUDIO_EXCEEDS_20_SECONDS'):
        converse(gateway=None,capability='fixture',speech=Speech(),actor_reply=lambda _: 'Unused',
                 initial_text='Synthetic long utterance.',language='en',done=lambda:False,max_turns=2)
    assert not invoked


def test_failed_speech_turn_keeps_recognized_input_and_unsynthesized_response_for_review(monkeypatch):
    import pytest
    class Speech:
        def synthesize(self,*a):return b'\0\0'*160
    progress=[]
    def worker(*a,on_event):
        on_event([{'operation':'transcribe','status':200,'text':'Confirmed synthetic reference.'},
                  {'operation':'reply','status':200,'text':'An unsynthesized model response.'}])
        raise RuntimeError('Synthetic speech provider failure')
    monkeypatch.setattr('sandbox.conversations.run_worker',worker)
    with pytest.raises(RuntimeError):
        converse(gateway=None,capability='fixture',speech=Speech(),actor_reply=lambda _: 'Unused',initial_text='Synthetic input.',
                 language='en',done=lambda:False,max_turns=1,on_progress=progress.append)
    assert progress[-1]['pending']['recognized_text']=='Confirmed synthetic reference.'
    assert progress[-1]['pending']['assistant_text']=='An unsynthesized model response.'
    assert progress[-1]['turns']==[] # Never label missing output audio as a completed turn.
