# Synthetic reference speech

`reference-english.wav` contains Azure-generated English speech from the approved
project setup: "This is a synthetic hospital test. The discharge summary needs a
signature." It contains no real patient or institution information.

The local WebRTC capture regression uses this fixed fixture to test the receiver
audio path without synthesizing new speech or opening a Bolna call. Provider
speech recognition is an optional, separately configured assertion.
