"""Shared spoken-call conventions used by every Claim911 voice role."""
import re


def normalize_spoken_text(text):
    text=str(text or '').lower().replace('’',"'")
    text=re.sub(r"\bthat(?:'|\s+)s\b",'that is',text)
    text=re.sub(r'\bclaim\s*(?:911|9\s+1\s+1)\b','claim911',text)
    return ' '.join(re.sub(r'[^a-z0-9 ]',' ',text).split())

COMMON_CALL_CLOSING_NOTE = "Thanks, that's all I need for this call."
CAREGIVER_INTAKE_CLOSING = (
    'Claim911 will check with the hospital and insurer, then show you what they confirm. '
    + COMMON_CALL_CLOSING_NOTE
)

COMMON_CALL_CLOSING_INSTRUCTION = (
    "COMMON END-OF-CALL RULE: After this call's required report or action has "
    "returned, state its actual result and any remaining step in plain language. "
    f"Then finish with this exact sentence: '{COMMON_CALL_CLOSING_NOTE}' "
    "The synthetic browser call ends when Claim911 hears that sentence. Do not "
    "use it before the required operation returns. If a refusal, uncertainty, "
    "or tool failure stops the task, explain that truthfully before closing."
)


def append_common_closing(objective):
    return f"{objective.rstrip()}\n\n{COMMON_CALL_CLOSING_INSTRUCTION}"


def report_speech(text,*,complete=True):
    """A bounded utterance, separate from instructions the agent must not read."""
    text=text.strip()
    if complete and not text.endswith(COMMON_CALL_CLOSING_NOTE):
        text+=' '+COMMON_CALL_CLOSING_NOTE
    if len(text.split())>55:raise ValueError('Report speech must remain a short spoken result')
    return {'spoken_outcome':text,'call_complete':complete,
            'instruction':('Say spoken_outcome exactly, then end this call. Do not recap confirmed identifiers, timestamps or documents.'
                           if complete else 'Say spoken_outcome and continue the required task. Do not use the closing note yet.')}


