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


class SameRecording(unittest.TestCase):
    """The title test on its own rejected 76 true duplicates and passed 2,395
    pairs on the meeting_type's own name. These pin what replaced it."""

    def cc(self, ta, tb, mt="CC City Council", **kw):
        a = {"title": ta, "meeting_type": mt}
        b = {"title": tb, "meeting_type": mt}
        a.update(kw.get("a", {}))
        b.update(kw.get("b", {}))
        return utils.same_recording(a, b)

    def test_committee_abbreviation_is_not_a_disagreement(self):
        # 57 of the 76 lost pairs were this one: MSC = Medford School Committee
        self.assertTrue(self.cc("MSC Reg Meeting", "Medford School Committee Meeting",
                                mt="MPS School Committee"))
        self.assertTrue(self.cc("CPC", "Community Preservation Committee",
                                mt="CC Community Preservation Committee"))

    def test_typo_in_the_committee_name(self):
        self.assertTrue(self.cc("Medford City Councl", "Medford City Council"))

    def test_a_named_subject_still_has_to_overlap(self):
        # the guard test_zero_overlap_is_not_a_duplicate depends on: a title
        # naming a SUBJECT is evidence, an abbreviation of the committee is not
        self.assertFalse(self.cc("Medford Comprehensive Master Plan", "SEPAC",
                                 mt="MPS School Committee"))

    def test_episodic_needs_a_positive_signal(self):
        mt = "Medford Happenings"
        # the pair that started this: Castus mirror of the YouTube original
        self.assertTrue(self.cc("Medford Happenings Episode 58 Laura O'Neill",
                                "Medford Happenings - Laura O'Neil", mt=mt))
        # two different guests on one day are NOT one recording
        self.assertFalse(self.cc("Medford Happenings - Sam Sednek",
                                 "Medford Happenings - Chris Oates", mt=mt))
        # ...and the programme name alone is not a signal
        self.assertFalse(self.cc("Medford Happenings Episode 58",
                                 "Medford Happenings Episode 59", mt=mt))

    def test_episodic_matches_on_identical_duration_when_retitled(self):
        # MCM publishes "w/ John Petrella" to Castus as "Local Happenings Part 2"
        mt = "Medford Happenings"
        self.assertTrue(self.cc("Medford Happenings w/ John Petrella",
                                "Medford Happenings - Local Happenings Part 2", mt=mt,
                                a={"duration": 709}, b={"duration": 709}))
        # a 115s promo is not the 2488s episode
        self.assertFalse(self.cc("Medford Happenings - Tax Override Q&A",
                                 "Medford Happenings Promo 2024", mt=mt,
                                 a={"duration": 2488}, b={"duration": 115}))
        # short clips can coincide by chance, so the floor keeps them apart:
        # these two really are 32s and 33s, on the same day, cross-channel
        self.assertFalse(self.cc("Data Talk #5: Progress Worth Watching",
                                 "AJ Olapade Candidate Profile 2025 School Committee",
                                 mt="Campaign", a={"duration": 32}, b={"duration": 33}))

    def test_known_limit_a_series_name_outside_the_meeting_type(self):
        """Documented weakness, not a passing grade. "Data Talk" names a series
        but is not part of meeting_type "Campaign", so two instalments share it
        and would pair if they were ever cross-channel. They are not: all 17
        cross-channel Campaign pairs in the corpus are correctly kept apart.
        If a series like this ever IS mirrored, add its name to
        utils._PROGRAMME_WORDS."""
        self.assertTrue(self.cc("Data Talk #5: Progress Worth Watching",
                                "Data Talk #6: Finding Bright Spots", mt="Campaign"))

    def test_full_meetings_do_not_use_duration(self):
        # a partial recording of a council meeting measured 0.166 of its twin
        self.assertTrue(self.cc("Medford, MA City Council - Apr. 12, 2016",
                                "Medford, MA City Council   Apr  12, 2016",
                                a={"duration": 1000}, b={"duration": 6000}))


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
        self.assertEqual(ch["B"]["skip"], True)
        self.assertEqual(ch["B"]["duplicate_id"], "A")
        self.assertEqual(ch["B"]["duplicate_method"], "metadata")
        self.assertIn("duplicate of A", ch["B"]["skip_reason"])
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
        self.assertEqual(ch["A"]["skip"], False)                 # un-hidden
        self.assertEqual(ch["A"]["duplicate_id"], "B")
        self.assertEqual(ch["B"]["skip"], False)
        self.assertEqual(ch["B"]["backseat"], True)

    def test_once_keeper_is_transcribed_the_unofficial_copy_is_skipped(self):
        self.transcribed("A", "2017-09-27")
        self.transcribed("B", "2017-09-26")
        data = {"A": entry("Medford, MA City Council - Sep. 26, 2017", "Mass Traction-US-Medford-1 - Government", "2017-09-27"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26", backseat=True)}
        ch = self.run_dedup(data)
        self.assertEqual(ch["A"]["skip"], True)
        self.assertEqual(ch["A"]["duplicate_id"], "B")
        self.assertEqual(ch["B"]["skip"], False)
        self.assertEqual(ch["B"]["backseat"], False)

    def test_skip_records_why(self):
        """A bare skip:true is indistinguishable from an intentional dedup, a
        truncated download, or a human decision. Record the reason."""
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["B"]["duplicate_method"], "metadata")
        self.assertIn("same type and meeting date", ch["B"]["skip_reason"])

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

    def test_never_hides_a_meeting_behind_a_hidden_keeper(self):
        """The preferred copy is skipped by a person / the truncated-audio
        guard, which dedup may not lift. Pointing the other copy at it would
        leave NO visible copy. Happened live to the MCM Archive copies of
        "Community Development Board 07-14-25" and a 2021 cannabis session."""
        data = {"A": entry("Community Development Board 07-14-25", "MCM Archive", "2025-07-14",
                           mt="CC Community Development Board", skip=True),
                "B": entry("Community Development Board 07/14/25", "MCM Castus", "2025-07-14",
                           mt="CC Community Development Board")}
        ch = self.run_dedup(data)
        # the visible copy stays visible (it may be recorded as a no-op)
        self.assertFalse(ch.get("B", {}).get("skip", False))
        self.assertNotIn("A", ch)          # and the protected skip is untouched

    def test_a_third_copy_can_still_keep_when_the_best_is_hidden(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26",
                           skip=True),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26"),
                "C": entry("Medford City Council 09-26-17", "MCM Castus", "2017-09-26")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["B"]["skip"], False)     # archive beats castus
        self.assertEqual(ch["C"]["skip"], True)
        self.assertEqual(ch["C"]["duplicate_id"], "B")
        self.assertNotIn("A", ch)

    def test_stale_skip_from_a_retired_rule_is_lifted(self):
        """News left the dedup set, so this function stops grouping those
        entries -- and could therefore never un-skip a wrong hide it had
        already made. Five real News videos were invisible in two mutual
        A->B->A pairs until this ran."""
        data = {"A": entry("Medford HS security increases after stabbing", "WCVB Channel 5 Boston",
                           "2022-12-20", mt="News", skip=True, duplicate_id="B"),
                "B": entry("Mother of stabbed Medford High School student speaks out", "CBS Boston",
                           "2022-12-20", mt="News", skip=True, duplicate_id="A")}
        ch = self.run_dedup(data)
        self.assertEqual(ch["A"]["skip"], False)
        self.assertEqual(ch["B"]["skip"], False)

    def test_untyped_stale_skip_is_NOT_lifted(self):
        """None was excluded under every version of this function, so a dedup
        skip on an untyped entry was recorded while it still had a type. It is
        unverifiable, not reversed -- and often right ("(Unofficial)")."""
        data = {"A": entry("Medford, MA School Committe - May 1, 2017 (Unofficial)", "MCM Archive",
                           "2017-05-01", mt=None, skip=True, duplicate_id="B"),
                "B": entry("School Committee 05-01-17", "Medford Public Schools", "2017-05-01", mt=None)}
        self.assertNotIn("A", self.run_dedup(data))

    def test_apply_false_does_not_mutate(self):
        data = {"A": entry("City Council 09-26-17", "City of Medford, Massachusetts", "2017-09-26"),
                "B": entry("Medford City Council 09-26-17", "MCM Archive", "2017-09-26")}
        self.run_dedup(data)
        self.assertNotIn("skip", data["B"])


