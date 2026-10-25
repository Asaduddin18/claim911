"""Separate canonical reference values from their deterministic spoken forms."""
import re

DIGITS=dict(zip('0123456789','zero one two three four five six seven eight nine'.split()))
PHONETIC=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
 'Alfa Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima Mike November Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey X-ray Yankee Zulu'.split()))


def readback(reference):
    if not isinstance(reference,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/-]{0,99}',reference):
        raise ValueError('Bounded canonical identifier required')
    def words(phonetic):
        return ', '.join('hyphen' if char=='-' else 'slash' if char=='/' else DIGITS[char] if char.isdigit()
                         else PHONETIC[char.upper()] if phonetic else char.upper() for char in reference)
    return {'canonical':reference,'spoken':words(False),'phonetic':words(True)}


def readbacks(values):
    return {name:readback(value) for name,value in values.items()}
