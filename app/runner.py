#!/usr/bin/env python3
"""Galios Pikas agentų paleidiklis: grafikas + rankiniai paleidimai."""
import csv, io, json, os, subprocess, sys, threading, time, traceback, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")
import db

try:
    TZ = ZoneInfo("Europe/Vilnius")
except Exception:
    from datetime import timedelta, timezone
    TZ = timezone(timedelta(hours=2))
TRIG = os.path.join(db.DATA, "triggers")
STATE = os.path.join(db.DATA, "runner_state.json")
GMAPS = os.environ.get("GMAPS_URL", "http://gmaps:8080")

# (agentas, savaitės dienos 0=pirm, valanda, minutė)
SCHEDULE = [
    ("maps", range(7), 3, 10),
    ("zvalgas", range(7), 7, 40),
    ("zvalgas", range(7), 17, 40),
    # ("tikrintojas", range(7), 5, 30),  # išjungta: rekvizitai.lt blokuoja automatinį skaitymą
    ("socialai", range(7), 12, 10),
    ("rasytojas", range(5), 8, 30),
    ("analitikas", [0], 7, 15),
    ("mokytojas", range(7), 22, 30),
]

MAPS_BATCHES = [
    ["autoservisas Vilnius", "automobilių remontas Vilnius"],
    ["autoservisas Naujininkai", "autoservisas Naujoji Vilnia", "autoservisas Rasos"],
    ["autoservisas Žirmūnai", "autoservisas Antakalnis", "autoservisas Baltupiai"],
    ["autoservisas Šeškinė", "autoservisas Fabijoniškės", "autoservisas Pašilaičiai"],
    ["autoservisas Pilaitė", "autoservisas Justiniškės", "autoservisas Karoliniškės"],
    ["autoservisas Lazdynai", "autoservisas Grigiškės", "autoservisas Vilkpėdė"],
    ["autoservisas Naujamiestis Vilnius", "autoservisas Šnipiškės", "autoservisas Žvėrynas"],
    ["dyzelinių variklių remontas Vilnius", "automobilių elektrikas Vilnius", "pavarų dėžių remontas Vilnius"],
    ["sunkvežimių servisas Vilnius", "transporto įmonė Vilnius", "krovinių pervežimas Vilnius"],
    ["motociklų servisas Vilnius", "mikroautobusų remontas Vilnius", "automobilių diagnostika Vilnius"],
    ["naudotų automobilių aikštelė Vilnius", "naudoti automobiliai Vilnius"],
    ["autoservisas Vilniaus rajonas", "autoservisas Nemenčinė", "autoservisas Pabradė"],
]


# Netinkami (nenaudoja Galios Piko paslaugų) arba konkurentai
EXCLUDE = ("detal", "dalys", "dalių", "parduotuv", "padang", "ratų", "ratai", "plovykl", "duslintuv", "stikl",
           "akumuliator", "tepal", "kėbul", "dažym", "chip", "tuning", "galios didinimas", "autodalys",
           "auto parts", "parts", "shop", "store", "kondicion", "salono valym", "evakuat", "techninė apžiūra",
           # oficialūs atstovai, automobilių pardavėjai, dideli tinklai (markių pavadinimų NEFILTRUOJAM –
           # mažas „BMW servisas“ yra geras klientas)
           "atstov", "oficial", "dealer", "naujų automobilių", "naujų auto", "autosalon", "salonas",
           "naujų automobilių pardav", "new cars",
           "moller", "möller", "krasta", "inchcape", "silberauto", "vaitėnas", "autobrava", "tokvila",
           "unimodus", "rolinga", "amber auto", "lancasterauto", "autokurtas", "renault retail")


def is_bad(name, cat, addr):
    low = f"{name} {cat}".lower()
    learned = [w for w in db.read_text(db.EXCLUDE_PATH).splitlines() if w.strip()]
    return any(w in low for w in EXCLUDE) or any(w.strip() in low for w in learned) or ("vilni" not in (addr or "").lower())


def cleanup():
    c = db.conn()
    n = 0
    for r in c.execute("SELECT id,name,category,address FROM leads WHERE kind='b2b' AND source='google_maps' AND status='naujas'").fetchall():
        if is_bad(r["name"], r["category"], r["address"]):
            c.execute("UPDATE leads SET status='atmestas' WHERE id=?", (r["id"],))
            n += 1
    c.commit()
    # vienkartinis: grąžinti automatiškai išmestus, kurie pagal naujas taisykles tinka
    # (updated_at == created_at reiškia, kad ranka nebuvo liesti)
    st = load_state()
    if not st.get("restore_v2"):
        back = 0
        for r in c.execute("SELECT id,name,category,address FROM leads WHERE kind='b2b' AND source='google_maps' AND status='atmestas' AND updated_at=created_at").fetchall():
            if not is_bad(r["name"], r["category"], r["address"]):
                c.execute("UPDATE leads SET status='naujas' WHERE id=?", (r["id"],)); back += 1
        c.commit()
        st["restore_v2"] = True; save_state(st)
        print(f"Grąžinta tinkamų: {back}", flush=True)
    print(f"Išvalyta netinkamų: {n}", flush=True)


