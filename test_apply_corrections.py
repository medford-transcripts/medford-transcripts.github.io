"""Regression tests for applying corrections to transcripts.

WHY THESE EXIST: this code writes to the archive. Every test below is a way an
earlier version of it destroyed data, found by applying two real corrections
and reading the diff:

  * treating a rendered line as ONE srt block, when it spans several, wrote the
    whole paragraph into the first block and left the rest duplicated
  * rebuilding the span as one block per turn deleted the sentence-level
    timestamps inside a paragraph -- the <a href> anchors and the player's
    fallback
  * stretching each block's end to the next block's start swallowed the real
    pauses, rewriting the timing of every block in a file to fix one label
  * writing LF back to a CRLF file produced a 4,935-line diff for a one-line
    change

Run:  python -m pytest test_apply_corrections.py -q
"""

import unittest

import apply_corrections as ap
import srt_lines as sl

SRT = (
    "1\r\n00:00:10,000 --> 00:00:12,000\r\n[SPEAKER_04]: Thank you, really appreciate this.\r\n"
    "\r\n"
    "2\r\n00:00:13,000 --> 00:00:14,500\r\n[SPEAKER_04]: Seems really well thought out.\r\n"
    "\r\n"
    "3\r\n00:00:16,000 --> 00:00:18,000\r\n[SPEAKER_04]: Completely open honors.\r\n"
    "\r\n"
    "4\r\n00:00:19,000 --> 00:00:20,000\r\n[SPEAKER_04]: Great, thank you.\r\n"
    "\r\n"
    "5\r\n00:00:21,000 --> 00:00:22,000\r\n[SPEAKER_09]: Next item.\r\n"
    "\r\n"
)

MAPPING = {"SPEAKER_04": "Mike Mastrobuoni",
           "SPEAKER_01": "Chad Fallon",
           "SPEAKER_09": "Paul Ruseau"}


class Parsing(unittest.TestCase):

    def test_roundtrip_timestamp(self):
        for v in (0.0, 1.5, 83.456, 5764.554, 3600.999):
            self.assertAlmostEqual(sl.to_seconds(sl.to_timestamp(v)), v, places=3)

    def test_blocks_parse(self):
        b = sl.parse_srt(SRT)
        self.assertEqual(len(b), 5)
        self.assertEqual(b[0]["speaker"], "SPEAKER_04")
        self.assertAlmostEqual(b[0]["start"], 10.0)
        self.assertAlmostEqual(b[0]["end"], 12.0)

    def test_render_is_valid_and_renumbered(self):
        b = sl.parse_srt(SRT)
        del b[1]
        again = sl.parse_srt(sl.render_srt(b))
        self.assertEqual(len(again), 4)


class LineSpan(unittest.TestCase):
    """A rendered <p class="line"> is consecutive blocks by ONE speaker."""

    def setUp(self):
        self.blocks = sl.parse_srt(SRT)

    def test_span_covers_all_same_speaker_blocks(self):
        i = sl.find_block(self.blocks, 10.0)
        self.assertEqual(sl.line_span(self.blocks, i), (0, 4))

    def test_span_stops_at_speaker_change(self):
        lo, hi = sl.line_span(self.blocks, 0)
        self.assertEqual(self.blocks[hi]["speaker"], "SPEAKER_09")

    def test_line_text_is_what_the_reader_sees(self):
        lo, hi = sl.line_span(self.blocks, 0)
        text = sl.line_text(self.blocks, lo, hi)
        # the whole paragraph, not just the first 34-character block
        self.assertIn("Thank you", text)
        self.assertIn("Great, thank you.", text)
        self.assertGreater(len(text), 100)

    def test_find_block_rejects_a_bad_timestamp(self):
        self.assertIsNone(sl.find_block(self.blocks, 999.0))


