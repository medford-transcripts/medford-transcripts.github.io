import datetime, time, os
import ipdb
import json,glob

# openAI has conflicting requirements with googletrans :(
#from openai import OpenAI
#with open('openai_key.txt') as f: api_key = f.readline().strip()
#client = OpenAI(api_key=api_key)

def supercut(speaker):

    t0 = datetime.datetime(1900,1,1)    
    excerpts = []
    files = glob.glob("*/*.srt")
    for file in files:
        yt_id = '_'.join(file.split('_')[1:]).split('\\')[0]
        dir = os.path.dirname(file)
        srtfilename = os.path.join(dir,dir) + '.srt'
        if srtfilename != file: continue

        jsonfile = os.path.join(dir,'speaker_ids.json')
        if os.path.exists(jsonfile):
            with open(jsonfile, 'r') as fp:
                speaker_ids = json.load(fp)
        else: speaker_ids = {}

        # requested speaker not in this transcript; skip file
        if speaker not in speaker_ids.values(): continue

        # extract text from this transcript
        with open(srtfilename, 'r', encoding="utf-8") as f:

            # Read each line in the file
            for line in f:
                line.strip()

                if "-->" in line:
                    # timestamp
                    start_string = line.split()[0]
                    stop_string = line.split()[-1]

                    # convert timestamp to seconds elapsed
                    start_time = (datetime.datetime.strptime(start_string,'%H:%M:%S,%f')-t0).total_seconds()
                    stop_time = (datetime.datetime.strptime(stop_string,'%H:%M:%S,%f')-t0).total_seconds()

                elif "[" in line:
                    # text
                    this_speaker = line.split()[0].split("[")[-1].split("]")[0]
                    text = ":".join(line.split(":")[1:])

                    if speaker_ids[this_speaker] == speaker:
                        excerpts.append({
                            "yt_id" : yt_id,
                            "start": start_time,
                            "stop" : stop_time,
                            "text" : text,
                            })
                    
                else: continue

    messages = [ {"role": "system", "content": "You are an intelligent assistant."} ]
    text = "Extract 2-4 minutes of the most consequential quotes from the following excerpts: "

    office = "city council"
    values = ["engagement","passion","competence","critical thinking","creativity","intelligence","communication","compassion","inspirational","integrity","honesty","visionary","fiscal responsibility","respect"]
    priorities = ["education","infrastructure","economic development","jobs","equity","equality","climate change","economy","veterans","health","affordable housing","public safety"]
    text = "Based on their quotes below, on a scale from 1 to 10 " + \
        "(10 being best) rate the candidate's suitability for " + office + \
        " based on each of the following values: " + ",".join(values) + \
        ". Also rate them based on the following priorities: " + ",".join(priorities) + \
        ". 'not enough information' is a valid ranking. Explain each score in 1-2 sentences."

    text = ""
    alltime = 0.0
    htmlfilename = os.path.join("electeds",speaker + '.html')
    html = open(htmlfilename, 'w', encoding="utf-8")

    for excerpt in excerpts:
        html.write('    <a href="https://youtu.be/' + excerpt["yt_id"] + '&t=' + str(excerpt["start"]) + 's">')
        html.write("[" + speaker + "]</a>: " + excerpt["text"].strip() + "<br><br>\n\n")
        text = text + " " + excerpt["text"]
        alltime += (excerpt["stop"] - excerpt["start"])
    html.close()
    messages = [({"role": "user", "content": text})]
    print(str(alltime/3600) + " hours of speech")

    return text
    ipdb.set_trace()

    model = "gpt-3.5-turbo"
    #model = "gpt-4o-mini"
    #response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content.strip()

if __name__ == "__main__":

    ''' The goal for this code is to find the most consequential exerpts
    for a given person (using chatGPT?) across all transcripts, then extract 
    the corresponding clips (yt_dlp?) from the transcribed videos and splice 
    them together (ffmpeg?) into a 2-4 minute supercut. 

    This is a very early draft that does none of those things...
    '''
    councilors = ["Lungo-Koehn", # Mayor 2020-
    "Burke", # Mayor 2016-2020
    "McGlynn", # Mayor 1988-2016
    "Callahan","Lazzaro","Leming", # City Councilors 2024 (Caraviello, Knight, Morell out) 
    "Collins","Tseng", # City Councilors 2022 (Marks, Falco out)
    "Falco","Marks","Knight","Caraviello","Scarpelli","Bears","Morell", # City Councilors 2020
    "Branley","Intoppa","Olapade","Reinfeld", # School committee 2024 (Kreatz, McLaughlin, Mustone, Hays out)
    "Hays", # School Committee 2022 (Van der Kloot out)
    "Mustone","McLaughlin","Kreatz","Graham","Ruseau", "Van der Kloot", # School Committee 2020
    "Jessica"] # important guest speakers
    # No videos prior to 2020?

    for councilor in councilors:
        print(councilor)
        excerpts = supercut(councilor)
        #ipdb.set_trace()


