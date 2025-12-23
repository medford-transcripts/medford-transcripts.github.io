import requests
import os
import ipdb
import json
import dateutil.parser as dparser
import re

import io
from datetime import datetime
from pypdf import PdfReader

# local imports
import utils

RESNO_RE = re.compile(r"\b(\d{2}-\d{3})\b")

MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December)"

DATE_ONLY_RE = re.compile(
    rf"^\s*{MONTHS}\s+\d{{1,2}},\s+\d{{4}}\s*$",
    re.I,
)

ROLE_RE = re.compile(
    r"""
    \b(
        City\s+Council(or|lor)|
        Council(or|lor)|
        Councillor|
        Council\s+President|
        Council\s+Vice\s+President|
        Vice\s+President|
        President|
        Mayor|
        Vice\s+Mayor
    )\b
    """,
    re.I | re.VERBOSE,
)

DATE_PATTERNS = [
    (re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
        re.I
    ), "%B %d, %Y"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), None),
]

DATE_PREFIX_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\s+",
    re.I,
)

TITLE_SUFFIX_RE = re.compile(
    r",?\s*(City\s+Council(or|lor)|Councillor|Councilor|Mayor|Vice\s+Mayor).*?$",
    re.I,
)

DESC_STOP = (
    "RECOMMENDATION",
    "FISCAL IMPACT",
    "ATTACHMENTS",
    "AGENDA ITEM",
    "SPONSORED BY",
    "FULL TEXT AND DESCRIPTION",  # defensive
)

SPONSOR_STOP = (
    "AGENDA ITEM",
    "FULL TEXT AND DESCRIPTION",
)

def _starts_with_any(u: str, markers: tuple[str, ...]) -> bool:
    return any(u.startswith(m) for m in markers)

def normalize_sponsor(s: str) -> str | None:
    if not s:
        return None

    s = s.strip()

    # Remove leading date
    s = DATE_PREFIX_RE.sub("", s)

    # Remove trailing title(s)
    s = TITLE_SUFFIX_RE.sub("", s)

    # Final cleanup
    s = " ".join(s.split())

    return s or None

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

def find_key_by_url(clerk_dict: dict, target_url: str):
    for k, v in clerk_dict.items():
        if isinstance(v, dict):
            urls = v.get("url")
            if isinstance(urls, list) and target_url in urls:
                return k
    return None

def scrape_resolutions():
    url_base="https://medfordma.api.civicclerk.com"
    jsonfile="civic_clerk.json"

    if os.path.exists(jsonfile):
        with open(jsonfile, "r", encoding="utf-8") as fp:
            clerk_dict = json.load(fp)

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

                # these are the resolutions (mostly?)
                if "reportsList" in child.keys():
                    for report in child["reportsList"]:

                        url = report["pdfMediaFullPath"]
                        if url == "": continue

                        # I've already parsed this one, skip it
                        res_key = find_key_by_url(clerk_dict, url)
                        if res_key is not None: continue

                        resolution = parse_resolution_from_url(url)

                        if resolution["resolution"] in clerk_dict.keys():
                            clerk_dict[resolution["resolution"]]["url"].append(url)
                            clerk_dict[resolution["resolution"]]["dates"].append(resolution["date"])
                        else:
                            clerk_dict[resolution["resolution"]] = {
                                "title":resolution["title"],
                                "dates":[resolution["date"]],
                                "sponsors":resolution["sponsor"],
                                "description":resolution["description"],
                                "url": [url]
                            }
    # save the data
    with open(jsonfile, "w") as fp:
        json.dump(clerk_dict, fp, indent=4)


def extract_resolution_url(data):
    for item in data["items"]:
        for child in item["childItems"]:

            # these are the resolutions (mostly?)
            if "reportsList" in child.keys():
                for report in child["reportsList"]:

                    url = report["pdfMediaFullPath"]
                    if url == "": return None

                    return url

