from pathlib import Path
import io
import json
import os
import time

import re
from html import escape
from site_url import site_url, SITE_ROOT

import utils

def make():

    # update meeting types and identify duplicates
    utils.add_all_meeting_types()
    utils.identify_duplicate_videos()

    # via utils so this is indifferent to the per-committee-settings shape
    # (see utils.meeting_type_config) and so "sources", which is a list of
    # roster URLs rather than a committee, stops being given a page.
    meeting_type = dict(sorted(utils.meeting_type_config().items(),
                               key=lambda kv: kv[0]))


    video_data = utils.get_video_data()

    # sort by date:
    sorted_items = sorted(
        video_data.items(),
        key=lambda kv: (
            kv[1].get("date")
            or kv[1].get("upload_date")
            or ""     # final fallback so None doesn't break comparisons
        ),reverse=True
    )
    video_data = dict(sorted_items)

    # Buffered; committed by write_atomic once the loop below completes.
    all_committees_table = io.StringIO()
    # The committees hub is a real document for the same reason the
    # per-committee pages are: it is in the sitemap and it is what every
    # committee page's "All committees" link points at.
    _hub_url = site_url('committees/index.html')
    _hub_desc = ('Every Medford Massachusetts public body with a transcribed '
                 'meeting, linking to its transcripts.')
    _hub_ld = {'@context': 'https://schema.org', '@type': 'CollectionPage',
               'name': 'Transcripts by committee', 'url': _hub_url,
               'description': _hub_desc, 'inLanguage': 'en'}
    all_committees_table.write('<!DOCTYPE html>' + chr(10) + '<html lang="en">' + chr(10))
    all_committees_table.write('  <head>' + chr(10) + '    <meta charset="UTF-8">' + chr(10))
    all_committees_table.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">' + chr(10))
    all_committees_table.write('    <title>Transcripts by committee - Medford Transcripts</title>' + chr(10))
    all_committees_table.write('    <meta name="description" content="' + escape(_hub_desc, quote=True) + '">' + chr(10))
    all_committees_table.write('    <link rel="canonical" href="' + _hub_url + '" />' + chr(10))
    all_committees_table.write('    <script type="application/ld+json">' + json.dumps(_hub_ld, ensure_ascii=False) + '</script>' + chr(10))
    all_committees_table.write('  </head>' + chr(10) + '  <body>' + chr(10))
    all_committees_table.write('    <h1>Transcripts by committee</h1>' + chr(10))
    all_committees_table.write('    <p><a href="../index.html">All transcripts</a></p>' + chr(10))
    all_committees_table.write(
        '    <p>Active bodies first. Everything ever transcribed is still '
        'listed below them.</p>' + chr(10))
    # ROWS ARE GROUPED, NOT JUST LISTED. 86 bodies in one alphabetical table
    # puts the Zoning Board next to a programme that last aired in 2019, so the
    # thing a reader wants most is the hardest to find. Collected here and
    # emitted in sections below, once each body's last meeting date is known.
    index_rows = []

    #import ipdb
    #ipdb.set_trace()
    all_committees = list(meeting_type.keys())
    all_committees.append(None)
    for committee in all_committees:

        if committee is None:
            committee_name = "Other"
        else:
            committee_name = committee

        htmlbasename = committee_name.replace(" ","_") + '.html'
        htmlname = 'committees/' + htmlbasename

        # ROWS ARE BUFFERED because the header depends on them: the Agenda and
        # Minutes columns are written only if this committee actually has one.
        # 492 agendas and 62 minutes spread over 63 committees means most
        # bodies have neither, and a column of empty cells on every other page
        # reads as "we lost the document" rather than "there isn't one".
        # Each column is decided SEPARATELY -- minutes are far rarer than
        # agendas, so a shared test would put an empty Minutes column on every
        # page that has agendas.
        rows = []
        has_agenda = has_minutes = False

        nmeetings = 0
        for video in video_data.keys():

            if "skip" in video_data[video].keys():
                if video_data[video]["skip"]: continue

            if "meeting_type" not in video_data[video].keys():
                if committee is not None:
                    continue

            transcript_url = video_data[video]["upload_date"] + "_" + video + '/' + video_data[video]["upload_date"] + "_" + video + ".html"

            if not os.path.exists(transcript_url): 
                continue


            if video_data[video]["meeting_type"] == committee:
                duration = video_data[video]["duration"]
                duration_string = time.strftime('%H:%M:%S', time.gmtime(duration))

                if "url" in video_data[video].keys():
                    url = video_data[video]["url"]
                else:
                    url = "https://youtu.be/" + video

                # The SAME matcher the front page uses (srt2html.make_index):
                # it requires date AND meeting_type to agree, so a document is
                # never stapled to a different committee that met the same
                # evening. Links are "../" relative because these pages live
                # in committees/.
                agenda_cell = minutes_cell = '<td></td>'
                agendas = utils.meeting_documents(video_data[video], "agendas")
                if agendas:
                    agenda_cell = ('<td><a href="../' + utils.web_path(agendas[0])
                                   + '">Agenda</a></td>')
                    has_agenda = True
                minutes = utils.meeting_documents(video_data[video], "minutes")
                if minutes:
                    minutes_cell = ('<td><a href="../' + utils.web_path(minutes[0])
                                    + '">Minutes</a></td>')
                    has_minutes = True

                nmeetings += 1
                rows.append((
                    '  <tr>\n'
                    '    <td>' + video_data[video]["date"] + '</td>\n'
                    '    <td><a href="' + url + '">[' + duration_string + ']</a></td>\n'
                    '    <td><a href="../' + transcript_url + '">' + video_data[video]["title"] + '</a></td>\n',
                    agenda_cell, minutes_cell,
                    '    <td>' + video_data[video]["channel"] + '</td>\n'
                    '  </tr>\n'))


        # A REAL DOCUMENT, not a bare <table>. These pages were fragments: no
        # doctype, no lang, no charset, no <title>. All 74 are in the sitemap,
        # and since ace582fc89 every transcript links to one and every
        # breadcrumb names one, so they are now the hub of the internal link
        # graph -- and a titleless fragment is a weak index candidate, which
        # would undercut the breadcrumb pointing at it.
        page_url = site_url(htmlname)
        first = rows[-1][0] if rows else ""
        last = rows[0][0] if rows else ""
        span = ""
        m_first = re.search(r"20\d\d-\d\d-\d\d", first)
        m_last = re.search(r"20\d\d-\d\d-\d\d", last)
        if m_first and m_last:
            span = "%s to %s" % (m_first.group(0), m_last.group(0))
        desc = ("%d transcribed %s meetings%s, Medford Massachusetts."
                % (nmeetings, committee_name, ", " + span if span else ""))

        if nmeetings > 0:
            _cfg = (utils.meeting_type_config().get(committee_name) or {}) \
                   if committee is not None else {}
            index_rows.append({
                "name": committee_name,
                "href": htmlbasename,
                "n": nmeetings,
                "last": m_last.group(0) if m_last else "",
                # "Other" is the no-type bucket, not a body; it sorts last
                "kind": _cfg.get("kind", "committee") if committee is not None
                        else "other",
            })

        crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                  "itemListElement": [
                      {"@type": "ListItem", "position": 1,
                       "name": "All transcripts", "item": SITE_ROOT},
                      {"@type": "ListItem", "position": 2,
                       "name": committee_name, "item": page_url}]}
        collection = {"@context": "https://schema.org", "@type": "CollectionPage",
                      "name": committee_name, "url": page_url,
                      "description": desc, "inLanguage": "en"}
        official = utils.official_body_url(committee_name)
        org = {"@type": "GovernmentOrganization", "name": committee_name}
        if official:
            org["sameAs"] = official
        collection["about"] = org

        html = open(htmlname, 'w', encoding="utf-8")
        html.write('<!DOCTYPE html>\n<html lang="en">\n  <head>\n')
        html.write('    <meta charset="UTF-8">\n')
        html.write('    <meta name="viewport" content="width=device-width, '
                   'initial-scale=1.0">\n')
        html.write('    <title>' + escape(committee_name, quote=True)
                   + ' - Medford Transcripts</title>\n')
        html.write('    <meta name="description" content="'
                   + escape(desc, quote=True) + '">\n')
        html.write('    <link rel="canonical" href="' + page_url + '" />\n')
        for obj in (crumbs, collection):
            html.write('    <script type="application/ld+json">'
                       + json.dumps(obj, ensure_ascii=False) + '</script>\n')
        html.write('  </head>\n  <body>\n')
        html.write('    <h1>' + escape(committee_name) + '</h1>\n')
        html.write('    <p>' + escape(desc) + '</p>\n')
        if official:
            # rel=nofollow matches how every other outbound source link on this
            # site is marked; the point is to send a READER to the membership,
            # contact and meeting schedule we do not republish.
            html.write('    <p>Official city page: <a href="'
                       + escape(official, quote=True) + '" rel="nofollow">'
                       + escape(committee_name) + ' on medfordma.org</a> '
                       '(membership, contact and meeting schedule)</p>\n')
        html.write('    <p><a href="../index.html">All transcripts</a> &middot; '
                   '<a href="index.html">All committees</a></p>\n')
        html.write('<table border=1>\n')
        header = ["<th scope='col'>Date</th>",
                  "<th scope='col'>Duration</th>",
                  "<th scope='col'>Title (click for transcript)</th>"]
        if has_agenda:  header.append("<th scope='col'>Agenda</th>")
        if has_minutes: header.append("<th scope='col'>Minutes</th>")
        header.append("<th scope='col'>Channel</th>")
        html.write("  <tr>" + "".join(header) + "</tr>\n")
        for lead, agenda_cell, minutes_cell, tail in rows:
            html.write(lead)
            if has_agenda:  html.write('    ' + agenda_cell + '\n')
            if has_minutes: html.write('    ' + minutes_cell + '\n')
            html.write(tail)
        html.write('</table>\n')
        html.write(utils.site_footer('../'))
        html.write('  </body>' + chr(10) + '</html>' + chr(10))
        html.close()

    # ACTIVE MEANS A MEETING IN THE LAST YEAR, computed from the transcripts
    # rather than flagged by hand, so it stays true with nobody maintaining it:
    # a body that resumes meeting moves back up on the next build, and one that
    # stops drifts down a year later. time is already imported; datetime is not.
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 365 * 86400))
    SECTIONS = (
        ("Active bodies", "met in the last 12 months",
         lambda r: r["kind"] == "committee" and r["last"] >= cutoff),
        ("Past bodies", "no meeting in the last 12 months",
         lambda r: r["kind"] == "committee" and r["last"] < cutoff),
        ("Programs and broadcasts", "not public bodies",
         lambda r: r["kind"] in ("program", "service")),
        ("Uncategorized", "not yet assigned to a body",
         lambda r: r["kind"] == "other"),
    )
    for heading, note, pick in SECTIONS:
        group = [r for r in index_rows if pick(r)]
        if not group:
            continue
        group.sort(key=lambda r: (-r["n"], r["name"]))
        all_committees_table.write(
            '    <h2>' + escape(heading) + ' <small>(' + escape(note)
            + ')</small></h2>' + chr(10))
        all_committees_table.write('<table border=1>' + chr(10))
        all_committees_table.write(
            '  <tr><td><center>Body</center></td>'
            '<td><center>Meetings</center></td>'
            '<td><center>Most recent</center></td></tr>' + chr(10))
        for r in group:
            all_committees_table.write(
                '  <tr><td><a href="' + r["href"] + '">' + escape(r["name"])
                + '</a></td><td>' + str(r["n"]) + '</td><td>'
                + escape(r["last"] or "") + '</td></tr>' + chr(10))
        all_committees_table.write('</table>' + chr(10))
    all_committees_table.write(utils.site_footer('../'))
    all_committees_table.write(chr(10) + '  </body>' + chr(10) + '</html>' + chr(10))
    utils.write_atomic("committees/index.html", all_committees_table.getvalue())


if __name__ == "__main__":

    make()