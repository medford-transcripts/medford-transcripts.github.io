"""
Regression tests for canonical URL construction.

Run: python -m pytest test_site_url.py -q
 or: python test_site_url.py
"""

import os
import site_url
from site_url import site_url as u, site_path, canonical_tag


def test_backslash_becomes_slash():
    """The A1 bug: os.path.join output must not leak into a URL."""
    got = u("2025-01-03_MCM00001695\\2025-01-03_MCM00001695.ar.html")
    assert "\\" not in got
    assert got == ("https://medford-transcripts.github.io/"
                   "2025-01-03_MCM00001695/2025-01-03_MCM00001695.ar.html")


def test_os_path_join_roundtrip():
    """Whatever separator this platform uses, the URL uses '/'."""
    p = os.path.join("2025-01-03_MCM00001695", "2025-01-03_MCM00001695.html")
    assert "\\" not in u(p)
    assert u(p).endswith("/2025-01-03_MCM00001695/2025-01-03_MCM00001695.html")


def test_forward_slash_unchanged():
    assert u("election/2025.html") == \
        "https://medford-transcripts.github.io/election/2025.html"


def test_no_double_slash_and_leading_dot():
    assert u("./election/2025.html") == \
        "https://medford-transcripts.github.io/election/2025.html"
    assert u("election//2025.html") == \
        "https://medford-transcripts.github.io/election/2025.html"
    assert u("/election/2025.html") == \
        "https://medford-transcripts.github.io/election/2025.html"


def test_root():
    assert u("") == "https://medford-transcripts.github.io/"


def test_yt_ids_with_leading_dash_and_underscore():
    """Real yt_ids contain '-' and '_'; they must survive unencoded."""
    for yt_id in ("-MlgNixuHJY", "h0C_BGnSd8o", "4up_cmlg7RM"):
        got = u(os.path.join("t", yt_id, yt_id + ".html"))
        assert yt_id in got, got
        assert "%" not in got, got


def test_spaces_are_encoded_not_raw():
    got = u("other_files/Some Report.pdf")
    assert " " not in got
    assert "%20" in got


def test_canonical_tag_shape():
    tag = canonical_tag(os.path.join("election", "2025.html"))
    assert tag.endswith(" />\n")
    assert 'rel="canonical"' in tag
    assert "\\" not in tag


def test_site_path_is_pure():
    assert site_path("a\\b\\c.html") == "a/b/c.html"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                failures += 1
                print("FAIL", name, e)
    raise SystemExit(1 if failures else 0)