class Realign(unittest.TestCase):

    def setUp(self):
        self.blocks = sl.parse_srt(SRT)

    def turns(self, *pairs):
        return [{"speaker": s, "text": t} for s, t in pairs]

    def test_speaker_split_keeps_every_block_boundary(self):
        """THE BUG: rebuilding as one block per turn deleted the sentence
        timestamps inside the paragraph."""
        turns = self.turns(
            ("Mike Mastrobuoni", "Thank you, really appreciate this. "
                                 "Seems really well thought out. "
                                 "Completely open honors."),
            ("Chad Fallon", "Great, thank you."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        self.assertEqual(len(out), 4)                     # all four survive
        self.assertEqual(out[-1]["speaker"], "SPEAKER_01")  # reattributed
        self.assertEqual([b["speaker"] for b in out[:3]], ["SPEAKER_04"] * 3)

    def test_original_timings_are_preserved(self):
        """THE BUG: ends were stretched to the next start, eating the pauses."""
        turns = self.turns(
            ("Mike Mastrobuoni", "Thank you, really appreciate this. "
                                 "Seems really well thought out. "
                                 "Completely open honors."),
            ("Chad Fallon", "Great, thank you."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        for i in range(4):
            self.assertAlmostEqual(out[i]["start"], self.blocks[i]["start"], places=3)
            self.assertAlmostEqual(out[i]["end"], self.blocks[i]["end"], places=3)

    def test_a_word_fix_changes_only_that_block(self):
        turns = self.turns(
            ("Mike Mastrobuoni", "Thank you, really appreciate this. "
                                 "Seems really well thought out. "
                                 "Completely open honours. "
                                 "Great, thank you."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        self.assertEqual(len(out), 4)
        self.assertEqual(out[0]["text"], self.blocks[0]["text"])
        self.assertEqual(out[1]["text"], self.blocks[1]["text"])
        self.assertIn("honours", out[2]["text"])
        self.assertEqual(out[3]["text"], self.blocks[3]["text"])

    def test_omitted_content_drops_its_block(self):
        """The form's contract is that the text REPLACES the original, so text
        the submitter leaves out is deleted. That is correct but destructive,
        so apply_one reports it rather than doing it silently -- and the
        truncation guard in ingest catches the accidental version."""
        turns = self.turns(
            ("Mike Mastrobuoni", "Thank you, really appreciate this. "
                                 "Seems really well thought out. "
                                 "Completely open honors."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        self.assertEqual(len(out), 3)

    def test_names_resolve_to_existing_speaker_labels(self):
        turns = self.turns(("Chad Fallon", "Thank you, really appreciate this. "
                                           "Seems really well thought out. "
                                           "Completely open honors."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        self.assertTrue(all(b["speaker"] == "SPEAKER_01" for b in out))

    def test_unknown_name_passes_through_literally(self):
        turns = self.turns(("Someone New", "Thank you, really appreciate this. "
                                           "Seems really well thought out. "
                                           "Completely open honors."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        self.assertEqual(out[0]["speaker"], "Someone New")

    def test_times_never_go_backwards(self):
        turns = self.turns(
            ("Mike Mastrobuoni", "Thank you, really appreciate this."),
            ("Chad Fallon", "Seems really well thought out. "
                            "Completely open honors. Great, thank you."))
        out = ap.realign(self.blocks, 0, 4, turns, MAPPING)
        for i in range(1, len(out)):
            self.assertGreaterEqual(out[i]["start"], out[i - 1]["start"])


class FileFormat(unittest.TestCase):
    """THE BUG: writing LF to a CRLF file rewrote every line."""

    def test_crlf_is_preserved(self):
        out = ap.match_format(sl.render_srt(sl.parse_srt(SRT)), SRT)
        self.assertIn("\r\n", out)
        self.assertNotIn("\n\n\n", out)

    def test_lf_file_stays_lf(self):
        lf = SRT.replace("\r\n", "\n")
        out = ap.match_format(sl.render_srt(sl.parse_srt(lf)), lf)
        self.assertNotIn("\r", out)

    def test_trailing_blank_line_is_kept(self):
        out = ap.match_format(sl.render_srt(sl.parse_srt(SRT)), SRT)
        self.assertTrue(out.endswith("\r\n\r\n"))

    def test_unchanged_content_reproduces_the_file(self):
        """The strongest guarantee: a no-op apply must be byte-identical."""
        out = ap.match_format(sl.render_srt(sl.parse_srt(SRT)), SRT)
        self.assertEqual(out, SRT)


class SpeakerNaming(unittest.TestCase):

    def test_unnamed_label_detected(self):
        self.assertTrue(ap.is_unnamed("SPEAKER_00", {"SPEAKER_00": "SPEAKER_00"}))

    def test_cross_video_pointer_counts_as_unnamed(self):
        # track_speakers leaves machine pointers, not human names
        self.assertTrue(ap.is_unnamed("SPEAKER_08",
                                      {"SPEAKER_08": "a17_UOV__Vs_SPEAKER_20"}))

    def test_real_name_is_not_unnamed(self):
        self.assertFalse(ap.is_unnamed("SPEAKER_04", MAPPING))

    def test_label_lookup_is_case_insensitive(self):
        self.assertEqual(ap.label_for_name("chad fallon", MAPPING), "SPEAKER_01")

    def test_unknown_name_has_no_label(self):
        self.assertIsNone(ap.label_for_name("Nobody At All", MAPPING))


if __name__ == "__main__":
    unittest.main()
