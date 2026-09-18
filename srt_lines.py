"""
SRT parsing, and the block-span that corresponds to one RENDERED line.

WHY THIS EXISTS as a shared module rather than a copy in each tool: an SRT
BLOCK and a rendered LINE are not the same thing, and getting that wrong
silently corrupts transcripts.

srt2html merges consecutive blocks by the same speaker into one
`<p class="line">`, so the paragraph a reader sees -- and therefore the text a
contributor edits in the correction form -- routinely spans several blocks:

    5764.554  [SPEAKER_04] Thank you, really appreciate this.
    5767.397  [SPEAKER_04] Seems really well thought out.          }  ONE
    5769.899  [SPEAKER_04] Within those four majors, ...           }  rendered
    5781.290  [SPEAKER_04] How do we ensure that there's access?   }  line
    5783.512  [SPEAKER_04] Completely open honors.
    5784.993  [SPEAKER_04] Great, thank you.

Reading "the original" as the FIRST block gives 34 characters where the
contributor saw 343, so a correction compared against it looks like a huge
rewrite, and applying it writes the whole paragraph into the first block while
leaving the other five in place -- duplicating the text. Both bugs were live
until this module existed.

This is also the first piece of the Phase 5D consolidation: four files parse
SRT timestamps by hand today.
"""

import re

TS_RE = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
SPEAKER_RE = re.compile(r"^\[([^\]]*)\]:\s*(.*)$", re.S)


def to_seconds(ts):
    """'00:01:23,456' -> 83.456. None if it does not look like a timestamp."""
    m = TS_RE.search(ts or "")
    if not m:
        return None
    h, mm, ss, ms = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int(ms.ljust(3, "0")) / 1000.0


def to_timestamp(sec):
    """83.456 -> '00:01:23,456'. Round-trips exactly with to_seconds."""
    if sec is None or sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_srt(text):
    """[{start, end, speaker, text}], speaker None when the block has no label."""
    blocks = []
    for raw in re.split(r"\r?\n\r?\n", text or ""):
        lines = raw.strip().splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        lo, hi = lines[1].split("-->")
        body = "\n".join(lines[2:]).strip()
        m = SPEAKER_RE.match(body)
        blocks.append({
            "start": to_seconds(lo),
            "end": to_seconds(hi),
            "speaker": m.group(1) if m else None,
            "text": (m.group(2) if m else body).strip(),
        })
    return blocks


def render_srt(blocks):
    """Back to SRT text, renumbered so the file stays valid after edits."""
    out = []
    for n, b in enumerate(blocks, start=1):
        body = ("[%s]: %s" % (b["speaker"], b["text"])) if b["speaker"] else b["text"]
        out.append("%d\n%s --> %s\n%s\n"
                   % (n, to_timestamp(b["start"]), to_timestamp(b["end"]), body))
    return "\n".join(out)


def find_block(blocks, t, tol=0.05):
    """Index of the block starting at t, or None. Matches on the start time
    because that is what srt2html writes into data-t and the form sends back."""
    best, best_d = None, None
    for i, b in enumerate(blocks):
        if b["start"] is None:
            continue
        d = abs(b["start"] - t)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best if (best_d is not None and best_d <= tol) else None


def line_span(blocks, i, names=None):
    """(lo, hi) block slice forming the rendered line that block i belongs to.

    Mirrors srt2html's grouping, and the subtlety is the whole point:
    srt2html merges paragraphs by the RESOLVED SPEAKER NAME, not the raw
    diarization label (srt2html.py:483-491 rewrites this_speaker through
    speaker_ids BEFORE comparing it to the previous speaker). So when two
    different labels -- SPEAKER_04 and SPEAKER_11 -- both map to "Zac Bears"
    and land next to each other, the reader sees ONE paragraph.

    Grouping by the raw label instead produced a SHORTER span than the
    contributor actually saw and edited, which either rejects a good
    correction as stale or writes a full paragraph into part of its blocks and
    duplicates the rest. Measured before this fix: 157 of 600 transcripts
    (26.2%) contain at least one such boundary.

    Pass `names` (the speaker_ids mapping) to group the way the page does.
    Without it this falls back to raw-label grouping, which is correct only
    when no two labels share a name.

    The slice STARTS at i rather than walking backwards, because the caller
    located i from a data-t attribute, which srt2html only emits at a line's
    first block.
    """
    if i is None or not (0 <= i < len(blocks)):
        return None

    def resolved(k):
        spk = blocks[k]["speaker"]
        if names is None or spk is None:
            return spk
        return names.get(spk, spk)

    want = resolved(i)
    j = i + 1
    while j < len(blocks) and resolved(j) == want:
        j += 1
    return (i, j)


def line_text(blocks, lo, hi):
    """The text a reader sees for that rendered line."""
    return " ".join(b["text"] for b in blocks[lo:hi] if b["text"]).strip()


def normalise(s):
    """Whitespace-insensitive comparison key.

    The correction form round-trips text through a textarea and the player
    joins block texts with a space, either of which changes spacing without
    changing content. Comparing raw strings produces false 'the transcript
    changed' reports.
    """
    return re.sub(r"\s+", " ", (s or "")).strip()
