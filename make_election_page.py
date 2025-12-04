import utils
import heatmap
import json
import supercut
import ipdb
import os
import datetime

def make_election_page(year=None, remake_heatmap=False, remake_html=False, skip_words=False):

    now = datetime.datetime.utcnow()

    with open("councilors.json", 'r') as fp:
        unsorted_directory = json.load(fp)

    #directory = dict(sorted(unsorted_directory.items(), key=lambda item: item[0].split()[-1]))
    directory = dict(
        sorted(
            unsorted_directory.items(),
            key=lambda item: (
                item[0].split()[1].lower() if len(item[0].split()) > 1 else item[0].split()[0].lower()
            )
        )
    )

    video_data = utils.get_video_data()

    with open("election/" + str(year) + ".html", "w") as f:

        minyear = 2000
        years = [str(y) for y in range(int(year), int(minyear) - 1, -1)]

        # begin the table
        f.write('<!DOCTYPE html>\n')
        f.write('<html lang="en">\n')
        f.write('  <head>\n')
        f.write('    <meta charset="UTF-8">\n')
        f.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
        f.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
        f.write('    <meta name="description" content="Excerpts from transcribed videos of the ' + str(year) + ' Medford MA candidates for Mayor, City Council, and School Committee.">\n')
        f.write('    <title>Medford MA ' + str(year) + ' Election</title>\n')
        f.write('    <link rel="canonical" href="https://medford-transcripts.github.io/" />\n')
        f.write('  </head>\n')
        f.write('\n')
        f.write('  <body>\n')
        f.write('    <h1>' + str(year) + ' Medford MA candidates</h1>\n') 
        f.write('    <h2>Excerpts of transcribed videos from the ' + str(year) + ' Medford MA candidates for Mayor, City Council, and School Committee.</h2>\n')


        positions = {
            "city_council_candidate":"City Council Candidates",
            "city_council_prelim_candidate":"City Council Prelim Candidates",
            "school_committee_candidate":"School Committee Candidates",
            "school_committee_prelim_candidate":"School Committee Prelim Candidates",
            "mayor_candidate": "Mayoral Candidates",
            "mayor_prelim_candidate": "Mayoral Prelim Candidates"
        }

        for position in positions.keys():

            # skip tables without any candidates
            no_candidates = True
            for official in directory.keys():
                if year in directory[official].keys():
                    if position in directory[official][year]["position"]:
                        no_candidates = False
            if no_candidates: continue

            mapname = year + "_" + position + '_heatmap.html'
            fullmapname = "election/" + mapname

            if os.path.exists(fullmapname): 
                mtime = os.path.getmtime(fullmapname)
                modified_date = datetime.datetime.fromtimestamp(mtime)

            if not os.path.exists(fullmapname) or (remake_heatmap and modified_date < now):
                heatmap.electeds_heatmap(position, year=year)

            f.write('\n')
            f.write('    <table border=1>\n')
            f.write('      <tr><td colspan=11><center>' + positions[position] + ' (<a href="' + mapname + '">map)</a></center></td></tr>\n')
            f.write('      <tr>\n')
            f.write('        <td title="A link to all excerpt for this speaker, with sentence-level, timestamped links to the source video"><center>Excerpts</center></td>\n')
            f.write('        <td title="Number of words spoken among all transcribed videos of this year">' + years[1] + ' Words</td>\n')
            f.write('        <td title="Number of words spoken among all transcribed videos of this year">' + year + ' Words</td>\n')
            f.write('        <td title="Campaign Links"><center>Campaign Links</center></td>\n')
            f.write('        <td><a href="https://ourrevolutionmedford.com/">ORM endorsed?</a></td>\n')
            f.write('        <td><a href="https://www.youtube.com/@MedfordHappenings">Medford Happenings</a></td>\n')
            f.write('        <td><a href="https://podcasts.apple.com/us/podcast/medford-bytes/id1591707053">Medford Bytes</a></td>\n')
            f.write('        <td><a href="https://www.gottaknowmedford.com">GKM</a></td>\n')
            f.write('        <td><a href="https://patch.com/massachusetts/medford"><center>Patch</center></a></td>\n')
            f.write('        <td><a href="https://www.medfordtv.org/"><center>MCM</center></a></td>\n')
            f.write('      </tr>\n')

            for official in directory.keys():

                htmlname = "electeds/" + official + ".html"

                if os.path.exists(htmlname): 
                    mtime = os.path.getmtime(htmlname)
                    modified_date = datetime.datetime.fromtimestamp(mtime)

                if not os.path.exists(htmlname) or (remake_html and modified_date < now):
                    supercut.supercut(official,mkhtml=True)

                if year in directory[official].keys():
                    if position in directory[official][year]["position"]:

                        if not skip_words:
                            print((official,years[0]))
                            excerpts = supercut.supercut(official,mkhtml=False,year=years[0])
                            excerptsm1 = supercut.supercut(official,mkhtml=False,year=years[1])

                            words_year = len(excerpts.split())
                            words_lastyear = len(excerptsm1.split())
                        else:
                            words_year = 0
                            words_lastyear = 0

                        elected_position = position.removesuffix("_prelim_candidate").removesuffix("_candidate")
                        is_incumbent = elected_position in directory[official][year]["position"]

                        official_name = official
                        if is_incumbent: official_name += "*"

                        f.write('      <tr>\n')
                        f.write('        <td><a href="../electeds/' + official + '.html">' + official_name + '</a></td>\n')
                        f.write('        <td><center>' + format(words_lastyear,",") + '</center></td>\n')
                        f.write('        <td><center>' + format(words_year,",") + '</center></td>\n')

                        # add campaign website
                        #if 'website' in directory[official].keys():
                        #    if directory[official]['website'] != "":
                        #        f.write('        <td><center><a href="' + directory[official]['website'] + '">website</a></center></td>\n')
                        #    else:
                        #        f.write('        <td></td>\n')
                        #else:
                        #    f.write('        <td></td>\n')

                        f.write('        <td><center>\n')
                        socials = ["website","email","facebook","instagram","twitter","linkedin","reddit","whatsapp","youtube","tiktok","pinterest","discord","github","bluesky","donate"]
                        for social in socials:
                            if social in directory[official].keys():
                                if directory[official][social] != "":
                                    f.write('          <a href="' + directory[official][social] + '"><img height="16" src="' + social + '.svg"></a>\n')
                        f.write('        </center></td>\n')


                        # add ORM endorsement
                        if 'orm_endorsed' in directory[official][year].keys():
                            f.write('        <td><center>Yes</center></td>\n')
                        else:
                            f.write('        <td></td>\n')

                        # find the most recent Medford Happenings Interview
                        found=False
                        for test_year in years:
                            if test_year in directory[official].keys():
                                if 'happenings' in directory[official][test_year].keys():
                                    if test_year == year:
                                        link_text = "Transcript"
                                    else:
                                        link_text = test_year + ' Tran'
                                    yt_id = directory[official][test_year]["happenings"]
                                    url = video_data[yt_id]["upload_date"] + "_" + yt_id + '/index.html'
                                    f.write('        <td><center><a href="../' + url + '">' + link_text + '</a></center></td>\n')
                                    found=True
                                    break
                        if not found:
                            f.write('        <td></td>\n')

                        # find the most recent Medford Bytes Interview
                        found=False
                        for test_year in years:
                            if test_year in directory[official].keys():
                                if 'bytes' in directory[official][test_year].keys():
                                    if test_year == year:
                                        link_text = "Transcript"
                                    else:
                                        link_text = test_year + ' Tran'
                                    yt_id = directory[official][test_year]["bytes"]
                                    url = video_data[yt_id]["upload_date"] + "_" + yt_id + '/index.html'
                                    f.write('        <td><center><a href="../' + url + '">' + link_text + '</a></center></td>\n')
                                    found=True
                                    break
                        if not found:
                            f.write('        <td></td>\n')

                        # find the most recent Gotta Know Medford profile
                        found=False
                        for test_year in years:
                            if test_year in directory[official].keys():
                                if 'gkm' in directory[official][test_year].keys():
                                    if test_year == year:
                                        link_text = "Link"
                                    else:
                                        link_text = test_year + ' Link'
                                    url = directory[official][test_year]["gkm"]
                                    f.write('        <td><center><a href="' + url + '">' + link_text + '</a></center></td>\n')
                                    found=True
                                    break
                        if not found:
                            f.write('        <td></td>\n')                        

                        # find the most recent Patch profile
                        found=False
                        for test_year in years:
                            if test_year in directory[official].keys():
                                if 'patch' in directory[official][test_year].keys():
                                    if test_year == year:
                                        link_text = "Link"
                                    else:
                                        link_text = test_year + ' Link'
                                    url = directory[official][test_year]["patch"]
                                    f.write('        <td><center><a href="' + url + '">' + link_text + '</a></center></td>\n')
                                    found=True
                                    break
                        if not found:
                            f.write('        <td></td>\n')   

                        # find the most recent MCM Interview
                        found=False
                        for test_year in years:
                            if test_year in directory[official].keys():
                                if 'mcm' in directory[official][test_year].keys():
                                    if test_year == year:
                                        link_text = "Transcript"
                                    else:
                                        link_text = test_year + ' Tran'
                                    yt_id = directory[official][test_year]["mcm"]
                                    url = video_data[yt_id]["upload_date"] + "_" + yt_id + '/index.html'
                                    f.write('        <td><center><a href="../' + url + '">' + link_text + '</a></center></td>\n')
                                    found=True
                                    break
                        if not found:
                            f.write('        <td></td>\n')

            f.write('      </tr>\n')
            f.write('    </table>\n\n')
            f.write('<p>\n\n')

        f.write("*=Incumbent<p>\n\n")
        f.write("These links go to a dedicated page for each candidate containing a compilation of all their excerpts extracted from the <a href=" + '"../index.html"' + ">transcribed videos</a> and include timestamped links to the original source video. Similar pages exist for candidates and a handful of important public employees <a href=" + '"../councilors.json"' + ">here</a>. Word counts for each candidate are also included, intended as a very rough proxy for who's active. A challenger having few appearances/words in these excerpts doesn't necessarily say much about them. Many successful candidates in the past did not appear in any videos prior to their election.<p>\n\n")
        f.write("A great use of these pages is to use your browser's search function to find where candidates mention topics that are important to you, then you can watch the corresponding video in its full context.<p>\n\n")
        f.write("One may also wish to upload these pages to <a href=" + '"http://chat.openai.com/"' + "'>ChatGPT</a> then ask for help synthesizing the results more globally. However, be warned it heavily weights the beginning of the file (the most recent excerpts), and will happily fill in missing information with convincing -- but totally ficticious -- misinformation. It's significantly better when asked to compare two things (" + '"rank the candidates on XX"' + "), but in general, treat the results from ChatGPT as a you would something written by a mid-level high school student.<p>\n\n")
        f.write("The videos are transcriptions of (nearly) all videos at the <a href=" + '"../channels_to_transcribe.txt"' + "'> YouTube channels listed here</a>, which are predominantly city council and school committee meetings, but also include campaign channels, news sources, and other channels dedicated to local politics, including partisans on both sides (I can only include YouTube channels, but if I'm missing any, please let me know).\n\n")

        f.write('  </body>\n')
        f.write('</html>\n')

