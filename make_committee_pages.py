from pathlib import Path
import io
import json
import os
import time

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
    all_committees_table.write('<table border=1>\n')
    all_committees_table.write('  <tr><td><center>Committee</center></td></td>\n')

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

        if nmeetings > 0:
            all_committees_table.write('<tr><td><a href="' + htmlbasename + '">' + committee_name + '</a></td></tr>\n')

        html = open(htmlname, 'w', encoding="utf-8")
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
        html.close()

    all_committees_table.write('</table>')
    utils.write_atomic("committees/index.html", all_committees_table.getvalue())


if __name__ == "__main__":

    make()