The code is all open source (https://github.com/medford-transcripts/medford-transcripts.github.io). It uses yt_dlp to download the audio, then uses the AI-driven whisperX (https://arxiv.org/abs/2303.00747) to transcribe it and add speaker IDs. The speaker IDs in the SRT file are manually matched to names to generate the transcript that appears on the webpage. The translation is done with googletrans.

The Spanish translation is still a work in progress. It appears large blocks of text (from long videos of one speaker) didn't translate at all. I also can't vouch for its accuracy. It's better than me, but that's not saying much. It wouldn't be hard to add more languages if that's useful, or if people have other translation tools they trust more, I can just delete it. 

The raw SRT file (which is time stamped by ~sentence for captions) is also available for download (you can construct the URL or browse github).

It's a lot better than the youtube captions, but it's not perfect -- particularly the speaker identification (which necessarily skews the stats), but you can refer to the timestamped links if something isn't clear.

The intent is to make it easier to engage with these meetings and to help voters make informed decisions. I welcome suggestions, constructive criticism, or help (e.g., manually correcting transcripts).

It takes about 5x real time (e.g., 5 hours for a 1-hour video) to make each transcript, so it'll be a while before I work through the backlog of 500+ videos. I'm currently working on all videos on the CityofMedfordMass, medfordpublicschools464, InvestinMedford, and ALLMedford youtube channels, but if there are others, please let me know. And for the technically minded, you're welcome to use the source code for your own purposes (or to help me out). I tried to make it reasonably easy to follow, but it definitely takes some technical bonafides to get going. 

There's no reason this code, with minimial modifications, wouldn't work for other municipalities or even a much broader purpose that requires transcripted youtube videos.