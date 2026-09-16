"""
Canonical URL construction for the published site.

Everything that writes an absolute medford-transcripts.github.io URL into a
page must go through site_url(). The bug this exists to prevent:

    html.write('...github.io/' + os.path.join(dir, name) + '...')

On Windows os.path.join yields a BACKSLASH, producing

    https://medford-transcripts.github.io/2025-01-03_MCM00001695\\...ar.html

which is not a valid path separator in a URL. Google resolves it to a single
flat segment that 404s, and a page whose canonical points at a 404 gets
dropped from the index. That silently de-indexed ~27,000 pages.

See plan.txt A1.
"""

import posixpath
from urllib.parse import quote

SITE_ROOT = "https://medford-transcripts.github.io/"


def site_path(path):
    """Normalize a repo-relative filesystem path to a URL path.

    Converts OS separators to '/', drops any leading './' or '/', and
    collapses redundant separators. Does not percent-encode.
    """
    rel = str(path).replace("\\", "/")
    rel = posixpath.normpath(rel)
    if rel == ".":
        return ""
    return rel.lstrip("/")


def site_url(path):
    """Absolute canonical URL for a repo-relative file path.

    Always emits forward slashes; never leaks an OS path separator into a URL.

    >>> site_url("2025-01-03_MCM00001695\\\\2025-01-03_MCM00001695.ar.html")
    'https://medford-transcripts.github.io/2025-01-03_MCM00001695/2025-01-03_MCM00001695.ar.html'
    >>> site_url("election/2025.html")
    'https://medford-transcripts.github.io/election/2025.html'
    """
    rel = site_path(path)
    # safe="/" keeps separators literal; spaces and other stray characters
    # in legacy filenames get encoded rather than breaking the URL.
    return SITE_ROOT + quote(rel, safe="/-_.~()[]@!$&'*+,;=")


def canonical_tag(path, indent="    "):
    """The full <link rel="canonical"> line, newline included."""
    return indent + '<link rel="canonical" href="' + site_url(path) + '" />\n'
