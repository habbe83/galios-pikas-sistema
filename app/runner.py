#!/usr/bin/env python3
"""Galios Pikas agentų paleidiklis: grafikas + rankiniai paleidimai."""
import csv, io, json, os, subprocess, sys, time, traceback, urllib.request
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
    ("tikrintojas", range(7), 5, 30),
    ("rasytojas", range(5), 8, 30),
    ("analitikas", [0], 7, 15),
]

MAPS_BATCHES = [
    ["autoservisas Vilnius", "automobilių remontas Vilnius"],
    ["sunkvežimių servisas Vilnius", "transporto įmonė Vilnius", "logistikos įmonė Vilnius"],
    ["automobilių prekyba Vilnius", "naudotų automobilių aikštelė Vilnius"],
    ["motociklų servisas Vilnius", "autonuoma Vilnius", "taksi įmonė Vilnius"],
    ["autoservisas Vilniaus rajonas", "krovinių pervežimas Vilnius"],
]

# Netinkami (nenaudoja Galios Piko paslaugų) arba konkurentai
EXCLUDE = ("detal", "dalys", "dalių", "parduotuv", "padang", "ratų", "ratai", "plovykl", "duslintuv", "stikl",
           "akumuliator", "tepal", "kėbul", "dažym", "chip", "tuning", "galios didinimas", "autodalys",
           "auto parts", "parts", "shop", "store", "kondicion", "salono valym", "evakuat", "techninė apžiūra")


def is_bad(name, cat, addr):
    low = f"{name} {cat}".lower()
    return any(w in low for w in EXCLUDE) or ("vilni" not in (addr or "").lower())


def cleanup():
    c = db.conn()
    n = 0
    for r in c.execute("SELECT id,name,category,address FROM leads WHERE kind='b2b' AND source='google_maps' AND status='naujas'").fetchall():
        if is_bad(r["name"], r["category"], r["address"]):
            c.execute("UPDATE leads SET status='atmestas' WHERE id=?", (r["id"],))
            n += 1
    c.commit()
    print(f"Išvalyta netinkamų: {n}", flush=True)


LLM_AGENTS = {
    "zvalgas": "Tu esi ŽVALGAS. Atlik užduotį pagal /app/agents/zvalgas.md. Dirbk savarankiškai iki galo.",
    "rasytojas": "Tu esi PASIŪLYMŲ RAŠYTOJAS. Atlik užduotį pagal /app/agents/rasytojas.md. Dirbk savarankiškai iki galo.",
    "tikrintojas": "Tu esi TIKRINTOJAS. Atlik užduotį pagal /app/agents/tikrintojas.md. Dirbk savarankiškai iki galo.",
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
    cmd = ["claude", "-p", LLM_AGENTS[agent], "--add-dir", "/app", "--max-turns", "120",
           "--allowedTools", "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob", "Grep",
           "Bash(python3 /app/db.py:*)", "Bash(python3 /app/db.py *)"]
    try:
        p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=45 * 60)
        out = (p.stdout or "") + ("\n" + p.stderr if p.returncode else "")
        return ("ok" if p.returncode == 0 else "klaida"), out.strip()
    except subprocess.TimeoutExpired:
        return "klaida", "Viršytas laikas (45 min)."


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


def execute(agent, state):
    c = db.conn()
    rid = db.log_run_start(c, agent)
    try:
        if agent == "maps":
            status, summary = run_maps(state)
        else:
            status, summary = run_claude(agent)
    except Exception as e:
        status, summary = "klaida", f"{e}\n{traceback.format_exc()[-1500:]}"
    db.log_run_end(db.conn(), rid, status, summary)
    print(f"[{datetime.now(TZ):%F %T}] {agent}: {status}", flush=True)


def main():
    os.makedirs(TRIG, exist_ok=True)
    print("Runner paleistas", flush=True)
    cleanup()
    while True:
        state = load_state()
        queue = []
        for f in sorted(os.listdir(TRIG)):
            agent = f.split(".")[0]
            os.remove(os.path.join(TRIG, f))
            if agent == "maps" or agent in LLM_AGENTS:
                queue.append(agent)
        n = datetime.now(TZ)
        for agent, days, h, m in SCHEDULE:
            key = f"{agent}@{h:02d}{m:02d}"
            today = n.strftime("%F")
            if n.weekday() in days and (n.hour, n.minute) >= (h, m) and state.get(key) != today:
                # tik jei vėluojam ne daugiau nei 3 val. (kad po perkrovimo nepaleistų visko iš karto)
                if (n.hour * 60 + n.minute) - (h * 60 + m) <= 180:
                    queue.append(agent)
                state[key] = today
        save_state(state)
        for agent in dict.fromkeys(queue):
            execute(agent, load_state())
        time.sleep(30)


if __name__ == "__main__":
    main()
