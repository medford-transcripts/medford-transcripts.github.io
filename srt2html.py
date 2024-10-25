import datetime, os
import ipdb
from wordcloud import WordCloud
import matplotlib.pyplot as plt


def finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop):
	# new speaker; wrap up and start new
	if text != "":
		html.write('    <a href="https://youtu.be/' + yt_id + '&t=' + str(start) + 's">')
		html.write("[" + speaker + "]</a>: " + text + "<br><br>\n\n")

	# let's do some stats by speaker
	if not speaker in speaker_stats.keys(): speaker_stats[speaker] = {"words": {}, "all_words" : ""}
	
	# time
	added_time = stop-start
	if "total_time" in speaker_stats[speaker].keys(): speaker_stats[speaker]["total_time"] += added_time
	else: speaker_stats[speaker]["total_time"] = added_time

	# all words for word cloud
	speaker_stats[speaker]["all_words"] += text

	added_words = 0
	for word in text.split():
		this_word = word.lower().split(".")[0].split(",")[0]
		added_words += 1
		if this_word in speaker_stats[speaker]["words"].keys(): speaker_stats[speaker]["words"][this_word] += 1
		else: speaker_stats[speaker]["words"][this_word] = 1

	if "total_words" in speaker_stats[speaker].keys(): speaker_stats[speaker]["total_words"] += added_words
	else: speaker_stats[speaker]["total_words"] = added_words

def srt2html(srtfilename, htmlfilename, speaker_ids={}, yt_id=None, dir=None):

    councilors = ["Lungo-Koehn", # Mayor
    "Bears","Collins","Callahan","Lazzaro","Leming","Scarpelli","Tseng", # City Councilors
    "Branley","Graham","Intoppa","Olapade","Reinfeld","Ruseau", # School committee
    "Jessica"] # important guest speakers

    speaker = ""
    start = 0.0
    stop = 86400.0
    text = ""
    t0 = datetime.datetime(1900,1,1)	

    if yt_id == None:
    	yt_id = os.path.basename(srtfilename)[0]

    # output custom html with links to corresponding parts of the youtube video
    html = open(os.path.join(dir,htmlfilename), 'w', encoding="utf-8")
    html.write('<!DOCTYPE html>\n')
    html.write('<html lang="en">\n')
    html.write('  <head>\n')
    html.write('    <meta charset="UTF-8">\n')
    html.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    html.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
    html.write('   <title>Transcript for ' + yt_id + '</title>\n')
    html.write('  </head>\n')
    html.write('  <body>\n')
    html.write('  <table>\n')

    speaker_stats = {}

    with open(os.path.join(dir,srtfilename), 'r', encoding="utf-8") as file:

        # Read each line in the file
	    for line in file:
	        line.strip()

	        if "-->" in line:
	        	# timestamp
	        	start_string = line.split()[0]
	        	stop_string = line.split()[-1]

	        	# convert timestamp to seconds elapsed
	        	this_start = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
	        	this_stop = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

	        elif "[" in line:
	        	# text
	        	this_speaker = line.split()[0].split("[")[-1].split("]")[0]
	        	this_text = line.split(":")[-1]

	        	# replace automated speaker tag with speaker ID
	        	if this_speaker in speaker_ids.keys():
	        		this_speaker = speaker_ids[this_speaker]

	        	if this_speaker == speaker:
	        		# same speaker; append to previous text
	        		text += this_text
	        	else:
	        		finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop)

	        		# update to new values
	        		start = this_start
	        		text = this_text
	        		speaker = this_speaker

	        	stop = this_stop

	        else: continue

    finish_speaker(html, speaker_stats, text, speaker, yt_id, start, stop)

    for speaker in speaker_stats.keys():
    	nprinted = 0
    	if speaker != '':
	    	print(speaker + ': ')
	    	print("  total time: " + str(round(speaker_stats[speaker]["total_time"]/60.0,2)) + ' minutes')
	    	print("  total words: " + str(speaker_stats[speaker]["total_words"]))

	    	# make a word cloud
	    	if speaker in councilors:
		    	wordcloud = WordCloud(max_font_size=40).generate(speaker_stats[speaker]["all_words"])
		    	wordcloud.to_file(os.path.join(dir,speaker + '.wordcloud.png'))


    ncols = 4
    nrows = 4
    idx = 0

	# find the subset of councilors present
    present_councilors = []
    for speaker_id in speaker_stats.keys():
    	if speaker_id in councilors: present_councilors.append(speaker_id)

    # make a table with stats
    for i in range(nrows):
    	html.write('    <tr>\n')
    	for j in range(ncols):
		    html.write('      <td>\n')
		    idx = i*ncols+j
		    if idx < len(present_councilors):
		    	if present_councilors[idx] in speaker_stats.keys():
				    imagename = present_councilors[idx] + '.wordcloud.png'
				    html.write('        <center>' + present_councilors[idx] + "</center><br>\n")
				    html.write('        total time: ' + str(round(speaker_stats[present_councilors[idx]]["total_time"]/60.0,2)) + ' minutes<br>\n')
				    html.write('        total words: ' + str(speaker_stats[present_councilors[idx]]["total_words"]) + '<br>\n')
				    html.write('        <a href="' + imagename + '"><img src="' + imagename + '" height=150></img></a><br>\n')
		    html.write('      </td>\n')
    	html.write('    </tr>\n')
    html.write('  </table>\n')

    html.write('  </body>\n')
    html.write('</html>\n')
    html.close()


