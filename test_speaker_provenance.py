"""Regression tests for speaker provenance and the guards in propagate().

WHY THESE EXIST: track_speakers.propagate() and match_embeddings() write
speaker_ids.json, the ground truth for who said what, and the owner's words
were "corruption happens and it propagates quickly and can destroy hand
verified ids". Every test below pins one of:

  * a cluster key ("<yt_id>_SPEAKER_NN") is load-bearing and is never
    collapsed or removed -- only followed, and only recorded
  * both writers leave a provenance record with the real cosine score and the
    exact reference speaker the value came from, and the prior value
  * propagate() refuses to overwrite an entry recorded as "manual"
  * propagate() is all-or-nothing: an exception mid-pass leaves NO file
    changed, and a cluster key pointing at a pruned speaker is skipped rather
    than raising KeyError halfway through the corpus
  * chained propagation inside one pass behaves exactly as the old
    write-as-you-go code did (a later file sees an earlier file's new value)
  * backfill never asserts "manual" for anything it cannot prove
  * revert undoes exactly one recorded hop and never clobbers a value it did
    not record

Every test runs in a throwaway directory. Nothing here touches a real
speaker_ids.json.

Run:  python -m pytest test_speaker_provenance.py -q
"""

import json
import os
import pickle
import shutil
import tempfile
import types
import unittest

import speaker_provenance as sp
import track_speakers as ts


def _write_json(path, data):
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fp:
        json.dump(data, fp, indent=4)


def _read_json(path):
    with open(path, "r") as fp:
        return json.load(fp)