def extract_sponsors(raw: str) -> list[str]:
    if not raw:
        return []

    s = " ".join(raw.strip().split())

    # Drop pure dates
    if DATE_ONLY_RE.match(s):
        return []

    # Remove leading date if present
    s = re.sub(
        rf"^{MONTHS}\s+\d{{1,2}},\s+\d{{4}}\s*",
        "",
        s,
        flags=re.I,
    ).strip()

    if not s:
        return []

    # Remove roles entirely (important: remove, not truncate)
    s = ROLE_RE.sub("", s)

    # Cleanup repeated commas / whitespace caused by removals
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r",+", ",", s).strip(", ")

    # Split into candidate names
    parts = [p.strip() for p in s.split(",") if p.strip()]

    # Heuristic: keep things that look like names (>= 2 capitalized words)
    sponsors = []
    for p in parts:
        words = p.split()
        if len(words) >= 2 and all(w[0].isupper() for w in words):
            sponsors.append(p)

    return sponsors

def normalize_date_from_line(line: str) -> str | None:
    for rex, fmt in DATE_PATTERNS:
        m = rex.search(line)
        if not m:
            continue
        raw = m.group(0)
        if fmt:
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                return None
        # numeric
        for f in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y"):
            try:
                return datetime.strptime(raw, f).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None

def _clean(line: str) -> str:
    return " ".join(line.strip().split())

def parse_resolution_from_url(url: str) -> dict:
    pdf_bytes = requests.get(url, timeout=60).content
    reader = PdfReader(io.BytesIO(pdf_bytes))

    # Grab first 1–2 pages (headers sometimes spill)
    raw_lines = []
    for page in reader.pages[:2]:
        text = page.extract_text() or ""
        raw_lines.extend(text.splitlines())

    lines = [_clean(l) for l in raw_lines if _clean(l)]

    resolution = None
    title = None
    meeting_date = None
    sponsor = ""
    description = ""

    in_sponsor = False
    in_description = False

    # Stop conditions (tune if needed)
    STOP_FOR_BLOCKS = (
        "AGENDA ITEM",
        "RESOLUTION",  # sometimes next resolution starts
    )

    for i, line in enumerate(lines):
        u = line.upper()

        # ---- resolution + title (same line) ----
        if not resolution:
            m = RESNO_RE.search(line)
            if m:
                resolution = m.group(1)
                # title is everything after the resno, trim leading punctuation like "-" or ":".
                after = line.split(resolution, 1)[1].strip()
                after = after.lstrip("-–—:").strip()
                title = after or None

        # ---- meeting date ----
        if meeting_date is None:
            d = normalize_date_from_line(line)
            if d:
                meeting_date = d

        # ---- section transitions ----
        if "SPONSORED BY" in u:
            in_sponsor = True
            in_description = False
            # sponsor might be inline after the label
            after = re.split(r"SPONSORED BY[:\s]*", line, flags=re.I)
            if len(after) > 1 and after[1].strip():
                sponsor = after[1].strip()
            continue

        if "FULL TEXT AND DESCRIPTION" in u:
            in_description = True
            in_sponsor = False
            # If the template sometimes has text on same line, capture it:
            after = re.split(r"FULL TEXT AND DESCRIPTION[:\s]*", line, flags=re.I)
            if len(after) > 1 and after[1].strip():
                description = after[1].strip()
            continue

        # ---- accumulate blocks ----
        if in_sponsor:
            if any(stop in u for stop in STOP_FOR_BLOCKS) or "FULL TEXT AND DESCRIPTION" in u:
                in_sponsor = False
            else:
                sponsor = (sponsor + " " + line).strip() if sponsor else line
            continue

        if in_description:
            if _starts_with_any(u, DESC_STOP):
                in_description = False
            else:
                description = (description + " " + line).strip() if description else line
            continue

    return {
        "resolution": resolution,
        "title": title,
        "description": description or None,
        "sponsor": extract_sponsors(sponsor),
        "date": meeting_date,
    }

