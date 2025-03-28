import requests
import os
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

for i in range(200):

    api_url = "https://medfordma.api.civicclerk.com/v1/Meetings/" + str(i+1)

    #https://medfordma.api.civicclerk.com/v1/Events
    #https://medfordma.api.civicclerk.com/v1/EventCategories

    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed
    response = requests.get(api_url, headers=headers)
    data = response.json()

    for item in data["items"]:
        for child in item["childItems"]:

            # these are other files
            if "attachmentsList" in child.keys():
                for attachment in child["attachmentsList"]:
                    pdfname = os.path.join("resolutions",attachment["mediaFileName"])
                    url = attachment["pdfVersionFullPath"]
                    try:
                        save_pdf(url, pdfname)
                    except:
                        print("failed to download " + pdfname)

            # these are the resolutions
            if "reportsList" in child.keys():
                for report in child["reportsList"]:
                    pdfname = os.path.join("resolutions",report["agendaObjItemReportName"] + '.pdf')
                    url = report["pdfMediaFullPath"]
                    try:
                        save_pdf(url, pdfname)
                    except:
                        print("failed to download " + pdfname)

    # grab agendas and other meeting files
    api_url = "https://medfordma.api.civicclerk.com/v1/Events/"  + str(i+1)
    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed
    response = requests.get(api_url, headers=headers)

    try:
        data = response.json()
    except:
        continue
    for publishedFile in data["publishedFiles"]:
        pdfname = os.path.join("resolutions",publishedFile["name"])
        if not pdfname.endswith(expected_exts): pdfname = pdfname + '.pdf'

        url = publishedFile["streamUrl"]
        try:
            save_pdf(url, pdfname)
        except:
            print("failed to download " + pdfname)