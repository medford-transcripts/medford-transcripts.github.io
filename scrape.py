import requests
import os, sys
import ipdb

def save_pdf(url, pdfname):

    if not os.path.exists(pdfname):
        print("Fetching " + pdfname)
        response = requests.get(url)
        with open(pdfname, 'wb') as f:
            f.write(response.content)
    else:
        print(pdfname + ' already exists')

expected_exts = ('.jpg','.pdf','.docx','.xlsx','.pptx','.doc','.mp3','.mp4','.webm')

# rather than looping arbitrarily over these, I should parse the upper level URL and follow the links
# which would be faster and more general
headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed

for i in range(500):

    api_url = "https://medfordma.api.civicclerk.com/v1/Meetings/" + str(i+1)

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
                    url = attachment["pdfVersionFullPath"]
                    try:
                        save_pdf(url, pdfname)
                    except:
                        print("failed to download " + pdfname)

            # these are the resolutions (mostly?)
            if "reportsList" in child.keys():
                for report in child["reportsList"]:
                    pdfname = os.path.join("resolutions",report["agendaObjItemReportName"].strip() + '.pdf')
                    url = report["pdfMediaFullPath"]
                    try:
                        save_pdf(url, pdfname)
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
        url = publishedFile["streamUrl"]

        try:
            save_pdf(url, pdfname)
        except:
            print("failed to download " + pdfname)

sys.exit()

# this seems like the intended way to do this, but it doesn't actually grab everything
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

            url = publishedFile["streamUrl"]
            try:
                save_pdf(url, pdfname)
            except:
                print("failed to download " + pdfname)

    url = data.get("@odata.nextLink")
