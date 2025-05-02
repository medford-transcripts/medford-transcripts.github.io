import requests
import os
import ipdb

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
    url = base_url
    while url:
        response = requests.get(url, headers=headers)
        data = response.json()

        for value in data["value"]:
            # value also contains things like eventName, startDateTime, agendaName...
            url2 = base_url + value["id"]

            response = requests.get(url2, headers=headers)
            data2 = response.json()

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
                pdfname.replace("/","")
                pdfname.replace("?","")

                url = publishedFile["streamUrl"]
                try:
                    save_file(url, pdfname)
                except:
                    print("failed to download " + pdfname)
                    ipdb.set_trace()

        url = data.get("@odata.nextLink")

if __name__ == "__main__":

    scrape()


