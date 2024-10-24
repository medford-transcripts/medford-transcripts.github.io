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

    speaker = ""
    start = 0.0
    stop = 86400.0
    text = ""
    t0 = datetime.datetime(1900,1,1)	

    if yt_id == None:
    	yt_id = os.path.basename(srtfilename)[0]

    # output custom html with links to corresponding parts of the youtube video
    html = open(os.path.join(dir,htmlfilename), 'w')
    html.write('<!DOCTYPE html>\n')
    html.write('<html lang="en">\n')
    html.write('  <head>\n')
    html.write('    <meta charset="UTF-8">\n')
    html.write('    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n')
    html.write('    <meta http-equiv="X-UA-Compatible" content="ie=edge">\n')
    html.write('   <title>Transcript for ' + yt_id + '</title>\n')
    html.write('  </head>\n')
    html.write('  <body>\n')

    speaker_stats = {}

    with open(os.path.join(dir,srtfilename), 'r') as file:

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

    html.write('  </body>\n')
    html.write('</html>\n')
    html.close()

    ignore_words = ["to","the","that","of","a","is","this","on","and","it","so","in","it's","just","are","for","has","had"]#,"i","you"]
    max_to_print = 3

    for speaker in speaker_stats.keys():
    	nprinted = 0
    	if speaker != '':
	    	print(speaker + ': ')
	    	print("  total time: " + str(round(speaker_stats[speaker]["total_time"]/60.0,2)) + ' minutes')
	    	print("  total words: " + str(speaker_stats[speaker]["total_words"]))


	    	if 0:
		    	print("  top " + str(max_to_print) + " words:")
		    	sorted_words = dict(sorted(speaker_stats[speaker]["words"].items(), key=lambda item: item[1],reverse=True))
		    	for word in sorted_words.keys():
		    		if word not in ignore_words:
		    			print("    " + word + ":" + str(sorted_words[word]))
		    			nprinted += 1
		    		if nprinted >= max_to_print: break

	    	# make a word cloud
	    	wordcloud = WordCloud(max_font_size=40).generate(speaker_stats[speaker]["all_words"])
	    	plt.figure()
	    	plt.imshow(wordcloud, interpolation="bilinear")
	    	plt.axis("off")
	    	plt.savefig(os.path.join(dir,speaker + '.wordcloud.png'))



#    ipdb.set_trace()

if __name__ == "__main__":

	speaker_ids = {
		"SPEAKER_00": "Barkson",
		"SPEAKER_01": "Tseng",
		"SPEAKER_02": "Costigan",
		"SPEAKER_03": "Collins",
		"SPEAKER_04": "Castagnetti",
		"SPEAKER_05": "Costigan",
		"SPEAKER_06": "Bears",
		"SPEAKER_07": "Scarpelli",
		"SPEAKER_08": "Costigan",
		"SPEAKER_09": "Leming",
		"SPEAKER_10": "Hurtubise",
		"SPEAKER_11": "Hurtubise",
	}

	#srt2html("council30.srt","council30_new.html",speaker_ids=speaker_ids, yt_id="kP4iRYobyr0", dir="council30")


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

	srt2html("council.0-60.srt","council.0-60_new.html",speaker_ids=speaker_ids, yt_id="kP4iRYobyr0", dir="council.0-60")