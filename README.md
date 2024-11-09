This website posts AI-generated transcripts of youtube videos relevant to Medford, MA local politics, including city council meetings, school committee meetings, subcommittee meetings, and local news reports.

The code to generate all open source (https://github.com/medford-transcripts/medford-transcripts.github.io). It uses yt_dlp to download the audio, then uses the AI-driven whisperX (https://arxiv.org/abs/2303.00747) to transcribe it and add speaker IDs. The speaker IDs in the SRT file are manually matched to names to generate the transcript that appears on the webpage. The spanish translation is done with googletrans.

The transcriptions contain many errors (particularly to the speaker identifications), and occasionally manual corrections to the SRT file are occasionally made (and corrections will be gladly accepted). Any controversial corrections will be flagged as such. 

The Spanish translation is still a work in progress. It appears large blocks of text (from long videos of one speaker) didn't translate at all. I also can't vouch for its accuracy. It's better than me, but that's not saying much. It wouldn't be hard to add more languages if that's useful, or if people have other translation tools they trust more, I can just delete it. 

The intent is to make it easier for the public to make informed decisions, advocate for their interests, engage with these meetings, and to be an informed electorate.

If you'd like to submit corrections, please send me revised versions of the raw SRT file (which is time stamped by ~sentence for captions) or the JSON files to identify each speaker -- not the HTML (which is programmatically generated from those two).

It takes about 3x real time (e.g., 3 hours for a 1-hour video) to make each transcript, so it'll take about 8 months (July 2025) to transcribe the backlog of videos I have already identified. I'm currently working on all videos on the CityofMedfordMass, medfordpublicschools464, medfordcommunitymedia391, InvestinMedford, and ALLMedford youtube channels, but if there are others, please let me know. 

For the technically minded, you're welcome to use the source code for your own purposes (or to help me out). I tried to make it reasonably easy to follow, but it definitely takes some technical chops to get going. 

There's no reason this code, with minimial modifications, wouldn't work for other municipalities or even a much broader purpose that requires transcripts of youtube videos.

If you fork this repo with the intent of making your own page of searchable transcripts, see here:
https://github.com/orgs/community/discussions/42375
https://www.bing.com/webmasters/tools/contentremoval