def make_all_election_pages(remake_heatmap=False, remake_html=False, skip_words=False):

    with open("election/index.html", "w") as f:

        # begin the table
        f.write('<!DOCTYPE html>\n')
        f.write('<html lang="en">\n')
        f.write('  <head>\n')
        f.write('    <meta charset="UTF-8">\n')
        f.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
        f.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
        f.write('    <meta name="description" content="Election info pages for Medford, MA Mayor, City Council, and School Committee.">\n')
        f.write('    <title>Medford Election</title>\n')
        f.write('    <link rel="canonical" href="https://medford-transcripts.github.io/" />\n')
        f.write('  </head>\n\n')
        f.write('  <body>\n')
        f.write('    <h1>Medford MA elections</h1>\n') 
        f.write('    <h2>Election info pages for Medford, MA Mayor, City Council, and School Committee</h2><br>\n')
        f.write('    <a href="school_committee_prelim_candidate_heatmap.html">School Committee Candidate Map (2005-Present)</a><br>\n')
        f.write('    <a href="city_council_prelim_candidate_heatmap.html">City Council Candidate Map (2005-Present)</a><br>\n')
        f.write('    <a href="mayor_prelim_candidate_heatmap.html">Mayor Candidate Map (2005-Present)</a><br><br>\n\n')
        f.write('    <a href="../wardmap.html">Ward Map (for City Council)</a><br>\n')
        f.write('    <a href="../districtmap.html">District Map (for School Committee)</a><br>\n')
        f.write('    <a href="../polling_places.html">Polling Place Map</a><br><br>\n\n')
        f.write('    <table border=1>\n')

        years = list(range(2025, 2004, -2))
        for year in years:
            make_election_page(year=str(year), remake_heatmap=remake_heatmap, remake_html=remake_html, skip_words=skip_words)
            f.write('      <tr><td><a href="' + str(year) + '.html">' + str(year) + '</a></tr>\n')

        f.write('    </table>\n')
        f.write('  </body>\n')
        f.write('</html>\n')

if __name__ == "__main__": 

    # this is much faster (seconds, not hours) for testing
    #make_all_election_pages(remake_heatmap=False, remake_html=False, skip_words=True)

    make_all_election_pages(remake_heatmap=True, remake_html=True)
    #make_election_page(year="2025")