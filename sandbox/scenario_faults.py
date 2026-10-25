"""Implemented institution seed faults, separate from voice-provider fault tests."""
from fastapi import HTTPException

SEED_FAULTS={'unsigned_summary','wrong_admission_invoice','old_bill','withheld_receipt','pending_insurer','denied_insurer','desk_unavailable'}


def validate_faults(values):
    if (not isinstance(values,list) or len(values)>7 or any(not isinstance(v,str) or v not in SEED_FAULTS for v in values)
        or len(values)!=len(set(values))):
        raise HTTPException(422,'Choose distinct implemented scenario faults')
    if {'pending_insurer','denied_insurer'}<=set(values):raise HTTPException(422,'Choose either pending review or issued denial, not both')
    return sorted(values)