class _InTempDir(unittest.TestCase):
    """chdir into a fresh temp dir: propagate()/match_embeddings() glob
    relative to cwd, which is the only way to point them at fixtures."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prov_test_")
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ids(self, d):
        return _read_json(os.path.join(d, "speaker_ids.json"))

    def prov(self, d):
        return sp.load_provenance(d)


# ---------------------------------------------------------------------------

class Shapes(unittest.TestCase):

    def test_three_shapes_are_disjoint(self):
        self.assertTrue(sp.is_cluster_key("a17_UOV__Vs_SPEAKER_20"))
        self.assertTrue(sp.is_cluster_key("MCM00001607_SPEAKER_07"))
        self.assertTrue(sp.is_raw_speaker("SPEAKER_06"))
        self.assertTrue(sp.is_named("Zac Bears"))
        for v in ("a17_UOV__Vs_SPEAKER_20", "SPEAKER_06", "Zac Bears"):
            self.assertEqual(
                [sp.is_cluster_key(v), sp.is_raw_speaker(v), sp.is_named(v)].count(True), 1, v)

    def test_cluster_key_check_matches_propagate(self):
        # propagate() uses len > 12 and value[11] == "_"; a 12-char string
        # with "_" at 11 is NOT a cluster key there, so not here either
        self.assertFalse(sp.is_cluster_key("abcdefghijk_"))
        self.assertTrue(sp.is_cluster_key("abcdefghijk_x"))
        self.assertFalse(sp.is_cluster_key(None))

    def test_make_entry_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            sp.make_entry("x", "guess")


class Sidecar(_InTempDir):

    def test_record_round_trip_and_atomic(self):
        d = os.path.join(self.tmp, "2020-01-01_AAAAAAAAAAA")
        os.makedirs(d)
        sp.record(d, "SPEAKER_01", "Zac Bears", "embedding_match",
                  score=0.83, from_="BBBBBBBBBBB_SPEAKER_04", previous="SPEAKER_01")
        got = sp.load_provenance(d)["SPEAKER_01"]
        self.assertEqual(got["value"], "Zac Bears")
        self.assertEqual(got["source"], "embedding_match")
        self.assertAlmostEqual(got["score"], 0.83)
        self.assertEqual(got["from"], "BBBBBBBBBBB_SPEAKER_04")
        self.assertEqual(got["previous"], "SPEAKER_01")
        self.assertTrue(got["at"].endswith("Z"))
        # no temp file left behind
        self.assertEqual(sorted(os.listdir(d)), ["speaker_provenance.json"])

    def test_corrupt_sidecar_reads_as_empty(self):
        d = os.path.join(self.tmp, "2020-01-01_AAAAAAAAAAA")
        os.makedirs(d)
        with open(sp.provenance_path(d), "w") as fp:
            fp.write("{not json")
        self.assertEqual(sp.load_provenance(d), {})

    def test_record_in_memory_does_not_touch_disk(self):
        d = os.path.join(self.tmp, "2020-01-01_AAAAAAAAAAA")
        os.makedirs(d)
        prov = {}
        sp.record(d, "SPEAKER_01", "Zac Bears", "propagated", provenance=prov)
        self.assertIn("SPEAKER_01", prov)
        self.assertFalse(os.path.exists(sp.provenance_path(d)))


class Backfill(_InTempDir):

    def setUp(self):
        super().setUp()
        _write_json("2020-01-01_AAAAAAAAAAA/speaker_ids.json",
                    {"SPEAKER_00": "Zac Bears", "SPEAKER_01": "SPEAKER_01",
                     "SPEAKER_02": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json("2020-01-02_BBBBBBBBBBB/speaker_ids.json",
                    {"SPEAKER_03": "George Scarpelli", "SPEAKER_04": "SPEAKER_04"})
        _write_json("manual_corrections.json", {"ids": {"AAAAAAAAAAA": {"dir": "2020-01-01_AAAAAAAAAAA"}}})

    def test_default_is_unknown_for_everything(self):
        summary = sp.backfill()
        self.assertEqual(summary["files_scanned"], 2)
        self.assertEqual(summary["entries_manual"], 0)
        self.assertEqual(summary["entries_unknown"], 5)
        for d in ("2020-01-01_AAAAAAAAAAA", "2020-01-02_BBBBBBBBBBB"):
            for key, entry in self.prov(d).items():
                self.assertEqual(entry["source"], "unknown")
                self.assertEqual(entry["value"], self.ids(d)[key])
        # never modified the ids files themselves
        self.assertEqual(self.ids("2020-01-01_AAAAAAAAAAA")["SPEAKER_02"], "BBBBBBBBBBB_SPEAKER_03")

    def test_manual_only_for_names_in_listed_videos_and_only_when_asked(self):
        summary = sp.backfill(mark_manual_from_corrections=True)
        self.assertEqual(summary["entries_manual"], 1)
        a = self.prov("2020-01-01_AAAAAAAAAAA")
        self.assertEqual(a["SPEAKER_00"]["source"], "manual")     # a name, listed video
        self.assertEqual(a["SPEAKER_01"]["source"], "unknown")    # raw, never manual
        self.assertEqual(a["SPEAKER_02"]["source"], "unknown")    # cluster key, never manual
        b = self.prov("2020-01-02_BBBBBBBBBBB")
        self.assertEqual(b["SPEAKER_03"]["source"], "unknown")    # a name, but unlisted video

    def test_backfill_is_idempotent_and_never_clobbers(self):
        sp.backfill()
        sp.record("2020-01-01_AAAAAAAAAAA", "SPEAKER_01", "SPEAKER_01", "manual")
        summary = sp.backfill(mark_manual_from_corrections=True)
        self.assertEqual(summary["files_touched"], 0)
        self.assertEqual(self.prov("2020-01-01_AAAAAAAAAAA")["SPEAKER_01"]["source"], "manual")
        self.assertEqual(self.prov("2020-01-01_AAAAAAAAAAA")["SPEAKER_00"]["source"], "unknown")


class DriftAndMarkManual(_InTempDir):

    def test_drift_lists_unrecorded_and_changed(self):
        d = "2020-01-01_AAAAAAAAAAA"
        _write_json(d + "/speaker_ids.json", {"SPEAKER_00": "Zac Bears", "SPEAKER_01": "SPEAKER_01"})
        sp.record(d, "SPEAKER_00", "Someone Else", "embedding_match")
        rows = sp.drift(d)
        self.assertEqual({r["speaker_key"] for r in rows}, {"SPEAKER_00", "SPEAKER_01"})

    def test_mark_manual_reads_value_from_disk(self):
        d = "2020-01-01_AAAAAAAAAAA"
        _write_json(d + "/speaker_ids.json", {"SPEAKER_00": "Zac Bears"})
        sp.record(d, "SPEAKER_00", "Someone Else", "embedding_match")
        out = sp.mark_manual(d, ["SPEAKER_00", "SPEAKER_99"])
        self.assertEqual(out, {"marked": ["SPEAKER_00"], "missing": ["SPEAKER_99"]})
        entry = self.prov(d)["SPEAKER_00"]
        self.assertEqual(entry["source"], "manual")
        self.assertEqual(entry["value"], "Zac Bears")
        self.assertEqual(entry["previous"], "Someone Else")
        self.assertNotIn("SPEAKER_99", self.prov(d))


# ---------------------------------------------------------------------------
# propagate()

class Propagate(_InTempDir):

    A, B, C, D = ("2020-01-01_AAAAAAAAAAA", "2020-01-02_BBBBBBBBBBB",
                  "2020-01-03_CCCCCCCCCCC", "2020-01-04_DDDDDDDDDDD")

    def test_follows_cluster_key_and_records_provenance(self):
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03",
                                                   "SPEAKER_05": "SPEAKER_05"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Zac Bears"})
        sp.record(self.B, "SPEAKER_03", "Zac Bears", "embedding_match", score=0.91,
                  from_="CCCCCCCCCCC_SPEAKER_00", previous="SPEAKER_03")

        result = ts.propagate()

        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "Zac Bears")
        self.assertEqual(self.ids(self.A)["SPEAKER_05"], "SPEAKER_05")
        entry = self.prov(self.A)["SPEAKER_04"]
        self.assertEqual(entry["source"], "propagated")
        self.assertEqual(entry["from"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertEqual(entry["previous"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertAlmostEqual(entry["score"], 0.91)   # inherited from the source entry
        self.assertNotIn("SPEAKER_05", self.prov(self.A))
        self.assertEqual(result["updated_files"], [os.path.join(self.A, "speaker_ids.json")])
        # B was the source, not a target: untouched
        self.assertEqual(self.ids(self.B), {"SPEAKER_03": "Zac Bears"})

    def test_unresolved_cluster_key_is_kept_verbatim(self):
        # B's SPEAKER_03 is still unnamed -> A keeps the cluster key, and gets
        # no provenance record for it (nothing happened)
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "SPEAKER_03"})
        ts.propagate()
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertFalse(os.path.exists(sp.provenance_path(self.A)))

    def test_guard_a_manual_entry_is_never_overwritten(self):
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Wrong Person"})
        sp.mark_manual(self.A, ["SPEAKER_04"])
        before = self.prov(self.A)["SPEAKER_04"]

        result = ts.propagate()

        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertEqual(self.prov(self.A)["SPEAKER_04"], before)
        self.assertEqual(result["skipped_manual"], [(os.path.join(self.A, "speaker_ids.json"), "SPEAKER_04")])
        self.assertEqual(result["updated_files"], [])

    def test_guard_a_does_not_protect_non_manual_sources(self):
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Zac Bears"})
        for source in ("unknown", "embedding_match", "propagated"):
            sp.record(self.A, "SPEAKER_04", "BBBBBBBBBBB_SPEAKER_03", source)
            _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
            ts.propagate()
            self.assertEqual(self.ids(self.A)["SPEAKER_04"], "Zac Bears", source)

    def test_guard_b_pruned_reference_is_skipped_not_raised(self):
        # A -> B's SPEAKER_03, which no longer exists in B. Old code: KeyError.
        # C -> B's SPEAKER_09 is fine and must still be propagated.
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_09": "Zac Bears"})
        _write_json(self.C + "/speaker_ids.json", {"SPEAKER_00": "BBBBBBBBBBB_SPEAKER_09"})

        result = ts.propagate()

        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")   # kept, not removed
        self.assertEqual(self.ids(self.C)["SPEAKER_00"], "Zac Bears")
        self.assertEqual(len(result["skipped_missing"]), 1)
        self.assertEqual(result["skipped_missing"][0][1:], ("SPEAKER_04", "BBBBBBBBBBB_SPEAKER_03"))

    def test_dangling_reference_to_missing_dir_is_left_alone(self):
        # 16 of these exist in the real corpus (dir deleted); the old code
        # tolerated them via len(mapped_file) == 1 and so must we
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "ZZZZZZZZZZZ_SPEAKER_03"})
        ts.propagate()
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "ZZZZZZZZZZZ_SPEAKER_03")

    def test_all_or_nothing_on_exception(self):
        # A (globbed first) is propagatable; Z (globbed last) is corrupt JSON.
        # Old code would have written A before dying on Z.
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Zac Bears"})
        os.makedirs("2020-01-09_ZZZZZZZZZZZ")
        with open("2020-01-09_ZZZZZZZZZZZ/speaker_ids.json", "w") as fp:
            fp.write("{corrupt")

        with self.assertRaises(ValueError):
            ts.propagate()

        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertFalse(os.path.exists(sp.provenance_path(self.A)))

    def test_chained_propagation_matches_old_single_pass_behaviour(self):
        # Old code wrote each file as it went, so D (after B in glob order)
        # saw B's NEW value in the same pass, while A (before B) saw the OLD
        # one. Collect-then-commit must reproduce that exactly, or a single
        # propagate() call would silently do less work than it used to.
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_00": "BBBBBBBBBBB_SPEAKER_03"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "CCCCCCCCCCC_SPEAKER_01"})
        _write_json(self.C + "/speaker_ids.json", {"SPEAKER_01": "Zac Bears"})
        _write_json(self.D + "/speaker_ids.json", {"SPEAKER_07": "BBBBBBBBBBB_SPEAKER_03"})

        ts.propagate()

        self.assertEqual(self.ids(self.A)["SPEAKER_00"], "CCCCCCCCCCC_SPEAKER_01")
        self.assertEqual(self.ids(self.B)["SPEAKER_03"], "Zac Bears")
        self.assertEqual(self.ids(self.D)["SPEAKER_07"], "Zac Bears")
        self.assertEqual(self.prov(self.D)["SPEAKER_07"]["from"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertEqual(self.prov(self.D)["SPEAKER_07"]["previous"], "BBBBBBBBBBB_SPEAKER_03")

        ts.propagate()   # second pass finishes A, as before
        self.assertEqual(self.ids(self.A)["SPEAKER_00"], "Zac Bears")
        self.assertEqual(self.prov(self.A)["SPEAKER_00"]["from"], "CCCCCCCCCCC_SPEAKER_01")
        self.assertEqual(self.prov(self.A)["SPEAKER_00"]["previous"], "CCCCCCCCCCC_SPEAKER_01")

    def test_preserves_key_order_and_format(self):
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_00": "SPEAKER_00",
                                                   "SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03",
                                                   "SPEAKER_02": "Someone"})
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Zac Bears"})
        ts.propagate()
        with open(self.A + "/speaker_ids.json") as fp:
            text = fp.read()
        self.assertEqual(list(_read_json(self.A + "/speaker_ids.json").keys()),
                         ["SPEAKER_00", "SPEAKER_04", "SPEAKER_02"])
        self.assertIn('    "SPEAKER_04": "Zac Bears"', text)   # indent=4 like every other writer


# ---------------------------------------------------------------------------
# match_embeddings()

def _embeddings(speakers, vectors):
    return types.SimpleNamespace(speaker=list(speakers), embeddings=[list(v) for v in vectors])


class MatchEmbeddings(_InTempDir):

    Q, R = "2020-01-01_QQQQQQQQQQQ", "2020-01-02_RRRRRRRRRRR"

    def setUp(self):
        super().setUp()
        _write_json("video_data.json", {"QQQQQQQQQQQ": {"upload_date": "2020-01-01"},
                                        "RRRRRRRRRRR": {"upload_date": "2020-01-02"}})
        os.makedirs(self.Q)
        os.makedirs(self.R)
        with open(self.R + "/embeddings.pkl", "wb") as fp:
            pickle.dump(_embeddings(["SPEAKER_05", "SPEAKER_07", "SPEAKER_08"],
                                    [[1.0, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]), fp)
        _write_json(self.R + "/speaker_ids.json", {"SPEAKER_05": "Zac Bears",
                                                   "SPEAKER_07": "SPEAKER_07",
                                                   "SPEAKER_08": "SPEAKER_08"})
        with open(self.Q + "/embeddings.pkl", "wb") as fp:
            pickle.dump(_embeddings(["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
                                    [[1.0, 0.0, 0.0], [0.0, 1.0, 0.1], [0.5, 0.5, 0.5]]), fp)
        _write_json(self.Q + "/speaker_ids.json", {"SPEAKER_00": "SPEAKER_00",
                                                   "SPEAKER_01": "SPEAKER_01",
                                                   "SPEAKER_02": "SPEAKER_02"})

    def test_records_named_match_with_score_and_source_key(self):
        ts.match_embeddings("QQQQQQQQQQQ")
        ids = self.ids(self.Q)
        self.assertEqual(ids["SPEAKER_00"], "Zac Bears")
        entry = self.prov(self.Q)["SPEAKER_00"]
        self.assertEqual(entry["source"], "embedding_match")
        self.assertEqual(entry["from"], "RRRRRRRRRRR_SPEAKER_05")
        self.assertEqual(entry["previous"], "SPEAKER_00")
        self.assertGreater(entry["score"], 0.99)
        self.assertLessEqual(entry["score"], 1.0)

    def test_records_unnamed_match_as_cluster_key(self):
        ts.match_embeddings("QQQQQQQQQQQ")
        ids = self.ids(self.Q)
        self.assertEqual(ids["SPEAKER_01"], "RRRRRRRRRRR_SPEAKER_07")   # cluster key, not collapsed
        entry = self.prov(self.Q)["SPEAKER_01"]
        self.assertEqual(entry["source"], "embedding_match")
        self.assertEqual(entry["from"], "RRRRRRRRRRR_SPEAKER_07")
        self.assertEqual(entry["previous"], "SPEAKER_01")
        self.assertGreater(entry["score"], 0.99)

    def test_no_match_leaves_no_record(self):
        ts.match_embeddings("QQQQQQQQQQQ")
        self.assertEqual(self.ids(self.Q)["SPEAKER_02"], "SPEAKER_02")   # cos ~0.58 to everything
        self.assertNotIn("SPEAKER_02", self.prov(self.Q))
        # the reference video is never written by matching the query
        self.assertFalse(os.path.exists(sp.provenance_path(self.R)))

    def test_already_identified_is_not_rematched(self):
        _write_json(self.Q + "/speaker_ids.json", {"SPEAKER_00": "Hand Named",
                                                   "SPEAKER_01": "SPEAKER_01",
                                                   "SPEAKER_02": "SPEAKER_02"})
        ts.match_embeddings("QQQQQQQQQQQ")
        self.assertEqual(self.ids(self.Q)["SPEAKER_00"], "Hand Named")
        self.assertNotIn("SPEAKER_00", self.prov(self.Q))


# ---------------------------------------------------------------------------
# report / revert

class ReportRevert(_InTempDir):

    A, B, C = ("2020-01-01_AAAAAAAAAAA", "2020-01-02_BBBBBBBBBBB", "2020-01-03_CCCCCCCCCCC")

    def setUp(self):
        super().setUp()
        # B's SPEAKER_03 was (wrongly) named; A and C were propagated from it
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Wrong Person"})
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "BBBBBBBBBBB_SPEAKER_03",
                                                   "SPEAKER_05": "SPEAKER_05"})
        _write_json(self.C + "/speaker_ids.json", {"SPEAKER_00": "BBBBBBBBBBB_SPEAKER_03"})
        ts.propagate()

    def test_report_lists_derived_entries(self):
        rep = sp.report("BBBBBBBBBBB_SPEAKER_03")
        derived = {(m["meeting_dir"], m["speaker_key"]) for m in rep["derived"]}
        self.assertEqual(derived, {(self.A, "SPEAKER_04"), (self.C, "SPEAKER_00")})
        for m in rep["derived"]:
            self.assertEqual(m["current_value"], "Wrong Person")
            self.assertEqual(m["previous"], "BBBBBBBBBBB_SPEAKER_03")
            self.assertEqual(m["source"], "propagated")
        self.assertEqual(rep["members"], [])   # all followed; none still hold the key
        self.assertEqual(sp.report("nobody_SPEAKER_00")["derived"], [])

    def test_dry_run_writes_nothing(self):
        rows = sp.revert("BBBBBBBBBBB_SPEAKER_03")
        self.assertEqual({r["status"] for r in rows}, {"would revert"})
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "Wrong Person")
        self.assertEqual(self.ids(self.C)["SPEAKER_00"], "Wrong Person")

    def test_apply_restores_previous_and_records_the_hop(self):
        rows = sp.revert("BBBBBBBBBBB_SPEAKER_03", apply=True)
        self.assertEqual({r["status"] for r in rows}, {"reverted"})
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")
        self.assertEqual(self.ids(self.A)["SPEAKER_05"], "SPEAKER_05")
        self.assertEqual(self.ids(self.C)["SPEAKER_00"], "BBBBBBBBBBB_SPEAKER_03")
        entry = self.prov(self.A)["SPEAKER_04"]
        self.assertEqual(entry["source"], "unknown")
        self.assertEqual(entry["previous"], "Wrong Person")
        self.assertIsNone(entry["from"])
        # the root cause is NOT touched by revert
        self.assertEqual(self.ids(self.B)["SPEAKER_03"], "Wrong Person")
        # once the root is fixed, propagate() can deliver the right name again
        _write_json(self.B + "/speaker_ids.json", {"SPEAKER_03": "Right Person"})
        ts.propagate()
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "Right Person")

    def test_lock_marks_manual_and_blocks_repropagation(self):
        sp.revert("BBBBBBBBBBB_SPEAKER_03", apply=True, lock=True)
        self.assertEqual(self.prov(self.A)["SPEAKER_04"]["source"], "manual")
        ts.propagate()
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "BBBBBBBBBBB_SPEAKER_03")

    def test_skips_entry_edited_since_it_was_recorded(self):
        _write_json(self.A + "/speaker_ids.json", {"SPEAKER_04": "Hand Fixed", "SPEAKER_05": "SPEAKER_05"})
        rows = {r["meeting_dir"]: r["status"] for r in sp.revert("BBBBBBBBBBB_SPEAKER_03", apply=True)}
        self.assertTrue(rows[self.A].startswith("skipped: on-disk value"))
        self.assertEqual(rows[self.C], "reverted")
        self.assertEqual(self.ids(self.A)["SPEAKER_04"], "Hand Fixed")

    def test_skips_entry_without_previous(self):
        sp.record(self.A, "SPEAKER_05", "Anyone", "unknown", from_="BBBBBBBBBBB_SPEAKER_03")
        rows = {r["speaker_key"]: r["status"] for r in sp.revert("BBBBBBBBBBB_SPEAKER_03")}
        self.assertEqual(rows["SPEAKER_05"], "skipped: no previous value recorded")


if __name__ == "__main__":
    unittest.main()
