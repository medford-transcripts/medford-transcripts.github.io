"""
Regression tests for the transcript replacement rules.

These exist because the rules have now been wrong in TWO opposite directions,
and a change that fixes one silently breaks the other:

  1. Unanchored str.replace() corrupted 935 of 2,273 transcripts, rewriting
     residents' surnames -- Moxley -> Marksley, Maxwell -> Markswell,
     McKernan -> Lungo-Koehnan, Beasley -> Bearsley.

  2. Naive word-boundary anchoring then stopped correcting PLURALS, because
     the rule table contains no plural forms at all -- all 151 single-word
     rules had been relying on substring matching to pluralise for free. That
     would have reverted "Councilors" to "counselors" across the archive.

Both directions are covered below. Run before any rule change or sweep:

    python test_fix_common_errors.py
"""

import importlib.util
import sys

import fix_common_errors as fce


def rules():
    spec = importlib.util.spec_from_file_location("fme", "find_manual_edits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_rules()


PATTERNS = fce.compile_rules(rules())


def fix(text):
    return fce.apply_rules(text, PATTERNS)


CASES = [
    # --- the rules must still do their job ---------------------------------
    ("Counselor Bears spoke",           "Councilor Bears spoke"),
    ("Councillor Collins",              "Councilor Collins"),
    ("the counselor said",              "the Councilor said"),
    ("city of Method",                  "city of Medford"),

    # --- PLURALS: the table has no plural forms, so the pattern must
    #     supply them or these silently stop being corrected ---------------
    ("talk with the other counselors",  "talk with the other Councilors"),
    ("Councillors voted",               "Councilors voted"),

    # --- WORD BOUNDARIES: real surnames that contain a rule key ------------
    ("Moxley lives on Salem St",        "Moxley lives on Salem St"),
    ("Maxwell and Beasley spoke",       "Maxwell and Beasley spoke"),
    ("Ms. McKernan asked",              "Ms. McKernan asked"),
    ("Roussell was present",            "Roussell was present"),

    # --- CONTEXT: a school guidance counselor is not a city Councilor ------
    ("the guidance counselor said",     "the guidance counselor said"),
    ("Do you and the guidance counselors have plans?",
     "Do you and the guidance counselors have plans?"),
    ("Guidance counselors are here",    "Guidance counselors are here"),

    # --- rules that depend on surrounding whitespace must survive ----------
    # (a blanket \b would break these: \b next to a space asserts the
    #  opposite of what is wanted)
    ("item 15 dash 402",                "item 15-402"),

    # --- CONTEXTUAL NAME RULES: mis-heard councilors get corrected... -------
    ("Councilor Moxley?",               "Councilor Marks?"),
    ("On motion by Councilor Maxwell.", "On motion by Councilor Marks."),
    ("Councilor McKernan?",             "Councilor Lungo-Koehn?"),
    ("President Bexar.",                "President Bears."),
    ("Councilor Scarpalli",             "Councilor Scarpelli"),
    # note the honorific is normalised too: "Councillor" -> "Councilor" is an
    # existing rule, so both the spelling and the name get corrected
    ("Councillor Maxx.",                "Councilor Marks."),

    # --- ...but the SAME surnames on real people must NOT be touched -------
    # This is the whole reason the rules are contextual. Only 38 of 111
    # "Maxwell" uses follow an honorific; the rest are real people.
    ("Fiona Maxwell, Shab Khan",        "Fiona Maxwell, Shab Khan"),
    ("the 2019 Maxwell Teacher of the Year",
     "the 2019 Maxwell Teacher of the Year"),
    ("musical legends as Leon Beal and Walter Beasley",
     "musical legends as Leon Beal and Walter Beasley"),
    ("At left wing, number 10, Brianna Scholl.",
     "At left wing, number 10, Brianna Scholl."),
    ("home for both myself and my wife, Brianna.",
     "home for both myself and my wife, Brianna."),

    # --- both spellings are School Committee member Erika Reinfeld ---------
    ("Member Rheinfeldt spoke",          "Member Reinfeld spoke"),
    ("Member Reinfeldt spoke",           "Member Reinfeld spoke"),
]



def main():
    failures = 0
    for src, want in CASES:
        got = fix(src)
        if got == want:
            print("PASS  %s" % src[:58])
        else:
            failures += 1
            print("FAIL  %s" % src)
            print("        want: %s" % want)
            print("        got : %s" % got)
    print("\n%d/%d passed" % (len(CASES) - failures, len(CASES)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
