DashTube 2016 (self-hosted version)
===================================

This version shows YouTube's real thumbnails, plays each video inside
the page with YouTube's own player, and shows the video's YouTube
comments under it. Thumbnails and the player need no API key; only
comments do. It has the same 1,058
Geometry Dash videos, all uploaded before Nov 24, 2016 (midnight Eastern).

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

"Only from before Nov 24, 2016" hides comments posted after the cutoff.
YouTube returns comments newest-first or by relevance, not oldest-first,
so you may need "Load more comments" to find old ones on busy videos.

Some videos can't be played inside other sites because their owner turned
off embedding; YouTube's player then shows a "Watch on YouTube" link.
