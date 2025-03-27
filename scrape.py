import requests
import os

def save_pdf(url, pdfname):

    if not os.path.exists(pdfname):
        print("Fetching " + pdfname)
        response = requests.get(url)
        with open(pdfname, 'wb') as f:
            f.write(response.content)
    else:
        print(pdfname + ' already exists')

for i in range(200):

    api_url = "https://medfordma.api.civicclerk.com/v1/Meetings/" + str(i+1)

    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed
    response = requests.get(api_url, headers=headers)
    data = response.json()

    for item in data["items"]:
        for child in item["childItems"]:
            if "attachmentsList" in child.keys():
                for attachment in child["attachmentsList"]:
                    print((attachment["mediaFileName"],attachment["pdfVersionFullPath"]))
            if "reportsList" in child.keys():
                for report in child["reportsList"]:
                    pdfname = os.path.join("resolutions",report["agendaObjItemReportName"] + '.pdf')
                    url = report["pdfMediaFullPath"]
                    try:
                        save_pdf(url, pdfname)
                    except:
                        print("failed to download " + pdfname)
