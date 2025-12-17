import requests
import os
import ipdb
import json
import dateutil.parser as dparser
import re

# local imports
import utils

def map(url_base="https://medfordma.api.civicclerk.com", jsonmap="agenda_map.json"):

    # this link will display fileId=54 in the browser:
    # https://mozilla.github.io/pdf.js/web/viewer.html?file=https://medfordma.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=54,plainText=false)


    if not os.path.exists(jsonmap):
        agenda_map = {}
    else:
        with open(jsonmap, 'r') as fp:
            agenda_map = json.load(fp)

    date = dparser.parse(title,fuzzy=True)


    # if the file doesn't end in one of these, it's assumed to be a pdf
    expected_exts = ('.jpg','.pdf','.docx','.xlsx','.pptx','.doc','.mp3','.mp4','.webm')

    # rather than looping arbitrarily over these, I should parse the upper level URL and follow the links
    # which would be faster and more general
    # but I did that (scrape_smart) and it misses a bunch of URLs, so maybe not
    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed

    # hardcoding this 500 is going to be problematic in the future
    for i in range(700):

        api_url = url_base + "/v1/Meetings/" + str(i+1)
        # first working example: https://medfordma.api.civicclerk.com/v1/Meetings/25

        # other possible entry points:
        #https://medfordma.api.civicclerk.com/v1
        #https://medfordma.api.civicclerk.com/v1/Events
        #https://medfordma.api.civicclerk.com/v1/EventCategories

        response = requests.get(api_url, headers=headers)
        data = response.json()

        for item in data["items"]:
            for child in item["childItems"]:

                #if "agendaObjectItemNumber" in child.keys():
                #    if child["agendaObjectItemNumber"] not in agenda_map.keys():
                #        agenda_map[child["agendaObjectItemNumber"]] = 


                # these are other files
                if "attachmentsList" in child.keys():
                    for attachment in child["attachmentsList"]:
                        pdfname = os.path.join("other_files",attachment["mediaFileName"].strip())
                        pdfname = pdfname.replace("/","").replace("?","")
                        url = attachment["pdfVersionFullPath"]
                        try:
                            
                            save_file(url, pdfname)
                        except:
                            print("failed to download " + pdfname)

                # these are the resolutions (mostly?)
                if "reportsList" in child.keys():
                    for report in child["reportsList"]:
                        pdfname = os.path.join("resolutions",report["agendaObjItemReportName"].strip() + '.pdf')
                        pdfname = pdfname.replace("/","").replace("?","")
                        url = report["pdfMediaFullPath"]
                        try:
                            save_file(url, pdfname)
                        except:
                            print("failed to download " + pdfname)

        api_url = "https://medfordma.api.civicclerk.com/v1/Events/" + str(i+1)
        response = requests.get(api_url, headers=headers)
        try:
            data = response.json()
        except:
            continue

        for publishedFile in data["publishedFiles"]:

            if publishedFile["type"] == "Agenda":
                dir = "agendas"
            elif publishedFile["type"] == "Agenda Packet":
                dir = "agendas"
            elif publishedFile["type"] == "Minutes":
                dir = "minutes"
            else:
                dir = "other_files"

            pdfname = os.path.join(dir,publishedFile["name"].strip())
            if not pdfname.endswith(expected_exts): pdfname = pdfname + '.pdf'
            pdfname = pdfname.replace("/","").replace("?","")

            url = publishedFile["streamUrl"]

            try:
                save_file(url, pdfname)
            except:
                print("failed to download " + pdfname)

def save_file(url, filename):

    if not os.path.exists(filename):
        print("Fetching " + filename)
        #ipdb.set_trace()
        response = requests.get(url)
        with open(filename, 'wb') as f:
            f.write(response.content)
    else:
        pass
        #print(filename + ' already exists')