#    ipdb.set_trace()

if __name__ == "__main__":

	speaker_ids = {
		"SPEAKER_00": "Olapade",
		"SPEAKER_01": "Bears",
		"SPEAKER_02": "Collins",
		"SPEAKER_03": "Music",
		"SPEAKER_04": "SPEAKER_04",
		"SPEAKER_05": "Leming",
		"SPEAKER_06": "Reinfeld",
		"SPEAKER_07": "Jessica",
		"SPEAKER_08": "Lazzaro",
		"SPEAKER_09": "Graham",
		"SPEAKER_10": "Lungo-Koehn",
		"SPEAKER_11": "Callahan",
		"SPEAKER_12": "Ruseau",
	}
	dir="2024-10-23_eYLl0XsNfvs_invest_in_medford_town_hall"
	srtfile="2024-10-23_eYLl0XsNfvs_invest_in_medford_town_hall.srt"
	htmlfile="2024-10-23_eYLl0XsNfvs_invest_in_medford_town_hall.html"
	srt2html(srtfile,htmlfile, yt_id="eYLl0XsNfvs", speaker_ids=speaker_ids, dir=dir)
	ipdb.set_trace()

	speaker_ids = {
		"SPEAKER_00": "Sharpener",
		"SPEAKER_01": "Lazzaro",
		"SPEAKER_02": "Costigan",
		"SPEAKER_03": "Scarpelli",
		"SPEAKER_04": "Leming",
		"SPEAKER_05": "Hurtubise",
		"SPEAKER_06": "Hurtubise",
		"SPEAKER_07": "Bears",
		"SPEAKER_08": "Bears",
		"SPEAKER_09": "Tardelli",
		"SPEAKER_10": "Barkson",
		"SPEAKER_11": "Collins",
		"SPEAKER_12": "Castagnetti",
		"SPEAKER_13": "Tseng",
		"SPEAKER_14": "Callahan",
		"SPEAKER_15": "McGonigal",
		"SPEAKER_16": "Costigan",
	}

	dir = "2024-10-15_kP4iRYobyr0_city_council_committee_of_the_whole_10-15-24"
	srtfile = dir + '.srt'
	htmlfile = dir + '.html'
	srt2html(srtfile,htmlfile,speaker_ids=speaker_ids, yt_id="kP4iRYobyr0", dir=dir)