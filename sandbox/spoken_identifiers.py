"""Lossless spoken-code normalization. No fuzzy reference correction."""
import re
from coordinator.identifier_readbacks import PHONETIC

PHONETIC_INPUT={word.casefold():letter.casefold() for letter,word in PHONETIC.items()}
PHONETIC_INPUT.update({'alpha':'a','juliet':'j','x ray':'x'})

DIGITS=dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine'),'0123456789'))


def normalize_identifier_speech(text):
    text=str(text).casefold()
    text=re.sub(r'\b(?:'+ '|'.join(re.escape(word) for word in sorted(PHONETIC_INPUT,key=len,reverse=True))+r')\b',lambda m:PHONETIC_INPUT[m[0]],text)
    text=re.sub(r'\bslash\b','/',text)
    text=re.sub(r'\b(?:hyphen|dash)\b','-',text)
    text=re.sub(r'\b(?:'+ '|'.join(DIGITS)+r')\b',lambda m:DIGITS[m[0]],text)
    text=re.sub(r'\b(?:[a-z]\s+)+[a-z]\b',lambda m:re.sub(r'\s+','',m[0]),text)
    text=re.sub(r'(?<=\d)\s+(?=\d)','',text)
    return re.sub(r'\s*-\s*','-',text)


def pronounce_role_identifiers(text,record):
    """Speak separators in actual role-owned identifiers, without changing facts."""
    identifiers=set()
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if (key in {'id','document_reference','dispatch_reference'} and isinstance(item,str)
                    and re.fullmatch(r'[a-z]+(?:[-/][a-z0-9]+)+',item)):
                    identifiers.add(item)
                elif isinstance(item,(dict,list)):visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(record)
    for identifier in sorted(identifiers,key=len,reverse=True):
        spoken=identifier.replace('-',' hyphen ').replace('/',' slash ')
        text=re.sub(r'(?<![A-Za-z0-9])'+re.escape(identifier)+r'(?![A-Za-z0-9])',lambda _:spoken,text)
    return text