LLM_AGENTS = {
    "zvalgas": "Tu esi ŽVALGAS. Atlik užduotį pagal /app/agents/zvalgas.md. Dirbk savarankiškai iki galo.",
    "rasytojas": "Tu esi PASIŪLYMŲ RAŠYTOJAS. Atlik užduotį pagal /app/agents/rasytojas.md. Dirbk savarankiškai iki galo.",
    "socialai": "Tu esi SOCIALINIŲ TINKLŲ ŽVALGAS. Atlik užduotį pagal /app/agents/socialai.md. Dirbk savarankiškai iki galo.",
    "tikrintojas": "Tu esi TIKRINTOJAS. Atlik užduotį pagal /app/agents/tikrintojas.md. Dirbk savarankiškai iki galo.",
    "mokytojas": "Tu esi MOKYTOJAS. Atlik užduotį pagal /app/agents/mokytojas.md.",
    "analitikas": "Tu esi ANALITIKAS. Atlik užduotį pagal /app/agents/analitikas.md.",
}


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(s):
    json.dump(s, open(STATE, "w"))


def run_claude(agent):
    token = db.load_settings().get("claude_token", "").strip()
    if not token:
        return "praleista", "Nėra Claude prisijungimo rakto. Įvesk jį dashboard'e → Nustatymai."
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=token, GP_DATA=db.DATA)
    env.pop("ANTHROPIC_API_KEY", None)
    work = f"/tmp/work_{agent}"
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.dirname(db.LESSONS_PATH), exist_ok=True)
    prompt = LLM_AGENTS[agent] + f" Prieš pradėdamas perskaityk {db.LESSONS_PATH} (jei yra) – tai pamokos iš ankstesnių rezultatų ir Karolio veiksmų; jų būtinai laikykis."
    lessons_dir = os.path.dirname(db.LESSONS_PATH)
    # Agentai mato tik savo instrukcijas, pamokas ir /tmp darbo failus – ne nustatymus su raktais.
    cmd = ["claude", "-p", prompt, "--add-dir", "/app", "--add-dir", lessons_dir, "--max-turns", "120",
           "--allowedTools", "WebSearch", "WebFetch",
           "Read(//app/**)", f"Read(/{lessons_dir}/**)", "Read(//tmp/**)", "Glob(//app/**)", "Grep(//app/**)",
           "Write(//tmp/**)", "Edit(//tmp/**)",
           "Bash(python3 /app/db.py:*)", "Bash(python3 /app/db.py *)",
           "--disallowedTools", f"Read(/{db.DATA}/*.json)", f"Read(/{db.DATA}/*.db*)"]
    try:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=45 * 60)
        out = (p.stdout or "") + ("\n" + p.stderr if p.returncode else "")
        return ("ok" if p.returncode == 0 else "klaida"), out.strip()
    except subprocess.TimeoutExpired:
        return "klaida", "Viršytas laikas (45 min)."


SOCIAL_QUERIES = [
    "DPF klaida", "EGR klaida", "AdBlue klaida", "P2002 klaida", "P20EE", "chiptuning Vilnius",
    "galios didinimas Vilnius", "kas išprogramuotų", "ECU remontas", "neužsiveda imobilaizeris",
    "automobilis avariniame režime", "sunkvežimis AdBlue klaida", "karštas sunkiai užsiveda",
    "sklendžių klaida", "variklio klaida Vilnius", "kompiuterinė diagnostika Vilnius",
]
APIFY = "https://api.apify.com/v2"


def apify_items(token, actor, run_input, items):
    # mokama pagal rezultatą (~0,005 $ už įrašą); maxItems ir maxTotalChargeUsd – griežtos ribos
    cap = max(0.5, round(items * 0.005 * 1.3, 2))
    q = urllib.parse.urlencode({"maxItems": items, "maxTotalChargeUsd": f"{cap:.2f}", "timeout": 280})
    req = urllib.request.Request(f"{APIFY}/acts/{actor}/run-sync-get-dataset-items?{q}", method="POST",
                                 data=json.dumps(run_input).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=320) as r:
        data = json.loads(r.read() or b"[]")
    return data if isinstance(data, list) else []


