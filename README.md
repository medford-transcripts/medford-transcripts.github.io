This website posts AI-generated transcripts of youtube videos relevant to Medford, MA local politics, including but not limited to city council meetings, school committee meetings, subcommittee meetings, campaign videos, and local news reports.

The intent is to make it easier for the public to make informed decisions, advocate for their interests, and generally engage with these meetings and be an informed electorate.

The code to generate all open source (https://github.com/medford-transcripts/medford-transcripts.github.io). It uses yt_dlp to download the audio, then uses the AI-driven whisperX (https://arxiv.org/abs/2303.00747) to transcribe it and add speaker IDs. 

I've modified WhisperX to return the speaker embeddings, and use those embeddings to match speakers between videos. Generic IDs are propagated along with the YouTube ID for consistent naming, but are replaced with user input names should the speaker_ids.json file be edited manually.

The transcriptions contain many errors (particularly in the speaker identifications), and manual corrections to the SRT files are occasionally made. Corrections will be gladly accepted, and any controversial corrections will be flagged as such. Beginning on 1/15/2025, I began saving the word-level timestamps in model.pkl and that will need to be edited to make corrections.

The Spanish translation is still a work in progress. It appears large blocks of text (from long videos of one speaker) didn't translate at all. I also can't vouch for its accuracy. It's better than me, but that's not saying much. It wouldn't be hard to add more languages if that's useful, or if people have other translation tools they trust more, I can just delete it. 

If you'd like to submit corrections, please send me revised versions of the raw SRT file (which is time stamped by ~sentence for captions) or the JSON files to identify each speaker -- not the HTML (which is programmatically generated from those two).

It takes about 3x real time (e.g., 3 hours for a 1-hour video) for me to make each transcript, so it'll take about 8 months (July 2025) to transcribe the backlog of videos I have already identified (it would be much faster if I had a GPU). I'm currently working on all videos on the CityofMedfordMass, medfordpublicschools464, medfordcommunitymedia391, InvestinMedford, and ALLMedford youtube channels, but if there are others, please let me know. 

For the technically minded, you're welcome to use the source code for your own purposes (or to help me out). I tried to make it reasonably easy to follow, but it definitely takes some technical chops to get going. 

There's no reason this code, with minimial modifications, wouldn't work for other municipalities or even a much broader purpose that requires transcripts of youtube videos.

If you fork this repo with the intent of making your own page of searchable transcripts, see here for Search Engine Optimization (SEO) tips:
https://github.com/orgs/community/discussions/42375
https://www.bing.com/webmasters/tools/