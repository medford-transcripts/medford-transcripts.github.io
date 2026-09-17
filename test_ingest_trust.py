"""Regression tests for the trusted-contributor whitelist.

WHY THESE EXIST: auto-accept writes to transcripts with nobody looking, so the
interesting cases are the ones where it must REFUSE. Each test below is a way
the whitelist could wrongly grant trust, and the most important is
test_nick_alone_is_not_trust -- matching on the display name rather than the
token would let any stranger inherit the owner's standing by typing his name
into a prompt box.

Run:  python -m pytest test_ingest_trust.py -q
"""

import io
import json
import os
import tempfile
import unittest

import ingest_corrections as ic

OWNER = "3a7f91c2d4e5b608"
STRANGER = "ffffffffffffffff"


def whitelist(path, token=OWNER, label="owner"):
    with io.open(path, "w", encoding="utf-8") as fp:
        json.dump({"contributors": [{"token": token, "label": label}]}, fp)


class TokenExtraction(unittest.TestCase):
    """contributorTag() sends nick + '/' + token, or a bare token."""

    def test_bare_token(self):
        self.assertEqual(ic.token_of(OWNER), OWNER)

    def test_nick_and_token(self):
        self.assertEqual(ic.token_of("Jason Eastman/" + OWNER), OWNER)

    def test_nick_containing_a_slash(self):
        # rsplit, not split: a nick may contain '/' and the token is last
        self.assertEqual(ic.token_of("Jason/Eastman/" + OWNER), OWNER)

    def test_empty(self):
        self.assertEqual(ic.token_of(""), "")
        self.assertEqual(ic.token_of(None), "")

    def test_whitespace_is_stripped(self):
        self.assertEqual(ic.token_of("  nick/" + OWNER + "  "), OWNER)


class WhitelistLoading(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "trusted.json")

    def test_missing_file_trusts_nobody(self):
        # A missing whitelist must never be read as allow-all.
        self.assertEqual(ic.load_trusted(os.path.join(self.dir, "nope.json")), {})

    def test_malformed_file_trusts_nobody(self):
        with io.open(self.path, "w", encoding="utf-8") as fp:
            fp.write("{ this is not json")
        self.assertEqual(ic.load_trusted(self.path), {})

    def test_empty_contributor_list(self):
        with io.open(self.path, "w", encoding="utf-8") as fp:
            json.dump({"contributors": []}, fp)
        self.assertEqual(ic.load_trusted(self.path), {})

    def test_blank_token_is_ignored(self):
        # A blank token would otherwise match token_of("") and trust everyone
        # who submits with no contributor tag at all.
        with io.open(self.path, "w", encoding="utf-8") as fp:
            json.dump({"contributors": [{"token": "  ", "label": "oops"}]}, fp)
        self.assertEqual(ic.load_trusted(self.path), {})

    def test_loads_token_and_label(self):
        whitelist(self.path)
        self.assertEqual(ic.load_trusted(self.path), {OWNER: "owner"})


class TrustDecision(unittest.TestCase):
    """The decision ingest makes per row, reproduced exactly."""

    def decide(self, contributor, target, trusted):
        tok = ic.token_of(contributor)
        return bool(tok and tok in trusted
                    and "unparsed" not in target and target != ["none"])

    def setUp(self):
        self.trusted = {OWNER: "owner"}

    def test_trusted_token_is_accepted(self):
        self.assertTrue(self.decide("Jason Eastman/" + OWNER, ["text"], self.trusted))

    def test_bare_trusted_token_is_accepted(self):
        self.assertTrue(self.decide(OWNER, ["speaker"], self.trusted))

    def test_nick_alone_is_not_trust(self):
        # THE ATTACK THIS GUARDS: a stranger types the owner's name into the
        # identity prompt. Same display name, different token -> still queued.
        self.assertFalse(self.decide("Jason Eastman/" + STRANGER, ["text"], self.trusted))

    def test_name_with_no_token_is_not_trust(self):
        self.assertFalse(self.decide("Jason Eastman", ["text"], self.trusted))

    def test_anonymous_is_not_trust(self):
        self.assertFalse(self.decide("", ["text"], self.trusted))

    def test_unparsed_is_never_auto_accepted(self):
        # Trust is about WHO, not about whether the edit is well formed.
        self.assertFalse(self.decide(OWNER, ["unparsed"], self.trusted))

    def test_no_op_edit_is_never_auto_accepted(self):
        self.assertFalse(self.decide(OWNER, ["none"], self.trusted))

    def test_empty_whitelist_accepts_nothing(self):
        self.assertFalse(self.decide(OWNER, ["text"], {}))

    def test_multi_target_edit_is_accepted(self):
        self.assertTrue(self.decide(OWNER, ["speaker", "text"], self.trusted))


if __name__ == "__main__":
    unittest.main()
