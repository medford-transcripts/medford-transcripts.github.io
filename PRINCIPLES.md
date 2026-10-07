# Principles

Standing constraints on this archive. These are not preferences to be
re-litigated per feature; they are the shape of the thing. If a change would
violate one, the change is wrong, not the principle.

## 1. The archive makes GOVERNMENT legible to the public, never individuals legible to institutions

This is the whole premise and the line everything else follows from. Making
public proceedings searchable corrects an asymmetry: the city already knows
what happened in its meetings, and the public does not. That is the service.

The same techniques pointed at ATTENDEES rather than OFFICIALS invert it —
they make individuals legible to whoever holds the index. That is a different
product with the opposite effect, and this archive does not build it.

## 2. Identification is limited to people who put themselves on the record

Three populations appear in a meeting recording, and they are not alike:

- **Officials and staff acting in official capacity.** Identify freely. Who
  said what in the conduct of public business IS the record.
- **People who chose to speak.** A public commenter steps to a microphone and
  usually states a name and address. Identify them; they addressed a public
  body on the record.
- **People merely present.** In the gallery, in frame, never spoke. **Never
  identify, never index, never count.** They consented to nothing. An
  attendance sheet of who showed up to a public meeting is the exact artifact
  that discourages showing up.

## 3. Biometrics are never published

Voiceprints (`embeddings.pkl`) and any future face representation are
biometric data. They stay out of the public repo, permanently. The published
artifact is the transcript and the name beside a speaker — never the
measurement that produced it.

Where a biometric must be stored at all, prefer a form that cannot be used
against anything outside this corpus:

- Store the VERDICT, not the vector, where that is affordable — the pairwise
  "cluster A is cluster B" graph, which is what `speaker_ids` cross-references
  already are.
- Where vectors are needed, transform them under a secret key held separately
  in `credentials/` (a keyed random projection preserves similarity, so
  matching still works, while a leaked template is inert without the key —
  and is cancelable by re-keying, which a face itself is not).
- Never keep the raw embedding after enrollment. Transform once, discard the
  original; then it does not exist to be leaked, seized, or inherited.

This does not defeat a court order or a compromised machine, and nothing
does. It defeats the realistic failure: templates escaping on their own.

## 4. Automation must earn its confidence by measurement

Identification at scale REQUIRES automation. 2,300 meetings and 676
unidentified clusters will not be reviewed by hand, and the fidelity every
other feature depends on comes from identifying speakers — not from being
cautious about identifying them. An archive that stays anonymous to stay safe
has failed at its own purpose.

What is NOT permitted is automation whose error rate nobody has measured.
This project's history is a list of passes that were confidently wrong:

- a title cue reported "0 contradictions" and was 29% wrong, because it scored
  the unverifiable remainder as success and wrote five organisations in as
  speakers
- open-vocabulary name extraction measured 95.7% disagreement and invented
  29,342 "distinct speakers" in a city with 1,229
- closed-set error is a function of candidate-set size: 0.0% wrong at two
  candidates, 29.6% at 1,229
- short-turn attribution measures 53-66% against a human reference, against
  97% on substantive speech

So: measure the error rate against ground truth before a pass writes anything,
state the number, and gate on it. Automate freely above the line. Queue for
review below it — not because review is virtuous, but because an unmeasured
rate is an unknown quantity of false claims about real people, published under
our name.

A REVIEW GATE IS NOT A SECURITY CONTROL. Anyone forking this deletes it in one
line, and the barrier to misuse was never that step. The reason for review is
correctness, and it applies to us.

A name on the wrong speaker is this project's worst failure mode, and the
reason for the closed candidate set, the full-name-only rule, and the
provenance tiers in §5.

## 5. Corrections and provenance are append-only in spirit

Every identification records where it came from. `manual` and
`backfill_high_confidence` are PROTECTED and machine passes must not overwrite
them. A machine may always propose; it may never silently replace a human
judgement.

## 6. The city's own words are quoted, not corrected

Meeting titles, agendas and body names are reproduced as the city published
them, including when they are wrong (`06.24.2017 MSC Special Meeting` is a
2024 meeting). The archive adds context beside the record — a corrected date
in metadata, a subject line from the summary — rather than rewriting what the
city said. What we assert in our own voice must be ours to defend.
