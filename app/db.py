#!/usr/bin/env python3
"""Galios Pikas - bendra duomenų bazė + CLI agentams.

Naudojimas agentams:
  python3 /app/db.py leads [--kind b2b|karstas] [--status naujas] [--limit 20]
  python3 /app/db.py lead <id>
  python3 /app/db.py add-lead --kind karstas --source paslaugos.lt --name "..." --url "..." --note "..." [--city ...] [--phone ...] [--email ...] [--category ...]
  python3 /app/db.py add-draft --lead <id> --subject "..." --body-file /tmp/x.txt
  python3 /app/db.py set-status <lead_id> <status>
  python3 /app/db.py add-report --title "..." --body-file /tmp/r.md
  python3 /app/db.py stats
"""
import argparse, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone

DATA = os.environ.get("GP_DATA", "/data")
DB_PATH = os.path.join(DATA, "galiospikas.db")
SETTINGS_PATH = os.path.join(DATA, "settings.json")

ENRICH_COLS = ["company_code", "employees", "vehicles", "revenue", "director", "activity"]
LEAD_STATUSES = ["naujas", "laiskas_paruostas", "issiustas", "atsake", "klientas", "atmestas"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,            -- b2b | karstas
  source TEXT, name TEXT, category TEXT, city TEXT, address TEXT,
  phone TEXT, email TEXT, website TEXT, url TEXT, rating TEXT, note TEXT,
  status TEXT NOT NULL DEFAULT 'naujas',
  dedup TEXT UNIQUE,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER, subject TEXT, body TEXT,
  status TEXT NOT NULL DEFAULT 'laukia',   -- laukia | issiusta | atmesta | klaida
  error TEXT, created_at TEXT, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT, started_at TEXT, finished_at TEXT, status TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, body TEXT, created_at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def conn():
    os.makedirs(DATA, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    have = {r[1] for r in c.execute("PRAGMA table_info(leads)")}
    for col in ENRICH_COLS + ["enriched_at"]:
        if col not in have:
            c.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")
    return c


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s):
    os.makedirs(DATA, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SETTINGS_PATH)


def _norm(s):
    return re.sub(r"[^a-z0-9ąčęėįšųūž]", "", (s or "").lower())


def dedup_key(d):
    if d.get("url") and d.get("kind") == "karstas":
        return "u:" + d["url"].strip().lower()
    phone = re.sub(r"\D", "", d.get("phone") or "")[-8:]
    return "n:" + _norm(d.get("name")) + ":" + (phone or _norm(d.get("website")) or _norm(d.get("address")))


def add_lead(c, d):
    d = {k: (v.strip() if isinstance(v, str) else v) for k, v in d.items()}
    key = dedup_key(d)
    t = now()
    try:
        cur = c.execute(
            "INSERT INTO leads(kind,source,name,category,city,address,phone,email,website,url,rating,note,status,dedup,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'naujas',?,?,?)",
            (d.get("kind", "b2b"), d.get("source"), d.get("name"), d.get("category"), d.get("city"), d.get("address"),
             d.get("phone"), d.get("email"), d.get("website"), d.get("url"), d.get("rating"), d.get("note"), key, t, t))
        c.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # jau yra - papildom tuščius laukus
        row = c.execute("SELECT * FROM leads WHERE dedup=?", (key,)).fetchone()
        for f in ("email", "website", "phone", "note"):
            if d.get(f) and not row[f]:
                c.execute(f"UPDATE leads SET {f}=?, updated_at=? WHERE id=?", (d[f], t, row["id"]))
        c.commit()
        return None


def log_run_start(c, agent):
    cur = c.execute("INSERT INTO runs(agent,started_at,status) VALUES(?,?,'vyksta')", (agent, now()))
    c.commit()
    return cur.lastrowid


def log_run_end(c, rid, status, summary):
    c.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE id=?", (now(), status, (summary or "")[-4000:], rid))
    c.commit()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("leads"); a.add_argument("--kind"); a.add_argument("--status"); a.add_argument("--limit", type=int, default=20)
    a.add_argument("--need-contact", action="store_true", help="tik su el. paštu arba svetaine")
    a.add_argument("--not-enriched", action="store_true", help="dar netikrinti rekvizitai.lt")
    a = sp.add_parser("lead"); a.add_argument("id", type=int)
    a = sp.add_parser("add-lead")
    for f in ("kind", "source", "name", "category", "city", "address", "phone", "email", "website", "url", "rating", "note"):
        a.add_argument("--" + f)
    a = sp.add_parser("add-draft"); a.add_argument("--lead", type=int, required=True); a.add_argument("--subject", required=True); a.add_argument("--body-file", required=True)
    a = sp.add_parser("enrich"); a.add_argument("id", type=int)
    for f in ENRICH_COLS + ["email", "phone", "website"]:
        a.add_argument("--" + f.replace("_", "-"))
    a = sp.add_parser("set-status"); a.add_argument("id", type=int); a.add_argument("status", choices=LEAD_STATUSES)
    a = sp.add_parser("add-report"); a.add_argument("--title", required=True); a.add_argument("--body-file", required=True)
    sp.add_parser("stats")
    sp.add_parser("known-urls")
    args = p.parse_args()
    c = conn()

    if args.cmd == "leads":
        q, prm = "SELECT * FROM leads WHERE 1=1", []
        if args.kind: q += " AND kind=?"; prm.append(args.kind)
        if args.status: q += " AND status=?"; prm.append(args.status)
        if args.need_contact: q += " AND (IFNULL(email,'')<>'' OR IFNULL(website,'')<>'')"
        if args.not_enriched: q += " AND enriched_at IS NULL"
        q += " ORDER BY id DESC LIMIT ?"; prm.append(args.limit)
        print(json.dumps([dict(r) for r in c.execute(q, prm)], ensure_ascii=False, indent=1))
    elif args.cmd == "lead":
        r = c.execute("SELECT * FROM leads WHERE id=?", (args.id,)).fetchone()
        print(json.dumps(dict(r) if r else None, ensure_ascii=False, indent=1))
    elif args.cmd == "add-lead":
        d = {k: v for k, v in vars(args).items() if k != "cmd" and v}
        d.setdefault("kind", "karstas")
        rid = add_lead(c, d)
        print(f"OK id={rid}" if rid else "JAU YRA (praleista)")
    elif args.cmd == "add-draft":
        body = _read(args.body_file).strip()
        if not c.execute("SELECT 1 FROM leads WHERE id=?", (args.lead,)).fetchone():
            sys.exit("Nėra tokio lead")
        if c.execute("SELECT 1 FROM drafts WHERE lead_id=? AND status IN ('laukia','issiusta')", (args.lead,)).fetchone():
            print("JAU YRA laiškas šiam klientui (praleista)"); return
        c.execute("INSERT INTO drafts(lead_id,subject,body,status,created_at) VALUES(?,?,?,'laukia',?)", (args.lead, args.subject, body, now()))
        c.execute("UPDATE leads SET status='laiskas_paruostas', updated_at=? WHERE id=?", (now(), args.lead))
        c.commit(); print("OK")
    elif args.cmd == "enrich":
        sets, vals = ["enriched_at=?", "updated_at=?"], [now(), now()]
        for f in ENRICH_COLS:
            v = getattr(args, f)
            if v: sets.append(f"{f}=?"); vals.append(v.strip())
        for f in ("email", "phone", "website"):  # tik jei tušti
            v = getattr(args, f)
            if v: sets.append(f"{f}=COALESCE(NULLIF({f},''), ?)"); vals.append(v.strip())
        c.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=?", vals + [args.id]); c.commit(); print("OK")
    elif args.cmd == "set-status":
        c.execute("UPDATE leads SET status=?, updated_at=? WHERE id=?", (args.status, now(), args.id)); c.commit(); print("OK")
    elif args.cmd == "add-report":
        c.execute("INSERT INTO reports(title,body,created_at) VALUES(?,?,?)", (args.title, _read(args.body_file), now())); c.commit(); print("OK")
    elif args.cmd == "known-urls":
        for r in c.execute("SELECT url FROM leads WHERE kind='karstas' AND IFNULL(url,'')<>'' ORDER BY id DESC LIMIT 300"):
            print(r["url"])
    elif args.cmd == "stats":
        out = {
            "leads_viso": c.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
            "pagal_statusa": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM leads GROUP BY status")},
            "pagal_tipa": {r[0]: r[1] for r in c.execute("SELECT kind, COUNT(*) FROM leads GROUP BY kind")},
            "pagal_saltini": {r[0]: r[1] for r in c.execute("SELECT source, COUNT(*) FROM leads GROUP BY source")},
            "per_7d": c.execute("SELECT COUNT(*) FROM leads WHERE created_at >= date('now','-7 day')").fetchone()[0],
            "laiskai": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM drafts GROUP BY status")},
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