def _trim(o, n=600):
    if isinstance(o, dict):
        return {k: _trim(v, n) for k, v in o.items() if v not in (None, "", [], {}) and not str(k).lower().startswith(("image", "thumb", "video", "media", "attach"))}
    if isinstance(o, list):
        return [_trim(v, n) for v in o[:15]]
    if isinstance(o, str):
        return o[:n]
    return o


def run_social(state):
    s = db.load_settings()
    token = s.get("apify_token", "").strip()
    if not token:
        return "praleista", "Nėra Apify rakto. Įvesk jį dashboard'e → Nustatymai."
    per = max(5, min(100, int(s.get("apify_posts", 15) or 15)))
    nq = max(1, min(8, int(s.get("apify_queries", 3) or 3)))
    i = state.get("social_q", 0)
    queries = [SOCIAL_QUERIES[(i + k) % len(SOCIAL_QUERIES)] for k in range(nq)]
    state["social_q"] = i + nq
    groups = [g.strip() for g in s.get("fb_groups", "").splitlines() if g.strip().startswith("http")]
    gi = state.get("social_g", 0)
    pick = [groups[(gi + k) % len(groups)] for k in range(min(2, len(groups)))] if groups else []
    state["social_g"] = gi + len(pick)
    save_state(state)
    posts, log, raw = [], [], []
    for q in queries:
        try:
            got = apify_items(token, "scraper_one~facebook-posts-search", {"query": q, "resultsCount": per, "searchType": "latest"}, per)
            raw += got
            posts += [{"paieska": q, "irasas": _trim(x)} for x in got]
            log.append(f"„{q}“: {len(got)}")
        except Exception as ex:
            log.append(f"„{q}“: klaida {ex}")
    for g in pick:
        try:
            got = apify_items(token, "apify~facebook-groups-scraper", {"startUrls": [{"url": g}], "resultsLimit": per}, per)
            raw += got
            posts += [{"grupe": g, "irasas": _trim(x)} for x in got]
            log.append(f"grupė {g}: {len(got)}")
        except Exception as ex:
            log.append(f"grupė {g}: klaida {ex}")
    # Komentarai: populiariausių (daugiausiai komentuotų) įrašų komentarai – ten dažnai rašo „aš irgi turiu tą klaidą“
    ncom = max(0, min(15, int(s.get("apify_comment_posts", 5) or 0)))
    if ncom and raw:
        def cnt(x):
            for k in ("commentsCount", "commentCount", "comments_count", "comments"):
                v = x.get(k)
                if isinstance(v, (int, float)): return v
                if isinstance(v, str) and v.isdigit(): return int(v)
                if isinstance(v, list): return len(v)
            return 0
        def link(x):
            for k in ("url", "postUrl", "facebookUrl", "link", "topLevelUrl"):
                v = x.get(k)
                if isinstance(v, str) and v.startswith("http"): return v
            return ""
        top = [link(x) for x in sorted(raw, key=cnt, reverse=True) if cnt(x) > 0 and link(x)]
        top = list(dict.fromkeys(top))[:ncom]
        if top:
            try:
                got = apify_items(token, "apify~facebook-comments-scraper",
                                  {"startUrls": [{"url": u} for u in top], "resultsLimit": 20}, 20 * len(top))
                posts += [{"komentaras": True, "irasas": _trim(x)} for x in got]
                log.append(f"komentarai iš {len(top)} įrašų: {len(got)}")
            except Exception as ex:
                log.append(f"komentarai: klaida {ex}")
    work = "/tmp/work_socialai"
    os.makedirs(work, exist_ok=True)
    with open(f"{work}/posts.json", "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)
    head = f"Facebook (Apify): {', '.join(log)}. Iš viso įrašų: {len(posts)}."
    if not posts:
        if any("401" in x for x in log):
            return "klaida", head + "\n\nApify raktas neteisingas (401). Nustatymuose įklijuok „Personal API token“ (prasideda apify_api_)."
        if any("klaida" in x for x in log):
            return "klaida", head
        return "ok", head + " Nėra ką analizuoti."
    st, out = run_claude("socialai")
    return st, head + "\n\n" + out


def http_json(method, url, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw


def run_maps(state):
    i = state.get("maps_batch", 0) % len(MAPS_BATCHES)
    kws = MAPS_BATCHES[i]
    state["maps_batch"] = i + 1
    save_state(state)
    job = json.loads(http_json("POST", f"{GMAPS}/api/v1/jobs", {
        "name": f"gp-{datetime.now(TZ):%Y%m%d-%H%M}", "keywords": kws, "lang": "lt",
        "zoom": 14, "depth": 5, "email": True, "max_time": 1500, "radius": 15000,
    }))
    jid = job.get("id") or job.get("ID")
    deadline = time.time() + 40 * 60
    status = ""
    while time.time() < deadline:
        time.sleep(30)
        j = json.loads(http_json("GET", f"{GMAPS}/api/v1/jobs/{jid}"))
        status = (j.get("Status") or j.get("status") or "").lower()
        if status in ("ok", "failed"):
            break
    if status != "ok":
        return "klaida", f"Google Maps užduotis nebaigta (statusas: {status or 'nežinomas'}). Raktažodžiai: {', '.join(kws)}"
    raw = http_json("GET", f"{GMAPS}/api/v1/jobs/{jid}/download", timeout=120).decode("utf-8", "replace")
    c = db.conn()
    new = seen = 0
    for row in csv.DictReader(io.StringIO(raw)):
        g = lambda *ks: next((row[k] for k in ks if row.get(k)), "")
        name = g("title", "name")
        if not name:
            continue
        cat = g("category", "categories")
        addr = g("address", "complete_address")
        if is_bad(name, cat, addr):
            continue  # netinkami / ne Vilnius / konkurentai
        emails = g("emails", "email").replace("[", "").replace("]", "").replace('"', "")
        email = emails.split(",")[0].strip() if emails else ""
        rid = db.add_lead(c, {
            "kind": "b2b", "source": "google_maps", "name": name, "category": cat,
            "city": "Vilnius", "address": addr, "phone": g("phone"), "email": email,
            "website": g("website", "web_site"), "url": g("link", "url", "reviews_link"),
            "rating": g("review_rating", "rating"), "note": "Paieška: " + ", ".join(kws),
        })
        seen += 1
        new += 1 if rid else 0
    return "ok", f"Raktažodžiai: {', '.join(kws)}. Rasta {seen} įmonių, naujų įrašyta: {new}."


def execute(agent, state, rid=None):
    c = db.conn()
    if rid:
        c.execute("UPDATE runs SET status='vyksta', started_at=? WHERE id=?", (db.now(), rid)); c.commit()
    else:
        rid = db.log_run_start(c, agent)
    try:
        if agent == "maps":
            status, summary = run_maps(state)
        elif agent == "socialai":
            status, summary = run_social(state)
        else:
            status, summary = run_claude(agent)
    except Exception as e:
        status, summary = "klaida", f"{e}\n{traceback.format_exc()[-1500:]}"
    db.log_run_end(db.conn(), rid, status, summary)
    print(f"[{datetime.now(TZ):%F %T}] {agent}: {status}", flush=True)


MAPS_LOCK = threading.Lock()


def run_maps_bg(rid):
    def go():
        with MAPS_LOCK:
            execute("maps", load_state(), rid)
    threading.Thread(target=go, daemon=True).start()


def main():
    os.makedirs(TRIG, exist_ok=True)
    print("Runner paleistas", flush=True)
    cleanup()
    c = db.conn()
    c.execute("UPDATE runs SET status='nutraukta', finished_at=? WHERE status='vyksta'", (db.now(),)); c.commit()
    while True:
        state = load_state()
        queue = []  # (agent, rid, trigger_file)
        for f in sorted(os.listdir(TRIG)):
            parts = f.split(".")
            agent = parts[0]
            rid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() and len(parts[1]) < 9 else None
            if agent == "maps" or agent in LLM_AGENTS or agent == "socialai":
                queue.append((agent, rid, os.path.join(TRIG, f)))
            else:
                os.remove(os.path.join(TRIG, f))
        n = datetime.now(TZ)
        for agent, days, h, m in SCHEDULE:
            key = f"{agent}@{h:02d}{m:02d}"
            today = n.strftime("%F")
            if n.weekday() in days and (n.hour, n.minute) >= (h, m) and state.get(key) != today:
                # tik jei vėluojam ne daugiau nei 3 val. (kad po perkrovimo nepaleistų visko iš karto)
                if (n.hour * 60 + n.minute) - (h * 60 + m) <= 180:
                    queue.append((agent, None, None))
                state[key] = today
        save_state(state)
        done = set()
        for agent, rid, tf in queue:
            if agent in done:
                if rid:
                    c = db.conn(); c.execute("UPDATE runs SET status='praleista', finished_at=?, summary='Jau buvo paleista' WHERE id=?", (db.now(), rid)); c.commit()
                if tf and os.path.exists(tf): os.remove(tf)
                continue
            done.add(agent)
            if tf and os.path.exists(tf):
                os.remove(tf)
            if agent == "maps":
                if MAPS_LOCK.locked():
                    if rid:
                        c = db.conn(); c.execute("UPDATE runs SET status='praleista', finished_at=?, summary='Google Maps paieška jau vyksta' WHERE id=?", (db.now(), rid)); c.commit()
                    continue
                run_maps_bg(rid)
            else:
                execute(agent, load_state(), rid)
        time.sleep(15)


if __name__ == "__main__":
    main()
