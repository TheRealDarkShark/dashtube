#!/usr/bin/env python3
"""DashTube data builder: finds Geometry Dash videos on YouTube uploaded before
Jan 16, 2017 (the day Update 2.1 came out) and writes ../data.json.

Every stage is resumable. Raw results are appended to tools/cache/*.jsonl, so a
stopped run picks up where it left off.

    python tools/build_data.py search            # day-by-day YouTube search (slow; stops if YouTube blocks it)
    python tools/build_data.py search --extended # more query variants on busy days
    python tools/build_data.py grow              # channels -> details -> discover, repeated until nothing new
    python tools/build_data.py avatars           # channel pictures still missing
    python tools/build_data.py build             # write data.json
    python tools/build_data.py audit             # check data.json; exits 1 if anything is wrong
    python tools/build_data.py all               # every stage above, in order
  (single steps: details, channels, discover)

Uses YouTube's own web API (the one youtube.com calls), throttled. Needs `requests`.
YouTube answers fast searching with an "unusual traffic" block that lasts a while; the search stage
then stops by itself, and everything else (channel listings, video details) keeps working.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'tools', 'cache')
DATA = os.path.join(ROOT, 'data.json')

FIRST_DAY = dt.date(2013, 1, 1)
LAST_DAY = dt.date(2017, 1, 15)   # last day listed (Pacific). Update 2.1 came out Jan 16, 2017.
CAP = '2017-01-16'                # Pacific date: this day and later are never listed
GD_OUT = '2013-08-13'             # Geometry Dash 1.0 came out; earlier videos count only from RobTop or titled "Geometry Dash"
MIN_VIEWS = 1000
ROBTOP = 'UCz_yk8mDSAnxJq0ar66L4sw'
API = 'https://www.youtube.com/youtubei/v1/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
CATS = ('official', 'levels', 'demons', 'creators', 'community', 'guides', 'more')

# Era starts (Pacific dates), used by the audit to print boundary samples. Same table as index.html.
ERAS = [('1.0', '2013-08-13'), ('1.1', '2013-09-10'), ('1.2', '2013-10-14'), ('1.3', '2013-11-20'),
        ('1.4', '2013-12-26'), ('1.5', '2014-01-30'), ('1.6', '2014-03-25'), ('1.7', '2014-05-22'),
        ('1.8', '2014-08-07'), ('1.9', '2014-11-09'), ('2.0', '2015-08-26')]

# ---------------------------------------------------------------- what counts as Geometry Dash
GD_NAME = re.compile(
    r'\bge?o?m?e?tr[iy]a?[\s_.\-]{0,2}d[ae]sh'      # geometry dash, geometrydash, geometri/geomtry/gemetry dash, geometry desh
    r'|геометр[иыя]\w*[\s_\-]*д[аэе]ш'              # Russian
    r'|지오메트리\s*대[쉬시]'                        # Korean
    r'|ジオメトリー?\s*ダッシュ'                      # Japanese
    r'|几何冲刺|幾何衝刺'                            # Chinese
    r'|جيومتري\s*داش',                              # Arabic
    re.I)

OFFICIAL_DISTINCT = ['Stereo Madness', 'Polargeist', 'Base After Base', "Can'?t Let Go", 'xStep', 'Clutterfunk',
                     'Theory of Everything 2', 'Theory of Everything', 'Electroman Adventures', 'Clubstep',
                     'Electrodynamix', 'Hexagon Force', 'Blast Processing', 'Geometrical Dominator', 'Deadlocked',
                     'The Seven Seas', 'Viking Arena', 'Airborne Robots', 'Space Pirates', 'Monster Dance Off']
OFFICIAL_GENERIC = ['Back on Track', 'Dry Out', 'Jumper', 'Time Machine', 'Cycles', 'Payload', 'Beast Mode',
                    'Machina', 'Years', 'Frontlines', 'Striker', 'Embers', 'Round 1']
USER_LEVELS = ['Bloodbath', 'Sonic Wave', 'Cataclysm', 'Yatagarasu', 'Ultra Violence', 'Nine Circles', 'The Nightmare',
               'Duelo Maestro', 'Toxic Factory', 'Windy Landscape', 'Fairydust', 'Retray', 'Platinum Adventure',
               'Death Moon', 'Aftercatabath', 'Cadrega City', 'Ice Carbon Diablo', 'Crimson Planet', 'Sakupen Hell',
               'Plasma Pulse', 'Ultra Paracosm', 'Lucid Nightmares', 'Black Blizzard', 'Deadly Clubstep',
               'Theory of Skillness', 'Bausha Vortex', 'Hexagon Dimension', 'Cyber Chaos', 'Magma Bound',
               'The Ultimate Phase', 'Heaven Sky', 'Frozen Days', 'Dorabae', 'Supersonic Zone', 'Dash Spider',
               'Speed Racer', 'Hyper Paracosm', 'Jawbreaker', 'Fantasy Planet', 'Phobos', 'Clutterfunk 2',
               'Clubstep 2', 'Electrodynamix 2', 'Hexagon Force 2', 'Fingerbang', 'Bloodlust', 'Necropolis',
               'Gamma Ray', 'Thinking Space', 'Sunset Sandstorm', 'Allegiance', 'Cosmic Dreamer', 'Forest Temple']
CREATORS = ['Viprin', 'Krazyman50', 'Zobros', 'Serponge', 'Michigun', 'Etzer', 'Sunix', 'TrusTa', 'Funnygame',
            'Manix648', 'Knobbelboy', 'ZenthicAlpha', 'Wulzy', 'Glittershroom', 'Jeyzor', 'Spu7nix', 'Adiale',
            'Ggb0y', 'Woogi1411', 'Noobas', 'Cyclic', 'Riot', 'Andromeda', 'Colon', 'Robtop', 'Rob Top', 'RobTopGames',
            'DorabaeGD', 'Lemons', 'Rustam', 'Jakerz', 'Xender Game', 'Npesta', 'Mbed', 'Sea1997', 'ThePuffin',
            'Juniper', 'Shulkern', 'Panman', 'SrGuillester', 'FlaaFlaa', 'TheRealDarnoc', 'Codex', 'Mulpan', 'Rlol']


def _words(names):
    return r'\b(?:' + '|'.join(re.escape(n).replace("'\\?", "'?") if "'?" in n else re.escape(n) for n in names) + r')\b'


# Names that point at Geometry Dash only when something else already does (several are also words or other games).
DISTINCT = re.compile(_words(OFFICIAL_DISTINCT + USER_LEVELS + CREATORS) +
                      r"|\b(?:insane|extreme|hard|medium|easy) demons?\b|\buser coins\b|\bsecret coins\b"
                      r"|\bmega ?collab|\bgauntlets?\b|\bmap ?packs?\b|\bdemon (?:list|run)", re.I)
GENERIC = re.compile(_words(OFFICIAL_GENERIC) +
                     r"|(?-i:\bGD\b)|\bdemons?\b|\bverif|\b100\s?%|\bcoins?\b|\bcollab|\blayout|\bnerf|\bbuff|\bXL\b"
                     r"|\brated\b|\bfeatured\b|\blevel request|\bmagic level|\bwave\b|\bship\b|\bufo\b|\bdual\b"
                     r"|\bcube\b|\blevel ?\d|\bsneak ?peek", re.I)
# Titles about another game. Videos that only mention GD in tags/description and name one of these are rejected.
OTHER_GAMES = re.compile(
    r'\b(?:minecraft|five nights|fnaf|roblox|gta|grand theft|call of duty|cod\b|black ops|fortnite|undertale|'
    r'terraria|pok[eé]mon|mario|zelda|clash (?:royale|of clans)|agar\.?io|slither\.?io|diep\.?io|piano tiles|'
    r'flappy bird|impossible game|bit\.?trip|cs:?go|counter.?strike|overwatch|osu!?|league of legends|dota|'
    r'world of warcraft|ratchet|doom\b|mortal kombat|smash bros|splatoon|subway surfers|temple run|'
    r'angry birds|plants vs|happy wheels|garry|tf2|team fortress|rocket league|hearthstone|skyrim|fallout|'
    r'sims\b|portal 2|bendy|hello neighbor|super meat boy|crossy road|color switch|'
    r'dashy square|shooty|cuphead|unturned|growtopia|pixel gun|geometry wars|polytopia)', re.I)
LEVEL_NAMES = sorted(OFFICIAL_DISTINCT + OFFICIAL_GENERIC + USER_LEVELS, key=len, reverse=True)
OFFICIAL_RE = re.compile(_words(OFFICIAL_DISTINCT), re.I)
DEMON_NAMES_RE = re.compile(_words(USER_LEVELS + ['Clubstep', 'Theory of Everything 2', 'Deadlocked']), re.I)


def loose_gd(title):
    return bool(GD_NAME.search(title) or DISTINCT.search(title) or GENERIC.search(title))


# ---------------------------------------------------------------- dates (Pacific, as YouTube shows them)
def us_pacific_offset(utc):
    """-7 during US daylight time (second Sunday of March 10:00 UTC to first Sunday of November 09:00 UTC), else -8."""
    y = utc.year
    mar1 = dt.datetime(y, 3, 1)
    start = mar1 + dt.timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=10)
    nov1 = dt.datetime(y, 11, 1)
    end = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7, hours=9)
    return -7 if start <= utc < end else -8


def to_pacific(stamp):
    """ISO time with any offset -> 'YYYY-MM-DDTHH:MM:SS-0X:00' in US Pacific time, or '' if unreadable."""
    try:
        t = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return ''
    if t.tzinfo is None:
        return ''
    utc = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
    off = us_pacific_offset(utc)
    local = utc + dt.timedelta(hours=off)
    return local.strftime('%Y-%m-%dT%H:%M:%S') + f'-0{-off}:00'


# ---------------------------------------------------------------- network
class Blocked(Exception):
    """YouTube answered a search with its 'unusual traffic' page: stop searching for now."""


class Net:
    def __init__(self, rate=6.0, jitter=False):
        self.interval = 1.0 / rate
        self.jitter = jitter
        self.lock = threading.Lock()
        self.next_t = 0.0
        self.pause_until = 0.0
        self.big_until = 0.0
        self.backoff = 0.0
        self.last_throttle = 0.0
        self.local = threading.local()
        self.version = '2.20241120.01.00'
        self.stats = collections.Counter()

    def session(self):
        s = getattr(self.local, 's', None)
        if s is None:
            s = requests.Session()
            s.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
            s.cookies.set('SOCS', 'CAI', domain='.youtube.com')
            self.local.s = s
        return s

    def ctx(self):
        return {'client': {'clientName': 'WEB', 'clientVersion': self.version, 'hl': 'en', 'gl': 'US'}}

    def init_version(self):
        try:
            r = self.session().get('https://www.youtube.com/?hl=en', timeout=30)
            m = re.search(r'"INNERTUBE_CLIENT_VERSION":"([\d.]+)"', r.text)
            if m:
                self.version = m.group(1)
        except requests.RequestException:
            pass
        log(f'client version {self.version}')

    def wait_turn(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t, self.pause_until)
            self.next_t = t + self.interval * (random.uniform(0.6, 1.6) if self.jitter else 1.0)
        d = t - time.monotonic()
        if d > 0:
            time.sleep(d)

    def pause(self, secs, why):
        with self.lock:
            until = time.monotonic() + secs
            if until > self.pause_until:
                self.pause_until = until
                log(f'  pausing {secs:.0f}s ({why})')

    def throttle(self, why, small=False):
        with self.lock:
            now = time.monotonic()
            if small:
                pause = 5.0
            else:
                if now < self.big_until:   # requests already in flight when the pause began: don't escalate again
                    return
                if now - self.last_throttle > 600:
                    self.backoff = 0
                self.backoff = min(900.0, max(30.0, self.backoff * 2))
                self.last_throttle = now
                pause = self.backoff
                self.big_until = now + pause
            if now + pause > self.pause_until:
                self.pause_until = now + pause
                log(f'  pausing {pause:.0f}s ({why})')
            self.stats['throttle'] += 1

    def post(self, endpoint, body, tries=8):
        for _ in range(tries):
            self.wait_turn()
            try:
                r = self.session().post(API + endpoint + '?prettyPrint=false', json=body, timeout=30)
            except requests.RequestException as e:
                self.throttle(f'{e.__class__.__name__}', small=True)
                continue
            self.stats['req'] += 1
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    self.throttle('bad JSON', small=True)
                    continue
            if r.status_code in (400, 404):
                return None
            if endpoint == 'search' and r.status_code in (403, 429):
                raise Blocked(f'HTTP {r.status_code}')
            self.throttle(f'HTTP {r.status_code}', small=r.status_code >= 500)
        raise RuntimeError(f'gave up on {endpoint}')

    def get(self, url, tries=5):
        for _ in range(tries):
            self.wait_turn()
            try:
                r = self.session().get(url, timeout=30)
            except requests.RequestException as e:
                self.throttle(f'{e.__class__.__name__}', small=True)
                continue
            self.stats['req'] += 1
            if r.status_code == 200:
                return r.text
            if r.status_code in (400, 404):
                return None
            self.throttle(f'HTTP {r.status_code}', small=r.status_code >= 500)
        raise RuntimeError('gave up on GET')


class Store:
    def __init__(self, name):
        self.path = os.path.join(CACHE, name + '.jsonl')
        self.lock = threading.Lock()

    def load(self):
        out = []
        if os.path.exists(self.path):
            with open(self.path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            pass  # half-written last line after a crash
        return out

    def add(self, rec):
        line = json.dumps(rec, ensure_ascii=False, separators=(',', ':'))
        with self.lock, open(self.path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')


def log(msg):
    print(time.strftime('%H:%M:%S ') + msg, flush=True)


def run_pool(tasks, fn, workers, label):
    done = 0
    total = len(tasks)
    lock = threading.Lock()
    t0 = time.monotonic()

    def wrap(task):
        nonlocal done
        try:
            fn(task)
        except Exception as e:  # noqa: BLE001 - one bad item must not stop a multi-hour run
            log(f'  {label}: {task!r:.80} failed: {e}')
        with lock:
            done += 1
            if done % 250 == 0 or done == total:
                el = time.monotonic() - t0
                eta = el / done * (total - done)
                log(f'  {label}: {done}/{total}  ({el / 60:.0f} min, ~{eta / 60:.0f} min left)')

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(wrap, tasks))


# ---------------------------------------------------------------- parsing helpers
def walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(o, list):
        for x in o:
            yield from walk(x, key)


def text(t):
    if not t:
        return ''
    if isinstance(t, str):
        return t
    return t.get('simpleText') or t.get('content') or ''.join(r.get('text', '') for r in t.get('runs', []))


def parse_views(s, compact=False):
    """'1,234 views' / '1.2K views' / 'No views'; with compact=True also a bare '1.4M' or '234'."""
    s = (s or '').replace('\u202f', ' ').replace('\xa0', ' ').strip()
    if not s:
        return -1
    if re.match(r'no views', s, re.I):
        return 0
    m = re.fullmatch(r'([\d.,]+)\s*([KMB])?\s*views?', s, re.I) or (compact and re.fullmatch(r'([\d.,]+)\s*([KMB])?', s, re.I))
    if not m:
        return -1
    n = float(m.group(1).replace(',', ''))
    if m.group(2):
        n *= {'K': 1e3, 'M': 1e6, 'B': 1e9}[m.group(2).upper()]
    return int(n)


def parse_age(s):
    """Whole years since upload from '9 years ago' / '9y ago' / 'Streamed 9 years ago'; 0 if under a year, -1 if unknown."""
    m = re.search(r'(\d+)\s*(years?|y|months?|mo|weeks?|w|days?|d|hours?|h|minutes?|min|m|seconds?|s)\s+ago', s or '')
    if not m:
        return -1
    return int(m.group(1)) if m.group(2) in ('year', 'years', 'y') else 0


def parse_len(s):
    parts = (s or '').strip().split(':')
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        return -1
    n = 0
    for p in parts:
        n = n * 60 + int(p)
    return n


def norm_av(u):
    if not u:
        return ''
    if u.startswith('//'):
        u = 'https:' + u
    if not re.match(r'https://yt3\.(?:ggpht|googleusercontent)\.com/', u):
        return ''
    return re.sub(r'=s\d+[^/]*$', '', u)


def cont_token(j):
    tok = None
    for c in walk(j, 'continuationItemRenderer'):
        t = next(walk(c, 'token'), None)
        if t:
            tok = t
    return tok


def from_video_renderer(v):
    vid = v.get('videoId')
    if not vid:
        return None
    owner = v.get('ownerText') or v.get('longBylineText') or v.get('shortBylineText') or {}
    cid = next((b for b in walk(owner, 'browseId') if str(b).startswith('UC')), '')
    av = next(walk(v.get('channelThumbnailSupportedRenderers', {}), 'url'), '')
    return {'id': vid, 't': text(v.get('title')), 'cid': cid, 'ch': text(owner), 'av': norm_av(av),
            'views': parse_views(text(v.get('viewCountText'))), 'len': parse_len(text(v.get('lengthText'))),
            'age': parse_age(text(v.get('publishedTimeText')))}


def from_lockup(x):
    if x.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO' or not x.get('contentId'):
        return None
    md = x.get('metadata', {}).get('lockupMetadataViewModel', {})
    parts = [text(p.get('text')) for row in walk(md.get('metadata', {}), 'metadataParts') for p in row]
    views = next((parse_views(p) for p in parts if parse_views(p) >= 0), -1)
    if views < 0:   # compact rows (related videos): [channel, '1.4M', '9y ago']
        views = next((parse_views(p, True) for p in parts[1:] if parse_views(p, True) >= 0), -1)
    age = next((parse_age(p) for p in parts if parse_age(p) >= 0), -1)
    ch = next((p for p in parts if parse_views(p, True) < 0 and parse_age(p) < 0), '')
    badges = [text(b.get('text')) for b in walk(x, 'thumbnailBadgeViewModel')]
    ln = next((parse_len(b) for b in badges if parse_len(b) >= 0), -1)
    cid = next((b for b in walk(x, 'browseId') if str(b).startswith('UC')), '')
    av = ''
    for a in walk(x, 'avatarViewModel'):
        av = next(walk(a, 'url'), '')
        break
    return {'id': x['contentId'], 't': text(md.get('title')), 'cid': cid, 'ch': ch, 'av': norm_av(av),
            'views': views, 'len': ln, 'age': age}


def items_in(j):
    out = {}
    for v in walk(j, 'videoRenderer'):
        it = from_video_renderer(v)
        if it:
            out.setdefault(it['id'], it)
    for x in walk(j, 'lockupViewModel'):
        it = from_lockup(x)
        if it:
            out.setdefault(it['id'], it)
    return out


def worth_details(it):
    """Listing says it could be old enough and popular enough."""
    return (it['age'] < 0 or it['age'] >= 9) and (it['views'] < 0 or it['views'] >= MIN_VIEWS)


# ---------------------------------------------------------------- stage: search
BASE = [('geometry dash', ''), ('geometry dash', 'CAI%3D'), ('geometry dash', 'CAM%3D'), ('gd', ''),
        ('geometry dash demon', ''), ('geometry dash level', ''), ('geometry dash 100%', '')]
EXTRA = [  # (query, first day, last day)
    ('geometry dash collab', None, None), ('geometry dash megacollab', '2014-06-01', None),
    ('geometry dash layout', '2015-06-01', None), ('geometry dash verified', None, None),
    ('geometry dash extreme demon', '2015-08-01', None), ('geometry dash insane demon', None, None),
    ('geometry dash animation', None, None), ('geometry dash tutorial', None, None),
    ('geometry dash song', None, None), ('geometry dash rage', None, None), ('geometry dash funny', None, None),
    ('geometry dash all coins', None, None), ('geometry dash custom level', None, None),
    ('geometry dash creator', None, None), ('geometry dash top 10', None, None),
    ('geometry dash gameplay', None, None), ('geometry dash live', None, None),
    ('geometry dash 1.9', '2014-08-01', '2015-12-31'), ('geometry dash 2.0', '2014-11-01', None),
    ('geometry dash 2.1', '2015-09-01', None), ('geometry dash meltdown', '2015-11-15', None),
    ('geometry dash world', '2016-11-15', None), ('geometry dash lite', None, None),
    ('geometry dash steam', '2014-12-01', None), ('geometry dash español', None, None),
    ('geometry dash nivel', None, None), ('geometry dash português', None, None), ('geometry dash fase', None, None),
    ('геометри даш', None, None), ('지오메트리 대쉬', None, None), ('ジオメトリーダッシュ', None, None),
    ('geometry dash indonesia', None, None), ('geometry dash deutsch', None, None),
    ('geometry dash français', None, None), ('geometry dash italiano', None, None), ('geometry dash polski', None, None),
    ('geometry dash türkçe', None, None), ('geometry dash việt', None, None)]


def days():
    d = FIRST_DAY
    while d <= LAST_DAY:
        yield d
        d += dt.timedelta(days=1)


def stage_search(net, workers, extended, threshold):
    """YouTube blocks search for a while (about ten minutes) from an address that searches too fast
    ('unusual traffic'). This runs slowly, waits out each block, and stops after several; rerun to continue."""
    st = Store('search')
    done = {r['k'] for r in st.load()}
    stop = threading.Event()
    blocks = [0]
    lock = threading.Lock()

    def one(task):
        q, sp, day = task
        body = {'context': net.ctx(), 'query': f'{q} after:{day} before:{day + dt.timedelta(days=1)}'}
        if sp:
            body['params'] = sp
        for _ in range(3):
            if stop.is_set():
                return
            items = {}
            try:
                j = net.post('search', body)
                pages = 0
                while j is not None:
                    pages += 1
                    got = items_in(j)
                    new = [i for i in got if i not in items]
                    for i in new:
                        items[i] = got[i]
                    tok = cont_token(j)
                    if not tok or len(new) < 5 or pages >= 3:
                        break
                    j = net.post('search', {'context': net.ctx(), 'continuation': tok})
            except Blocked as e:
                with lock:
                    if net.pause_until > time.monotonic():
                        continue          # already waiting out this block
                    blocks[0] += 1
                    if blocks[0] > 8:
                        stop.set()
                        log(f'  search: blocked {blocks[0]} times; stopping. Rerun later to continue.')
                        return
                    net.pause(600, f'YouTube is blocking searches ({e}), block {blocks[0]}')
                continue
            st.add({'k': f'{q}|{sp}|{day}', 'items': list(items.values())})
            return

    tasks = [(q, sp, d) for d in days() for q, sp in BASE if f'{q}|{sp}|{d}' not in done]
    random.Random(7).shuffle(tasks)   # spread over the whole period, so a stopped run still samples every year
    log(f'search: {len(tasks)} base queries to run ({len(done)} done before)')
    run_pool(tasks, one, workers, 'search')
    if not extended or stop.is_set():
        return
    per_day = collections.defaultdict(set)
    for r in st.load():
        q, sp, d = r['k'].split('|')
        if (q, sp) in BASE:
            per_day[d].update(i['id'] for i in r['items'])
    done = {r['k'] for r in st.load()}
    tasks = []
    for d in days():
        ds = str(d)
        if len(per_day[ds]) < threshold:
            continue
        for q, a, b in EXTRA:
            if (a and ds < a) or (b and ds > b) or f'{q}||{d}' in done:
                continue
            tasks.append((q, '', d))
    random.Random(8).shuffle(tasks)
    busy = sum(1 for d in days() if len(per_day[str(d)]) >= threshold)
    log(f'search --extended: {busy} busy days, {len(tasks)} extra queries to run')
    run_pool(tasks, one, workers, 'search+')


# ---------------------------------------------------------------- stage: details
def fetch_player(net, vid):
    for attempt in range(6):
        j = net.post('player', {'context': net.ctx(), 'videoId': vid, 'contentCheckOk': True, 'racyCheckOk': True})
        if j is None:
            return {'id': vid, 'st': 'HTTP'}
        ps = j.get('playabilityStatus', {})
        status, why = ps.get('status', ''), ps.get('reason', '') or text(ps.get('errorScreen', {}).get('playerErrorMessageRenderer', {}).get('reason'))
        mf = j.get('microformat', {}).get('playerMicroformatRenderer', {})
        vd = j.get('videoDetails', {})
        if not mf.get('publishDate') and 'bot' in why.lower():
            net.throttle('bot check')
            continue
        if not mf.get('publishDate'):
            got = watch_page(net, vid)
            if got:
                mf, vd = got
        if not mf.get('publishDate'):
            return {'id': vid, 'st': status or 'NOMETA', 'why': why[:160]}
        desc = vd.get('shortDescription') or text(mf.get('description')) or ''
        return {'id': vid, 'st': 'OK', 'pub': mf.get('publishDate'),
                't': vd.get('title') or text(mf.get('title')),
                'cid': vd.get('channelId') or mf.get('externalChannelId', ''),
                'ch': vd.get('author') or mf.get('ownerChannelName', ''),
                'len': int(vd.get('lengthSeconds') or mf.get('lengthSeconds') or 0),
                'views': int(vd.get('viewCount') or mf.get('viewCount') or 0),
                'kw': vd.get('keywords') or [], 'd': desc[:300], 'dgd': bool(GD_NAME.search(desc)),
                'cat': mf.get('category', ''), 'live': bool(vd.get('isLiveContent'))}
    raise RuntimeError('bot check kept failing')


def watch_page(net, vid):
    html = net.get(f'https://www.youtube.com/watch?v={vid}&hl=en&gl=US')
    if not html:
        return None
    m = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var\s|</script>)', html, re.S)
    if not m:
        return None
    try:
        pj = json.loads(m.group(1))
    except ValueError:
        return None
    return pj.get('microformat', {}).get('playerMicroformatRenderer', {}), pj.get('videoDetails', {})


def legacy():
    """The original hand-checked list (1,058 videos), copied once from data.json before the first rebuild."""
    path = os.path.join(CACHE, 'legacy_data.json')
    if not os.path.exists(path):
        if not os.path.exists(DATA):
            return {}, {}
        with open(DATA, encoding='utf-8') as f:
            d = json.load(f)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    rows = {r[0]: {'id': r[0], 't': r[1], 'cid': d['c'][r[2]][0], 'ch': d['c'][r[2]][1], 'len': r[3], 'views': r[4],
                   'pub': r[5], 'cat': r[6], 'lab': r[7]} for r in d['v']}
    chans = {c[0]: c for c in d['c']}
    return rows, chans


def candidates():
    """Video ids worth a details lookup: search hits, channel-crawl hits and the original list."""
    want = {}
    for r in Store('search').load() + Store('found').load():
        for it in r['items']:
            if worth_details(it):
                want.setdefault(it['id'], it)
    for r in Store('channels').load():
        if r.get('st') != 'OK':
            continue
        items = r['items']
        heavy = bool(items) and sum(loose_gd(i['t']) for i in items) / len(items) >= 0.3
        for it in items:
            if worth_details(it) and (heavy or loose_gd(it['t'])):
                it = dict(it, cid=it.get('cid') or r['cid'])
                want.setdefault(it['id'], it)
    for vid, row in legacy()[0].items():
        want.setdefault(vid, row)
    return want


def stage_details(net, workers):
    st = Store('details')
    have = {r['id'] for r in st.load()}
    want = candidates()
    tasks = [v for v in want if v not in have]
    log(f'details: {len(want)} candidates, {len(tasks)} to look up')
    run_pool(tasks, lambda vid: st.add(fetch_player(net, vid)), workers, 'details')


# ---------------------------------------------------------------- stage: channels
def crawl_channel(net, cid):
    j = net.post('browse', {'context': net.ctx(), 'browseId': cid, 'params': 'EgZ2aWRlb3PyBgQKAjoA'})
    if j is None:
        return {'cid': cid, 'st': 'ERR'}
    cm = j.get('metadata', {}).get('channelMetadataRenderer', {})
    av = norm_av(((cm.get('avatar') or {}).get('thumbnails') or [{}])[0].get('url', ''))
    tok = None
    for li in walk(j, 'listItemViewModel'):
        if text(li.get('title')) == 'Oldest':
            tok = next(walk(li, 'token'), None)
    oldest = bool(tok)
    if tok:
        j = net.post('browse', {'context': net.ctx(), 'continuation': tok})
    items, pages, stop, gave_up = [], 0, False, False
    while j is not None and pages < 80:
        pages += 1
        for x in walk(j, 'lockupViewModel'):
            it = from_lockup(x)
            if not it:
                continue
            if oldest and 0 <= it['age'] < 9:
                stop = True
                break
            it['cid'] = cid
            items.append(it)
        if pages >= 5 and not GD_NAME.search(cm.get('title', '')) and not any(loose_gd(i['t']) for i in items):
            gave_up = True   # 150 videos and none looks like Geometry Dash: not a GD channel
            break
        tok = cont_token(j)
        if stop or not tok:
            break
        j = net.post('browse', {'context': net.ctx(), 'continuation': tok})
    keep = [i for i in items if i['age'] < 0 or i['age'] >= 9]
    return {'cid': cid, 'st': 'OK', 'title': cm.get('title', ''), 'av': av, 'oldest': oldest,
            'pages': pages, 'gave_up': gave_up, 'items': keep}


def is_gd_channel(rec):
    """A crawled channel whose pre-2017 uploads are clearly Geometry Dash (used to look for more channels)."""
    if rec.get('st') != 'OK':
        return False
    items = rec['items']
    n = sum(1 for i in items if GD_NAME.search(i['t']))
    return bool(GD_NAME.search(rec.get('title', ''))) and n >= 1 or n >= 3 or (n >= 1 and n / max(1, len(items)) >= 0.3)


def stage_channels(net, workers, min_strong):
    st = Store('channels')
    have = {r['cid'] for r in st.load()}
    strong = collections.Counter()
    named = set()
    for r in Store('details').load():
        if r.get('st') != 'OK' or not r.get('cid'):
            continue
        pub = to_pacific(r['pub'])
        if GD_NAME.search(r.get('ch', '')):
            named.add(r['cid'])
        if pub and pub[:10] < CAP and r['views'] >= MIN_VIEWS and GD_NAME.search(r['t']):
            strong[r['cid']] += 1
    found = set()
    for r in Store('found').load():
        found.update(r['cids'])
    pick = {c for c, n in strong.items() if n >= min_strong} | named | set(legacy()[1]) | found
    tasks = sorted(c for c in pick if c and c.startswith('UC') and c not in have)
    log(f'channels: {len(pick)} channels to cover, {len(tasks)} still to list')
    run_pool(tasks, lambda cid: st.add(crawl_channel(net, cid)), workers, 'channels')
    return len(tasks)


# ---------------------------------------------------------------- stage: discover (more channels, without search)
def related_items(net, vid):
    j = net.post('next', {'context': net.ctx(), 'videoId': vid})
    sec = (j or {}).get('contents', {}).get('twoColumnWatchNextResults', {}).get('secondaryResults', {})
    return list(items_in(sec).values())


def stage_discover(net, workers, per_channel):
    """For every Geometry Dash channel found so far: read its featured-channels list, and the related videos of
    its most-viewed old GD videos. Channels of old GD videos found that way are queued for `channels`."""
    found = Store('found')
    seen = {r['from'] for r in found.load()}
    gd = [r for r in Store('channels').load() if is_gd_channel(r)]
    tasks = []
    for r in gd:
        if 'f:' + r['cid'] not in seen:
            tasks.append(('f', r['cid']))
        top = sorted((i for i in r['items'] if GD_NAME.search(i['t'])), key=lambda i: -i['views'])[:per_channel]
        tasks += [('r', i['id']) for i in top if 'r:' + i['id'] not in seen]
    log(f'discover: {len(gd)} Geometry Dash channels; {len(tasks)} featured lists and related-video lists to read')

    def one(task):
        kind, key = task
        if kind == 'f':
            j = net.post('browse', {'context': net.ctx(), 'browseId': key, 'params': 'EghjaGFubmVscw%3D%3D'})
            cids = set(x.get('channelId') for x in walk(j or {}, 'gridChannelRenderer'))
            cids |= set(x.get('channelId') for x in walk(j or {}, 'channelRenderer'))
            cids |= {x.get('contentId') for x in walk(j or {}, 'lockupViewModel') if 'CHANNEL' in str(x.get('contentType', ''))}
            found.add({'from': 'f:' + key, 'cids': sorted(c for c in cids if c and c != key), 'items': []})
        else:
            its = [i for i in related_items(net, key) if (i['age'] < 0 or i['age'] >= 9) and GD_NAME.search(i['t'])]
            found.add({'from': 'r:' + key, 'cids': sorted({i['cid'] for i in its if i['cid']}), 'items': its})

    run_pool(tasks, one, workers, 'discover')
    return len(tasks)


# ---------------------------------------------------------------- stage: avatars
def stage_avatars(net, workers):
    st = Store('chmeta')
    have = {r['cid'] for r in st.load()}
    av = known_avatars()
    accepted, _ = accept_all()
    need = sorted({r['cid'] for r in accepted.values()} - set(av) - have)
    log(f'avatars: {len(need)} channels still without a picture')

    def one(cid):
        j = net.post('browse', {'context': net.ctx(), 'browseId': cid})
        cm = (j or {}).get('metadata', {}).get('channelMetadataRenderer', {})
        st.add({'cid': cid, 'title': cm.get('title', ''),
                'av': norm_av(((cm.get('avatar') or {}).get('thumbnails') or [{}])[0].get('url', ''))})

    run_pool(need, one, workers, 'avatars')


def known_avatars():
    av = {}
    for r in Store('search').load():
        for it in r['items']:
            if it.get('cid') and it.get('av'):
                av.setdefault(it['cid'], it['av'])
    for r in Store('channels').load() + Store('chmeta').load():
        if r.get('av'):
            av[r['cid']] = r['av']
    return av


# ---------------------------------------------------------------- deciding and labelling
def accept_all():
    """Returns ({id: row}, {id: reason}) for every video that belongs in the archive."""
    old, _ = legacy()
    det = {r['id']: r for r in Store('details').load() if r.get('st') == 'OK'}
    rows = {}
    for vid, r in det.items():
        pub = to_pacific(r['pub'])
        if not pub or pub[:10] >= CAP or r['len'] <= 0:
            continue
        rows[vid] = dict(r, pub=pub)
    # channels that are mostly Geometry Dash (by title or channel name)
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows.values():
        per[r['cid']][1] += 1
        if GD_NAME.search(r['t']) or GD_NAME.search(r['ch']):
            per[r['cid']][0] += 1
    focus = {c for c, (s, n) in per.items() if s >= 3 and s / n >= 0.5}
    out, why = {}, {}
    for vid, r in rows.items():
        t = r['t']
        tags = ' '.join(r.get('kw') or [])
        reason = None
        if r['cid'] == ROBTOP:
            reason = 'robtop'
        elif GD_NAME.search(t):
            reason = 'title'
        elif GD_NAME.search(r['ch']):
            reason = 'channel'
        elif OTHER_GAMES.search(t) or r['pub'][:10] < GD_OUT:
            reason = None   # about another game, or uploaded before Geometry Dash existed (e.g. a song later used in it)
        elif GD_NAME.search(tags) or r.get('dgd'):
            if GD_NAME.search(r.get('d', '')[:150]):
                reason = 'desc'
            elif DISTINCT.search(t):
                reason = 'tags+name'
            elif GENERIC.search(t):
                reason = 'tags+term'
        elif r['cid'] in focus and DISTINCT.search(t):
            reason = 'channel+name'
        if vid in old:
            reason = reason or 'legacy'
        elif r['views'] < MIN_VIEWS:
            reason = None
        if reason:
            out[vid] = r
            why[vid] = reason
    for vid, r in old.items():       # original list: keep even if YouTube did not answer this time
        if vid not in out and r['pub'][:10] < CAP:
            out[vid] = dict(r, kw=[], d='')
            why[vid] = 'legacy'
    return out, why


def categorize(t, cid):
    s = t.lower()
    if cid == ROBTOP:
        return 'official'
    if re.search(r'tutorial|how to|\bguide\b|\btop\s?\d+|\bvs\.?\b|comparison|speed ?run|\bsecrets?\b|\btips\b'
                 r'|\btricks?\b|ranking|tier list|\blist\b|explained|\bfacts\b|theory\b(?! of everything)', s):
        return 'guides'
    if re.search(r'animat|reaction|\breacts?\b|\brage\b|funny|\bmusic\b|\bsong\b|remix|glitch|parody|\bmemes?\b'
                 r'|troll|fan ?made|piano|\bcover\b|\bsfm\b|lyrics?|\bskit\b|comedy|\bprank|\bbloopers?\b', s):
        return 'community'
    if (OFFICIAL_RE.search(t) and re.search(r'100\s?%|coins?|level \d+|complete|all levels|official', s)) \
            or re.search(r'\ball (?:main |official )?levels\b|\bmain levels?\b|\bofficial levels?\b', s):
        return 'levels'
    if re.search(r'\bdemons?\b|verif|extreme|insane|\bxl\b|\bnerf|\bbuff|impossible|hardest', s) or DEMON_NAMES_RE.search(t):
        return 'demons'
    if re.search(r'collab|layout|preview|showcase|\bmy (?:new )?level|\bby\s+\w|creator|\bdeco|\bnew level|\bremake'
                 r'|\brated\b|\bfeatured\b|\bid\s*[:#]?\s*\d{5,}', s):
        return 'creators'
    if OFFICIAL_RE.search(t):
        return 'levels'
    return 'more'


QUOTED = [r'"([^"]{2,40})"', r'“([^”]{2,40})”', r'«([^»]{2,40})»', r"''([^']{2,40})''", r'„([^“”]{2,40})[“”]',
          r'「([^」]{2,40})」']


def make_label(t):
    for p in QUOTED:
        m = re.search(p, t)
        if m and not GD_NAME.search(m.group(1)) and re.search(r'\w', m.group(1)):
            return trim(m.group(1))
    for name in LEVEL_NAMES:
        if len(name) > 6 and re.search(_words([name]), t, re.I):
            return name.replace("'?", "'")
    s = re.sub(r'[\[(\{][^\])\}]*[\])\}]', ' ', t)
    s = re.sub(r'#\S+', ' ', s)
    s = re.sub(r'\b100\s?%|\ball coins\b|\b\d coins\b', ' ', s, flags=re.I)
    segs = []
    for seg in re.split(r'\s[-–—|:~]+\s|\|', s):
        clean = re.sub(r'\s+', ' ', GD_NAME.sub(' ', seg)).strip(' -–—|:~!.,')
        if len(re.findall(r'\w', clean)) >= 2:
            segs.append((clean, bool(GD_NAME.search(seg))))
    if len(segs) > 1 and segs[0][1]:   # "Geometry Dash Animation - Dual Portal": the part after the game name
        return trim(segs[1][0])
    return trim(segs[0][0]) if segs else 'Geometry Dash'


def trim(s, n=28):
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(' ', 1)[0]
    return cut if len(cut) >= 8 else s[:n]


# ---------------------------------------------------------------- stage: build
def stage_build():
    rows, why = accept_all()
    old, old_ch = legacy()
    av = known_avatars()
    names = {}
    for r in sorted(rows.values(), key=lambda r: r['pub']):
        if r.get('ch'):
            names[r['cid']] = r['ch']
    for cid, c in old_ch.items():
        names.setdefault(cid, c[1])
    for r in Store('channels').load() + Store('chmeta').load():
        if r.get('title') and r['cid'] in names and not names[r['cid']]:
            names[r['cid']] = r['title']
    order = sorted(rows.values(), key=lambda r: (-r['views'], r['id']))
    cidx, chans, v = {}, [], []
    for r in order:
        if r['cid'] not in cidx:
            cidx[r['cid']] = len(chans)
            chans.append([r['cid'], names.get(r['cid']) or r['cid'], av.get(r['cid'], '')])
        o = old.get(r['id'])
        cat = o['cat'] if o else categorize(r['t'], r['cid'])
        lab = o['lab'] if o else make_label(r['t'])
        v.append([r['id'], r['t'], cidx[r['cid']], int(r['len']), int(r['views']), r['pub'], cat, lab])
    out = {'c': chans, 'v': v}
    with open(DATA, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(CACHE, 'reasons.json'), 'w', encoding='utf-8') as f:
        json.dump(why, f, ensure_ascii=False, indent=0)
    tiers = collections.Counter(why[r[0]] for r in v)
    log(f'build: wrote {len(v)} videos from {len(chans)} channels '
        f'({os.path.getsize(DATA) / 1e6:.1f} MB); {sum(1 for c in chans if c[2])} channels have a picture')
    log('  reasons: ' + ', '.join(f'{k} {n}' for k, n in tiers.most_common()))


# ---------------------------------------------------------------- stage: audit
def stage_audit(net, sample):
    with open(DATA, encoding='utf-8') as f:
        d = json.load(f)
    why = {}
    p = os.path.join(CACHE, 'reasons.json')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            why = json.load(f)
    bad = []
    ids = set()
    for r in d['v']:
        vid, t, ci, ln, views, pub, cat, lab = r
        if vid in ids:
            bad.append(f'duplicate id {vid}')
        ids.add(vid)
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d-0[78]:00', pub):
            bad.append(f'{vid}: odd date {pub}')
        elif pub[:10] >= CAP:
            bad.append(f'{vid}: uploaded {pub}, on or after the cutoff')
        elif to_pacific(pub) != pub:
            bad.append(f'{vid}: offset does not match US Pacific daylight rules: {pub}')
        if not (0 <= ci < len(d['c'])):
            bad.append(f'{vid}: bad channel index')
        if why.get(vid) != 'legacy' and views < MIN_VIEWS:
            bad.append(f'{vid}: only {views} views')
        if ln <= 0:
            bad.append(f'{vid}: length {ln}')
        if cat not in CATS:
            bad.append(f'{vid}: category {cat}')
        if not why.get(vid):
            bad.append(f'{vid}: no recorded reason it is Geometry Dash')
    for c in d['c']:
        if c[2] and not re.match(r'https://yt3\.(?:ggpht|googleusercontent)\.com/', c[2]):
            bad.append(f'channel {c[0]}: odd picture URL')
    era = lambda pub: next((e for e, s in reversed(ERAS) if pub[:10] >= s), 'pre')
    log(f'audit: {len(d["v"])} videos, {len(d["c"])} channels, {len(bad)} problems')
    log('  per update: ' + ', '.join(f'{k} {n}' for k, n in sorted(collections.Counter(era(r[5]) for r in d['v']).items())))
    log('  per year: ' + ', '.join(f'{k} {n}' for k, n in sorted(collections.Counter(r[5][:4] for r in d['v']).items())))
    log('  per shelf: ' + ', '.join(f'{k} {n}' for k, n in collections.Counter(r[6] for r in d['v']).most_common()))
    log('  per reason: ' + ', '.join(f'{k} {n}' for k, n in collections.Counter(why.get(r[0], '?') for r in d['v']).most_common()))
    rnd = random.Random(16)
    weak = [r for r in d['v'] if why.get(r[0]) in ('tags+name', 'tags+term', 'desc', 'channel+name', 'legacy')
            and not GD_NAME.search(r[1])]
    print('\n--- sample of videos without "Geometry Dash" in the title (check these are really GD) ---')
    for r in rnd.sample(weak, min(sample, len(weak))):
        print(f'  [{why.get(r[0])}] {r[1]}  —  {d["c"][r[2]][1]}  ({r[5][:10]}, https://youtu.be/{r[0]})')
    print('\n--- boundary check: newest videos and first/last day of each update ---')
    newest = sorted(d['v'], key=lambda r: r[5], reverse=True)[:5]
    for r in newest:
        print(f'  newest  {r[5]}  {r[1][:70]}')
    for e, s in ERAS:
        day0 = s
        prev = (dt.date.fromisoformat(s) - dt.timedelta(days=1)).isoformat()
        a = [r for r in d['v'] if r[5][:10] == prev][:1]
        b = [r for r in d['v'] if r[5][:10] == day0][:1]
        for r in a:
            print(f'  {era(r[5]):>4} (day before {e})  {r[5]}  {r[1][:60]}')
        for r in b:
            print(f'  {era(r[5]):>4} (first day)     {r[5]}  {r[1][:60]}')
    if net and sample:
        print('\n--- re-reading 30 random videos from YouTube ---')
        changed = 0
        for r in rnd.sample(d['v'], min(30, len(d['v']))):
            got = fetch_player(net, r[0])
            if got.get('st') == 'OK' and to_pacific(got['pub']) != r[5]:
                changed += 1
                bad.append(f'{r[0]}: date now reads {got["pub"]}, data.json has {r[5]}')
        print(f'  {changed} of 30 differ')
    if bad:
        print('\nPROBLEMS:')
        for b in bad[:200]:
            print('  ' + b)
        return 1
    print('\naudit passed')
    return 0


# ---------------------------------------------------------------- main
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['search', 'details', 'channels', 'discover', 'grow', 'avatars', 'build', 'audit', 'all'])
    ap.add_argument('--extended', action='store_true', help='search: also run extra queries on busy days')
    ap.add_argument('--busy', type=int, default=30, help='search: unique videos from base queries that make a day busy')
    ap.add_argument('--search-rate', type=float, default=0.8, help='search: requests per second (YouTube blocks fast searching)')
    ap.add_argument('--min-strong', type=int, default=2, help='channels: GD-titled videos needed to list a channel')
    ap.add_argument('--related', type=int, default=1, help='discover: related-video lists read per GD channel')
    ap.add_argument('--rounds', type=int, default=4, help='grow: channels -> details -> discover rounds at most')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--rate', type=float, default=4.0, help='requests per second for everything but search')
    ap.add_argument('--sample', type=int, default=80, help='audit: titles to print for a manual check')
    a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    net = Net(a.rate)
    if a.stage not in ('build',) and not (a.stage == 'audit' and not a.sample):
        net.init_version()
    if a.stage in ('search', 'all'):
        snet = Net(a.search_rate, jitter=True)
        snet.version = net.version
        stage_search(snet, 1, a.extended or a.stage == 'all', a.busy)
        net.stats.update(snet.stats)
    if a.stage == 'details':
        stage_details(net, a.workers)
    if a.stage == 'channels':
        stage_channels(net, a.workers, a.min_strong)
    if a.stage == 'discover':
        stage_discover(net, a.workers, a.related)
    if a.stage in ('grow', 'all'):
        stage_details(net, a.workers)
        for rnd in range(1, a.rounds + 1):
            log(f'grow: round {rnd}')
            new_ch = stage_channels(net, a.workers, a.min_strong)
            stage_details(net, a.workers)
            new_lists = stage_discover(net, a.workers, a.related)
            if not new_ch and not new_lists:
                break
        stage_channels(net, a.workers, a.min_strong)
        stage_details(net, a.workers)
    if a.stage in ('avatars', 'all'):
        stage_avatars(net, a.workers)
    if a.stage in ('build', 'all'):
        stage_build()
    if a.stage in ('audit', 'all'):
        sys.exit(stage_audit(net, a.sample))
    log(f'done; {net.stats["req"]} requests, {net.stats["throttle"]} pauses')


if __name__ == '__main__':
    main()
