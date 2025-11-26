from langdetect import detect
import glob
import os

# when english is enforced, it actively translates non-english to english. 
# So I let it auto-identify the language for a while.
# However, the auto-identification misidentifies the language (based on the first 30 seconds) a few percent of the time.
# When that happens, it automatically translates the rest of the video into that language.
# This is meant to identify "english" transcripts that aren't english so they can be re-transcribed. 
def is_english(text):
    try:
        return detect(text) == "en"
    except:
        return False  # short/empty/ambiguous text → treat as not English

files = glob.glob('*/20??-??-??_???????????.srt')

for fname in files:

    with open(fname, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    if not is_english(text):
        print(fname)
