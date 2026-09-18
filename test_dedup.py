"""Regression tests for title standardisation and duplicate detection.

WHY THESE EXIST: identify_duplicate_videos decides which recordings never
get transcribed. Getting it wrong in one direction wastes days of compute
(it had queued 161 hours of audio whose transcripts already existed); in the
other it silently drops a meeting from the archive. Each test is one of
those two failure directions.

Run:  python -m pytest test_dedup.py -q
"""

import os
import tempfile
import unittest

import utils


class TitleDate(unittest.TestCase):

    def test_common_formats(self):
        cases = {
            "Medford City Council 09-26-17": "2017-09-26",
            "3.13.2024 MSC FY25 Budget Committee of the Whole": "2024-03-13",
            "Medford, MA City Council - Sep. 26, 2017": "2017-09-26",
            "Community Development Board 09-02-26": "2026-09-02",
            "School Committee 2025-10-06": "2025-10-06",
            "Council Meeting September 2, 2026": "2026-09-02",
        }
        for title, want in cases.items():
            self.assertEqual(utils.title_date(title), want, title)

    def test_no_date_is_none(self):
        # dateutil's fuzzy parser used to read these as dates
        for t in ("Medford Happenings Episode 56", "#CottonSwabChallenge", "MCM00001286", ""):
            self.assertIsNone(utils.title_date(t), t)

    def test_title_date_after_upload_is_a_typo(self):
        # "01-20-26" on a video uploaded 2025-01-22: the year is wrong
        self.assertIsNone(utils.title_date("City Council 01-20-26", not_after="2025-01-22"))
        self.assertEqual(utils.title_date("City Council 01-20-26", not_after="2026-01-22"), "2026-01-20")

    def test_meeting_date_falls_back_to_stored(self):
        self.assertEqual(utils.meeting_date({"title": "no date here", "date": "2024-05-01"}), "2024-05-01")
        self.assertEqual(utils.meeting_date({"title": "Council 05-03-24", "date": "2024-05-05",
                                             "upload_date": "2024-05-05"}), "2024-05-03")


class TitleStem(unittest.TestCase):

    def test_true_duplicates_overlap(self):
        self.assertTrue(utils.titles_overlap("Medford City Council 09-26-17",
                                             "Medford, MA City Council - Sep. 26, 2017"))
        self.assertTrue(utils.titles_overlap("3.13.2024 MSC FY25 Budget Committee of the Whole",
                                             "Medford School Committee of the Whole 03-13-24"))

    def test_different_meetings_do_not(self):
        self.assertFalse(utils.titles_overlap("Medford Comprehensive Master Plan 10-20-22", "SEPAC 10.20"))
        self.assertFalse(utils.titles_overlap("10-10-17 Medford City Council", "#CottonSwabChallenge"))


def entry(title, channel, date, mt="CC City Council", **kw):
    e = {"title": title, "channel": channel, "date": date, "upload_date": date, "meeting_type": mt}
    e.update(kw)
    return e


class Dedup(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)

    def transcribed(self, yt_id, date):
        d = date + "_" + yt_id
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, d + ".srt"), "w").close()

    def run_dedup(self, data):
        return utils.identify_duplicate_videos(data, apply=False)["changes"]

    def test_official_beats_archive_when_neither_transcribed(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["B"], {"skip": True, "duplicate_id": "A"})
        self.assertEqual(ch["A"]["skip"], False)

    def test_lone_transcript_stays_visible_and_keeper_takes_back_seat(self):
        """Mass Traction is retiring: the MCM copy is the keeper even though the
        Mass Traction copy is the one already transcribed. Neither is hidden
        until the keeper is done; the keeper is flagged to wait its turn."""
        self.transcribed("A", "2017-09-27")
        data = {"A": entry("Medford, MA City Council - Sep. 26, 2017", "Mass Traction-US-Medford-1 - Government",
                           "2017-09-27", skip=True, duplicate_id="B"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["A"], {"skip": False, "duplicate_id": "B"})   # un-hidden
        self.assertEqual(ch["B"], {"skip": False, "duplicate_id": "A", "backseat": True})

    def test_once_keeper_is_transcribed_the_unofficial_copy_is_skipped(self):
        self.transcribed("A", "2017-09-27")
        self.transcribed("B", "2017-09-26")
        data = {"A": entry("Medford, MA City Council - Sep. 26, 2017", "Mass Traction-US-Medford-1 - Government", "2017-09-27"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26", backseat=True)}
        ch = self.run_dedup(data)
        self.assertEqual(ch["A"], {"skip": True, "duplicate_id": "B"})
        self.assertEqual(ch["B"], {"skip": False, "duplicate_id": "A", "backseat": False})

    def test_manual_correction_is_untouched(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26", manual_correction=True)}
        self.assertNotIn("B", self.run_dedup(data))

    def test_owner_or_guard_skip_is_untouched(self):
        # skip without duplicate_id was not set by dedup: never un-skip it
        self.transcribed("A", "2017-09-26")
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26",
                           skip=True, skip_reason="audio truncated"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        self.assertNotIn("A", self.run_dedup(data))

    def test_zero_overlap_is_not_a_duplicate(self):
        data = {"A": entry("Medford Comprehensive Master Plan 10-20-22", "MCM Archive", "2022-10-20", mt="MPS School Committee"),
                "B": entry("SEPAC 10.20", "Medford Public Schools", "2022-10-20", mt="MPS School Committee")}
        self.assertEqual(self.run_dedup(data), {})

    def test_same_channel_is_not_a_duplicate_unless_livestream(self):
        data = {"A": entry("City Council 09-26-17", "MCM Archive", "2017-09-26"),
                "B": entry("City Council 09-26-17 part 2", "MCM Archive", "2017-09-26")}
        self.assertEqual(self.run_dedup(data), {})
        mt = "Mass Traction-US-Medford-1 - Government"
        data = {"A": entry("City Council 09-26-17 Livestream", mt, "2017-09-26"),
                "B": entry("City Council 09-26-17", mt, "2017-09-26")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["A"]["skip"], True)       # the Livestream loses
        self.assertEqual(ch["B"]["skip"], False)

    def test_different_dates_never_pair(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-19-17", "MCM Archive", "2017-09-19")}
        self.assertEqual(self.run_dedup(data), {})

    def test_apply_false_does_not_mutate(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        self.run_dedup(data)
        self.assertNotIn("skip", data["B"])


if __name__ == "__main__":
    unittest.main()
