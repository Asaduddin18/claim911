# Case reconstruction and test oracle

## Public anchor

A public consumer account reports an initially represented cashless approval, an unresolved final authorization at discharge, a ₹1.9 lakh bill and conflicting explanations. It has not been independently verified. Original account: https://www.reddit.com/r/InsuranceTroubleIndia/comments/1lj7e01

## Synthetic additions

All patient identifiers, hospital/claims organizations, packet contents, timestamps, references, contact numbers configured for role play, submission channels and routing cause are synthetic. The account does not establish that an incorrect TPA destination caused the real incident. The simulation is not a real insurer integration or an insurance decision.

## Reproducible initial state

- Patient: DEMO-PATIENT-42, admission DEMO-ADMISSION-9.
- Initial authorization PREAUTH-077 is AUTHORIZED.
- Final authorization request HOSP-FINAL-1042 revision 1 was dispatched to old-tpa.example.invalid.
- Transport accepted it, but the designated claims queue has no matching final request.
- Medical readiness is READY; administrative authorization remains PENDING.

The `.invalid` destinations are inert routing labels. No documents are emailed to them.

## Institution operations

The hospital may inspect its case and dispatch history and submit a corrected revision. Only the claims service owns its received requests and signing key. Agent credentials can read the published demo routing directory and signed receipt evidence; they cannot read hidden case records, create submissions, issue receipts or access evaluator controls. Access in this simulator does not imply an institution would permit equivalent real-world access.

## Manual proof

1. Hospital reads its final-request dispatch record.
2. Claims searches the same case, patient, final request reference and request type.
3. Compare the dispatch destination with the designated route.
4. Hospital submits revision 2 with the full synthetic packet to the designated route.
5. Claims returns a signed receipt matching case, reference, revision and packet hash.
6. A verifier with only the claims public key validates that receipt.

Expected conclusion: routing blocker resolved; final authorization and discharge remain pending.

## Counterexamples

Already-received requests must not be needlessly resubmitted. Initial authorization cannot satisfy final-request receipt. Missing documents, wrong identifiers, withheld acknowledgment, wrong revision and invalid signatures must not produce success. A correct dispatch without receipt remains unverified.
