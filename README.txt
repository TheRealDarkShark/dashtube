DashTube (self-hosted version)
==============================

A YouTube-style site for Geometry Dash videos uploaded before January 16,
2017, the day Geometry Dash update 2.1 came out. Nothing uploaded on or
after that day is listed. Dates are US Pacific time, the way YouTube shows
them.

It shows YouTube's real thumbnails and channel pictures, plays each video
inside the page with YouTube's own player, and can show the video's YouTube
comments under it. Only comments need an API key.

The time machine
----------------
The pill at the top right ("Frozen at Jan 15, 2017") opens the time
machine:
  - Pick an update (1.0 ... 2.0) to see only the videos uploaded while it
    was the newest version. The pill then reads "Frozen at 1.9"; hover it
    for the exact dates. Tick "Also show videos from before it" to include
    everything older too.
  - Or pick a range of updates (for example 1.1 through 1.5), or freeze the
    site on any day.
The choice is kept in the address (?at=1.9, ?at=1.1-1.5, ?at=2015-03-03),
so a link opens the same frozen view.

Each update starts on the first day it was out on any platform (US dates):
  1.0 Aug 13 2013   1.1 Sep 10 2013   1.2 Oct 14 2013   1.3 Nov 20 2013
  1.4 Dec 26 2013   1.5 Jan 30 2014   1.6 Mar 25 2014   1.7 May 22 2014
  1.8 Aug 7 2014    1.9 Nov 9 2014    2.0 Aug 26 2015   2.1 Jan 16 2017
Sources: the official Geometry Dash wiki (geometrydash.wiki.gg, Update
pages), App Store version history, gd.miraheze.org/wiki/Updates. Some
sources are a day later, because they date releases in European time.

It has to be opened through a web server, not by double-clicking
index.html: browsers block the page from reading data.json, and YouTube
blocks its player, on pages opened as files.


1. Run it on your own computer
------------------------------
Open a terminal in this folder and run:

    python3 -m http.server 8000

Then open  http://localhost:8000  in your browser.
(On Windows, use "python" instead of "python3".)


2. Or put it online for free (to share it)
------------------------------------------
Upload index.html and data.json to any static host, for example
GitHub Pages: make a new public repository, add both files, then turn on
Settings > Pages > "Deploy from a branch" (main, root folder).
Your site appears at  https://YOUR-NAME.github.io/REPO-NAME/


3. Turn on comments (needs a free YouTube API key)
---------------------------------------------------
YouTube has no embeddable comment section. It only shares comments
through the YouTube Data API, which needs a key:

  a. Go to https://console.cloud.google.com/ and create a project.
  b. APIs & Services > Library > "YouTube Data API v3" > Enable.
  c. APIs & Services > Credentials > Create credentials > API key.
  d. Recommended: edit the key and restrict it.
       - Application restrictions: "Websites", and add the address you
         use, e.g.  http://localhost:8000/*  or
         https://YOUR-NAME.github.io/*
       - API restrictions: "YouTube Data API v3" only.
  e. Open any video in DashTube and paste the key into the Comments box.

The key is saved only in your browser (localStorage) and is sent only to
Google. Use "Remove API key" under Comments to forget it.

Quota: the free quota is 10,000 units a day; each batch of 50 comments
costs 1 unit, so normal use won't come close.

"Only from before ..." hides comments posted after the day you froze on.
YouTube returns comments newest-first or by relevance, not oldest-first,
so you may need "Load more comments" to find old ones on busy videos.

Some videos can't be played inside other sites because their owner turned
off embedding; YouTube's player then shows a "Watch on YouTube" link.


4. Rebuilding the video list (data.json)
----------------------------------------
tools/build_data.py collects the list from YouTube (Python 3 with the
"requests" package). Every step is resumable; raw results go to
tools/cache/ (not committed).

    python tools/build_data.py search    # day-by-day YouTube search, slow
    python tools/build_data.py grow      # list Geometry Dash channels' uploads,
                                         # look up each video, find more channels
    python tools/build_data.py avatars   # channel pictures
    python tools/build_data.py build     # write data.json
    python tools/build_data.py audit     # check it; prints samples to eyeball

A video is listed when it was uploaded before Jan 16, 2017, has at least
1,000 views, and its title, channel name, tags or description name
Geometry Dash (also its Russian, Korean, Japanese and Chinese names), or it
comes from a channel that is mostly Geometry Dash and its title names a
Geometry Dash level, creator or difficulty.

YouTube briefly blocks an address that sends requests too fast (about ten
minutes); the builder slows down and waits these out. While a block lasts,
YouTube search may also ask you to prove you're not a robot in your own
browser.