def find_key_by_agendaid():

# this seems like the smart/intended way to do this, 
# but there are many URLs that don't seem to be linked this way
# so we'll do it the dumb way for now
def scrape_smart():

    event_base_url = "https://medfordma.api.civicclerk.com/v1/Events/"
    meeting_base_url = "https://medfordma.api.civicclerk.com/v1/Meetings/"


    headers = {"User-Agent": "Mozilla/5.0"}  # Add other headers if needed
    expected_exts = ('.jpg','.pdf','.docx','.xlsx','.pptx','.doc','.mp3','.mp4','.webm')
    desired_types = ["Agenda","Agenda Packet","Minutes"]

    # this link will display fileId=54 in the browser:
    # https://mozilla.github.io/pdf.js/web/viewer.html?file=https://medfordma.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=54,plainText=false)

    jsonfile="civic_clerk.json"
    if os.path.exists(jsonfile):
        with open(jsonfile, "r", encoding="utf-8") as fp:
            clerk_dict = json.load(fp)
    else:
        clerk_dict = {}

    url = event_base_url
    while url:
        response = requests.get(url, headers=headers)
        data = response.json()

        for value in data["value"]:
            # value also contains things like eventName, startDateTime, agendaName...

            event_url = event_base_url + str(value["id"])
            response = requests.get(event_url, headers=headers)
            event_data = response.json()
            if not "publishedFiles" in event_data.keys(): continue

            agenda_id = value["agendaId"]
            res_key = find_key_by_agendaid(agenda_id)
            if res_key is None:
                meeting_url = meeting_base_url + str(agenda_id)
                response = requests.get(meeting_url, headers=headers)
                meeting_data = response.json()

                resolution_url = extract_resolution_url(meeting_data)
                resolution_dict = parse_resolution_from_url(resolution_url)

                res_no = resolution_dict["resolution"]
                date = resolution_dict["date"]
                pdfname = "resolutions/" + res_no + "_" + agenda_id + '.pdf'

                if res_no not in clerk_dict.keys():
                    clerk_dict[res_no] = {}

                if date not in clerk_dict[res_no].keys():
                    clerk_dict[res_no][date] = {}

                clerk_dict[res_no][date]["title"] = resolution_dict["title"]
                clerk_dict[res_no][date]["sponsors"] = resolution_dict["sponsor"]
                clerk_dict[res_no][date]["description"] = resolution_dict["description"]
                clerk_dict[res_no][date]["pdfname"] = pdfname
                clerk_dict[res_no][date]["agenda_id"] = agenda_id

                save_file(resolution_url, pdfname)

            else:
                # I've already parsed this one, skip it
                pass

            for publishedFile in event_data["publishedFiles"]:

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
                    continue
                    date = publishedFile["publishOn"] #.strftime("%Y-%m-%d") 

                meeting_type = utils.get_meeting_type_by_title(publishedFile["name"])

                if meeting_type is None:
                    print("couldn't interpret meeting type")
                    print(publishedFile["name"])
                    continue
                    #ipdb.set_trace()

                file_id = publishedFile["fileId"]
                print(file_id, date, type, meeting_type, " | ", publishedFile["name"])

                #url = publishedFile["streamUrl"]


                url = "https://mozilla.github.io/pdf.js/web/viewer.html?file=https://medfordma.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=" + str(file_id) + ",plainText=false)"

                if meeting_type in clerk_dict.keys():
                    if date in clerk_dict[meeting_type].keys():
                        clerk_dict[meeting_type][date][type] = url
                    else:
                        clerk_dict[meeting_type][date] = {type:url}
                else:
                    clerk_dict[meeting_type] = {
                        date: {
                            type:url
                        }
                    }

                # save the data
                with open(jsonfile, "w") as fp:
                    json.dump(clerk_dict, fp, indent=4)

        url = data.get("@odata.nextLink")

if __name__ == "__main__":

    scrape()