def scrape(url_base="https://medfordma.api.civicclerk.com"):

    # if the file doesn't end in one of these, it's assumed to be a pdf
    expected_exts = ('.jpg','.pdf','.docx','.xlsx','.pptx','.doc','.mp3','.mp4','.webm')

    # rather than looping arbitrarily over these, I should parse the upper level URL and follow the links
    # which would be faster and more general
    # but I did that (scrape_smart) and it misses a bunch of URLs, so maybe not
    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed

    # hardcoding this 500 is going to be problematic in the future
    for i in range(700):

        api_url = url_base + "/v1/Meetings/" + str(i+1)

        # other possible entry points:
        #https://medfordma.api.civicclerk.com/v1
        #https://medfordma.api.civicclerk.com/v1/Events
        #https://medfordma.api.civicclerk.com/v1/EventCategories

        response = requests.get(api_url, headers=headers)
        data = response.json()

        for item in data["items"]:
            for child in item["childItems"]:

                # these are other files
                if "attachmentsList" in child.keys():
                    for attachment in child["attachmentsList"]:
                        pdfname = os.path.join("other_files",attachment["mediaFileName"].strip())
                        pdfname = pdfname.replace("/","").replace("?","")
                        url = attachment["pdfVersionFullPath"]
                        try:
                            save_file(url, pdfname)
                        except:
                            print("failed to download " + pdfname)

                # these are the resolutions (mostly?)
                if "reportsList" in child.keys():
                    for report in child["reportsList"]:
                        pdfname = os.path.join("resolutions",report["agendaObjItemReportName"].strip() + '.pdf')
                        pdfname = pdfname.replace("/","").replace("?","")
                        url = report["pdfMediaFullPath"]
                        try:
                            save_file(url, pdfname)
                        except:
                            print("failed to download " + pdfname)

        api_url = "https://medfordma.api.civicclerk.com/v1/Events/" + str(i+1)
        response = requests.get(api_url, headers=headers)
        try:
            data = response.json()
        except:
            continue

        for publishedFile in data["publishedFiles"]:

            if publishedFile["type"] == "Agenda":
                dir = "agendas"
            elif publishedFile["type"] == "Agenda Packet":
                dir = "agendas"
            elif publishedFile["type"] == "Minutes":
                dir = "minutes"
            else:
                dir = "other_files"

            pdfname = os.path.join(dir,publishedFile["name"].strip())
            if not pdfname.endswith(expected_exts): pdfname = pdfname + '.pdf'
            pdfname = pdfname.replace("/","").replace("?","")

            url = publishedFile["streamUrl"]

            try:
                save_file(url, pdfname)
            except:
                print("failed to download " + pdfname)

# this seems like the smart/intended way to do this, 
# but there are many URLs that don't seem to be linked this way
# so we'll do it the dumb way for now
def scrape_smart():
    base_url = "https://medfordma.api.civicclerk.com/v1/Events/"
    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed
    expected_exts = ('.jpg','.pdf','.docx','.xlsx','.pptx','.doc','.mp3','.mp4','.webm')
    desired_types = ["Agenda","Agenda Packet","Minutes"]

    # this link will display fileId=54 in the browser:
    # https://mozilla.github.io/pdf.js/web/viewer.html?file=https://medfordma.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=54,plainText=false)

    url = base_url
    while url:
        response = requests.get(url, headers=headers)
        data = response.json()

        for value in data["value"]:
            # value also contains things like eventName, startDateTime, agendaName...
            url2 = base_url + str(value["id"])
            response = requests.get(url2, headers=headers)
            data2 = response.json()

            if not "publishedFiles" in data2.keys(): continue

            for publishedFile in data2["publishedFiles"]:

                type = publishedFile["type"]
                if type not in desired_types: continue

                # remove strings that mess up date extraction
                string_to_extract_date = publishedFile["name"]
                string_to_extract_date = re.sub(r'FY\d{2}', '', string_to_extract_date)
                string_to_extract_date = string_to_extract_date.replace("24.01.09-Regular","2024.01.09 - Regular")
                string_to_extract_date = re.sub(r'Final \d{1}', '', string_to_extract_date)
                string_to_extract_date = string_to_extract_date.split(" - ")[0]

                try:
                    date = dparser.parse(string_to_extract_date,fuzzy=True).strftime("%Y-%m-%d") 
                except ValueError:
                    print("couldn't parse date")
                    print(string_to_extract_date)
                    print(publishedFile["name"])
                    #ipdb.set_trace()
                    date = publishedFile["publishOn"] #.strftime("%Y-%m-%d") 

                meeting_type = utils.get_meeting_type_by_title(publishedFile["name"])

                if meeting_type is None:
                    print("couldn't interpret meeting type")
                    print(publishedFile["name"])
                    #ipdb.set_trace()

                file_id = publishedFile["fileId"]
                print(file_id, date, type, meeting_type, " | ", publishedFile["name"])


                url = publishedFile["streamUrl"]
                try:
                    pass
                    #save_file(url, pdfname)
                except:
                    print("failed to download " + pdfname)
                    ipdb.set_trace()

        url = data.get("@odata.nextLink")

if __name__ == "__main__":

    scrape()


