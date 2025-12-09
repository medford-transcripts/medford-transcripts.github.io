from pathlib import Path
import json
import os
import time

import utils

def make():

    # update meeting types and identify duplicates
    utils.add_all_meeting_types()
    utils.identify_duplicate_videos()

    with open("meeting_types.json", "r", encoding="utf-8") as fp:
        meeting_type = json.load(fp)
    meeting_type = dict(sorted(meeting_type.items(), key=lambda kv: kv[0]))


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

    all_committees_table = open("committees/index.html", 'w', encoding="utf-8")
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

        html = open(htmlname, 'w', encoding="utf-8")
        html.write('<table border=1>\n')
        #html.write("  <tr><td><center>Date</center></td><td><center>Duration</center></td><td><center>Title (click for transcript)</center></td><td><center>Agenda</center></td><td><center>Minutes</center></td><td><center>Channel</center></td><td colspan=2><center>Raw files</center></td></tr>\n")
        html.write("  <tr><td><center>Date</center></td><td><center>Duration</center></td><td><center>Title (click for transcript)</center></td><td><center>Channel</center></td></tr>\n")

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

                nmeetings += 1
                html.write('  <tr>\n')
                html.write('    <td>' + video_data[video]["date"] + '</td>\n')
                html.write('    <td><a href="' + url + '">[' + duration_string + ']</a></td>\n')
                html.write('    <td><a href="../' + transcript_url + '">' + video_data[video]["title"] + '</a></td>\n')
                html.write('    <td>' + video_data[video]["channel"] + '</td>\n')
                html.write('  </tr>\n')

        if nmeetings > 0:
            all_committees_table.write('<tr><td><a href="' + htmlbasename + '">' + committee_name + '</a></td></tr>\n')

        html.write('</table>\n')
        html.close()

    all_committees_table.write('</table>')
    all_committees_table.close()


if __name__ == "__main__":

    make()