if __name__ == "__main__":
    unittest.main()


class MeetingDocuments(unittest.TestCase):
    """Agendas/minutes matched to the meeting they belong to.

    The failure that matters is attaching a document to the WRONG committee:
    a council meeting and a school committee meeting on the same evening each
    matching the other's agenda. Date alone cannot tell them apart.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.makedirs(os.path.join(self.tmp, "agendas"))
        os.makedirs(os.path.join(self.tmp, "minutes"))
        # meeting_types.json is read relative to cwd
        import shutil
        shutil.copy(os.path.join(self.cwd, "meeting_types.json"), self.tmp)
        os.chdir(self.tmp)
        utils._DOC_INDEX.clear()

    def tearDown(self):
        os.chdir(self.cwd)
        utils._DOC_INDEX.clear()

    def doc(self, kind, name):
        open(os.path.join(kind, name), "w").close()
        utils._DOC_INDEX.clear()

    def test_matches_on_date_and_type(self):
        self.doc("agendas", "2024.01.17 - City Council Agenda.pdf")
        e = {"title": "Medford City Council 01-17-24", "date": "2024-01-17",
             "meeting_type": "CC City Council"}
        self.assertEqual(len(utils.meeting_documents(e, "agendas")), 1)

    def test_does_not_attach_another_committees_agenda(self):
        """Same evening, different committee: no link rather than a wrong one."""
        self.doc("agendas", "2024.01.17 - Committee of the Whole Agenda.pdf")
        e = {"title": "Medford City Council 01-17-24", "date": "2024-01-17",
             "meeting_type": "CC City Council"}
        self.assertEqual(utils.meeting_documents(e, "agendas"), [])

    def test_untyped_meeting_gets_nothing(self):
        self.doc("agendas", "2024.01.17 - City Council Agenda.pdf")
        e = {"title": "something 01-17-24", "date": "2024-01-17", "meeting_type": None}
        self.assertEqual(utils.meeting_documents(e, "agendas"), [])

    def test_wrong_date_gets_nothing(self):
        self.doc("agendas", "2024.01.17 - City Council Agenda.pdf")
        e = {"title": "Medford City Council 01-24-24", "date": "2024-01-24",
             "meeting_type": "CC City Council"}
        self.assertEqual(utils.meeting_documents(e, "agendas"), [])

    def test_prefers_the_version_with_attachments(self):
        self.doc("agendas", "2024.01.17 - City Council Agenda No Attachments.pdf")
        self.doc("agendas", "2024.01.17 - City Council Agenda With Attachments.pdf")
        e = {"title": "Medford City Council 01-17-24", "date": "2024-01-17",
             "meeting_type": "CC City Council"}
        self.assertIn("With Attachments", utils.meeting_documents(e, "agendas")[0])

    def test_minutes_are_separate_from_agendas(self):
        self.doc("minutes", "2024.01.17 - City Council Report.pdf")
        e = {"title": "Medford City Council 01-17-24", "date": "2024-01-17",
             "meeting_type": "CC City Council"}
        self.assertEqual(utils.meeting_documents(e, "agendas"), [])
        self.assertEqual(len(utils.meeting_documents(e, "minutes")), 1)
