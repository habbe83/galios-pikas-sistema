#!/usr/bin/env python3
"""Galios Pikas dashboard (be išorinių bibliotekų)."""
import hashlib, hmac, html, os, smtplib, ssl, sys, time, urllib.parse
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")
import db

PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SECRET = (os.environ.get("PANEL_SECRET") or PASSWORD or "x").encode()
TRIG = os.path.join(db.DATA, "triggers")
AGENTS = {"maps": "B2B medžiotojas (Google Maps)", "zvalgas": "Žvalgas (karšti klientai)",
          "tikrintojas": "Tikrintojas (rekvizitai.lt)", "socialai": "Socialinių tinklų žvalgas (Facebook)", "rasytojas": "Pasiūlymų rašytojas", "analitikas": "Analitikas", "mokytojas": "Mokytojas (mokosi iš rezultatų)"}
STATUS_LT = {"naujas": "Naujas", "laiskas_paruostas": "Laiškas paruoštas", "issiustas": "Išsiųsta",
             "atsake": "Atsakė", "klientas": "Klientas ✔", "atmestas": "🗑 Šiukšliadėžė"}
e = lambda s: html.escape(str(s if s is not None else ""))

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e8e8ea}
a{color:#ff7a1a;text-decoration:none}header{display:flex;gap:18px;align-items:center;padding:14px 22px;background:#16191f;border-bottom:1px solid #262a33;flex-wrap:wrap}
header b{font-size:18px;margin-right:12px}header a{color:#c9c9cf}header a.on{color:#ff7a1a}
main{padding:22px;max-width:1300px;margin:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
.card{background:#16191f;border:1px solid #262a33;border-radius:12px;padding:16px}.card .n{font-size:30px;font-weight:700}.card .l{color:#9a9aa3;font-size:13px}
table{width:100%;border-collapse:collapse;background:#16191f;border-radius:12px;overflow:hidden;font-size:14px}th,td{padding:9px 10px;border-bottom:1px solid #262a33;text-align:left;vertical-align:top}
th{color:#9a9aa3;font-weight:600;background:#1a1e25}tr:hover td{background:#1b1f27}
.btn{background:#ff7a1a;color:#111;border:0;border-radius:8px;padding:8px 14px;font-weight:600;cursor:pointer}.btn.g{background:#2a2f3a;color:#e8e8ea}.btn.r{background:#5a2328;color:#fff}
input,textarea,select{background:#0f1115;color:#e8e8ea;border:1px solid #333845;border-radius:8px;padding:8px;width:100%;font:inherit}
textarea{min-height:220px}.box{background:#16191f;border:1px solid #262a33;border-radius:12px;padding:16px;margin-bottom:16px}
.muted{color:#9a9aa3;font-size:13px}.pill{display:inline-block;padding:2px 8px;border-radius:99px;background:#262a33;font-size:12px}
.ok{color:#5fd38a}.bad{color:#ff6b6b}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}pre{white-space:pre-wrap;margin:0;font-size:13px}
h2{margin:6px 0 14px}form.inline{display:inline}
"""


def page(title, body, active=""):
    nav = "".join(f'<a class="{"on" if active == k else ""}" href="/{k}">{v}</a>' for k, v in
                  [("", "Apžvalga"), ("klientai", "Klientai"), ("laiskai", "Laiškai"), ("agentai", "Agentai"),
                   ("ataskaitos", "Ataskaitos"), ("pamokos", "Pamokos"), ("nustatymai", "Nustatymai")])
    return f"""<!doctype html><html lang="lt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Galios Pikas</title><style>{CSS}</style></head><body><header><b>⚡ Galios Pikas</b>{nav}
<span style="flex:1"></span><a href="/atsijungti">Atsijungti</a></header><main>{body}</main></body></html>"""


def sign(v):
    return hmac.new(SECRET, v.encode(), hashlib.sha256).hexdigest()


def send_mail(settings, to, subject, body):
    pw = settings.get("smtp_password", "")
    if not pw:
        raise RuntimeError("Nenustatytas el. pašto slaptažodis (Nustatymai).")
    sender = settings.get("smtp_user") or "info@galiospikas.lt"
    msg = EmailMessage()
    msg["From"] = formataddr(("Galios Pikas", sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="galiospikas.lt")
    msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=Atsisakyti>"
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(sender, pw)
        s.send_message(msg)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---------- pagalbinės ----------
    def authed(self):
        ck = self.headers.get("Cookie", "")
        for part in ck.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "gp":
                ts, _, sig = v.partition(".")
                if ts.isdigit() and hmac.compare_digest(sign(ts), sig) and time.time() - int(ts) < 30 * 86400:
                    return True
        return False

    def out(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def redirect(self, to, headers=None):
        h = {"Location": to}
        h.update(headers or {})
        self.out(303, "", headers=h)

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = urllib.parse.parse_qs(self.rfile.read(n).decode(), keep_blank_values=True)
        d = {k: v[0] for k, v in raw.items()}
        d["_ids"] = [i for i in raw.get("ids", []) if i.isdigit()]
        return d

    def login_page(self, err=""):
        self.out(200, f"""<!doctype html><html lang="lt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prisijungti</title><style>{CSS}</style></head><body><main style="max-width:380px;margin-top:12vh">
<div class="box"><h2>⚡ Galios Pikas</h2><form method="post" action="/prisijungti">
<input type="password" name="pw" placeholder="Slaptažodis" autofocus><br><br>
<button class="btn">Prisijungti</button> <span class="bad">{e(err)}</span></form></div></main></body></html>""")

    # ---------- GET ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(path.query).items()}
        p = path.path.rstrip("/") or "/"
        if p == "/health":
            return self.out(200, "ok", "text/plain")
        if p == "/atsijungti":
            return self.redirect("/", {"Set-Cookie": "gp=; Max-Age=0; Path=/"})
        if not self.authed():
            return self.login_page()
        c = db.conn()
        if p == "/":
            return self.out(200, self.home(c))
        if p == "/klientai":
            return self.out(200, self.leads(c, q))
        if p == "/laiskai":
            return self.out(200, self.drafts(c, q))
        if p == "/agentai":
            return self.out(200, self.runs(c))
        if p == "/ataskaitos":
            return self.out(200, self.reports(c))
        if p == "/nustatymai":
            return self.out(200, self.settings(q))
        if p == "/pamokos":
            return self.out(200, self.lessons(q))
        self.out(404, page("Nerasta", "<h2>Nerasta</h2>"))

    def home(self, c):
        one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        cards = [
            (one("SELECT COUNT(*) FROM leads WHERE created_at >= date('now','-7 day')"), "Nauji klientai per 7 d."),
            (one("SELECT COUNT(*) FROM leads WHERE kind='karstas' AND status='naujas'"), "🔥 Karšti (neperžiūrėti)"),
            (one("SELECT COUNT(*) FROM leads WHERE kind='b2b'"), "B2B įmonių bazėje"),
            (one("SELECT COUNT(*) FROM drafts WHERE status='laukia'"), "Laiškai laukia patvirtinimo"),
            (one("SELECT COUNT(*) FROM drafts WHERE status='issiusta'"), "Išsiųsta laiškų"),
            (one("SELECT COUNT(*) FROM leads WHERE status IN ('atsake','klientas')"), "Atsakė / tapo klientais"),
        ]
        h = '<div class="cards">' + "".join(f'<div class="card"><div class="n">{n}</div><div class="l">{l}</div></div>' for n, l in cards) + "</div>"
        s = db.load_settings()
        h += f"""<div class="box row"><span>Claude agentams: {'<b class="ok">prijungtas</b>' if s.get('claude_token') else '<b class="bad">neprijungtas</b> – <a href="/nustatymai">įvesk raktą</a>'}</span>
<span>· El. paštas siuntimui: {'<b class="ok">nustatytas</b>' if s.get('smtp_password') else '<b class="bad">nenustatytas</b>'}</span></div>"""
        hot = c.execute("SELECT * FROM leads WHERE kind='karstas' ORDER BY id DESC LIMIT 8").fetchall()
        h += "<h2>🔥 Naujausi karšti klientai</h2>" + self.lead_table(hot)
        rep = c.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        if rep:
            h += f'<h2>Paskutinė ataskaita <span class="muted">{e(rep["created_at"])}</span></h2><div class="box"><pre>{e(rep["body"])}</pre></div>'
        return page("Apžvalga", h, "")

    def lead_table(self, rows, actions=False, trash=False):
        if not rows:
            return '<div class="box muted">Tuščia.</div>'
        chk = '<th style="width:30px"><input type="checkbox" style="width:auto" onclick="document.querySelectorAll(\'input[name=ids]\').forEach(x=>x.checked=this.checked)"></th>' if actions else ""
        t = f"<table><tr>{chk}<th>Įmonė / žmogus</th><th>Ko reikia / kategorija</th><th>Kontaktai</th><th>Šaltinis</th><th>Statusas</th>{'<th></th>' if actions else ''}</tr>"
        for r in rows:
            contacts = " ".join(x for x in [
                f'<a href="tel:{e(r["phone"])}">{e(r["phone"])}</a>' if r["phone"] else "",
                f'<a href="mailto:{e(r["email"])}">{e(r["email"])}</a>' if r["email"] else "",
                f'<a href="{e(r["website"])}" target="_blank">svetainė</a>' if r["website"] else "",
                f'<a href="{e(r["url"])}" target="_blank">nuoroda</a>' if r["url"] else ""] if x)
            st = e(STATUS_LT.get(r["status"], r["status"]))
            if actions:
                opts = "".join(f'<option value="{k}" {"selected" if k == r["status"] else ""}>{v}</option>' for k, v in STATUS_LT.items())
                st = f'<form method="post" action="/statusas"><input type="hidden" name="id" value="{r["id"]}"><select name="status" onchange="ajaxPost(this.form)">{opts}</select></form>'
            box = f'<td><input type="checkbox" name="ids" value="{r["id"]}" form="bulk" style="width:auto"></td>' if actions else ""
            act = ""
            if actions:
                a, lbl, cls = ("atkurti", "↩ Atkurti", "g") if trash else ("ismesti", "🗑", "r")
                act = f'<td><form method="post" action="/siuksliadeze" data-ajax="row"><input type="hidden" name="ids" value="{r["id"]}"><button class="btn {cls}" name="a" value="{a}" title="{"Atkurti" if trash else "Į šiukšliadėžę"}">{lbl}</button></form></td>'
            keys = r.keys()
            info = " · ".join(x for x in [
                f'🚚 {e(r["vehicles"])} TP' if "vehicles" in keys and r["vehicles"] else "",
                f'👥 {e(r["employees"])} darb.' if "employees" in keys and r["employees"] else "",
                f'💶 {e(r["revenue"])}' if "revenue" in keys and r["revenue"] else "",
                f'Vadovas: {e(r["director"])}' if "director" in keys and r["director"] else "",
                f'Veikla: {e(r["activity"])}' if "activity" in keys and r["activity"] else ""] if x)
            info = f'<div style="font-size:13px;margin-top:4px">{info}</div>' if info else ""
            t += (f'<tr>{box}<td><b>{e(r["name"])}</b><div class="muted">{e(r["city"])} {e(r["address"])}</div>{info}</td>'
                  f'<td>{e(r["category"])}<div class="muted">{e(r["note"])}</div></td><td>{contacts}</td>'
                  f'<td><span class="pill">{e(r["source"])}</span><div class="muted">{e(r["created_at"])}</div></td><td>{st}</td>{act}</tr>')
        return t + "</table>"

    def leads(self, c, q):
        kind, status, s = q.get("tipas", ""), q.get("statusas", ""), q.get("q", "")
        trash = q.get("rodinys") == "siuksliadeze"
        sql, a = "SELECT * FROM leads WHERE " + ("status='atmestas'" if trash else "status<>'atmestas'"), []
        if kind: sql += " AND kind=?"; a.append(kind)
        if status: sql += " AND status=?"; a.append(status)
        if s: sql += " AND (name LIKE ? OR category LIKE ? OR note LIKE ? OR city LIKE ?)"; a += [f"%{s}%"] * 4
        rows = c.execute(sql + " ORDER BY id DESC LIMIT 300", a).fetchall()
        opt = lambda d, cur: "".join(f'<option value="{k}" {"selected" if k == cur else ""}>{v}</option>' for k, v in d.items())
        ntrash = c.execute("SELECT COUNT(*) FROM leads WHERE status='atmestas'").fetchone()[0]
        tabs = (f'<div class="row" style="margin-bottom:14px"><a class="btn {"g" if trash else ""}" href="/klientai">Aktyvūs</a>'
                f'<a class="btn {"" if trash else "g"}" href="/klientai?rodinys=siuksliadeze">🗑 Šiukšliadėžė ({ntrash})</a></div>')
        bulk = (f'<form id="bulk" method="post" action="/siuksliadeze" data-ajax="bulk" class="row" style="margin-bottom:10px">'
                + ('<button class="btn g" name="a" value="atkurti">↩ Atkurti pažymėtus</button>' if trash else '<button class="btn r" name="a" value="ismesti">🗑 Pažymėtus į šiukšliadėžę</button>')
                + '</form>')
        f = f"""<form class="row box" method="get">{'<input type="hidden" name="rodinys" value="siuksliadeze">' if trash else ''}<select name="tipas" style="width:auto">{opt({"": "Visi tipai", "karstas": "🔥 Karšti", "b2b": "B2B"}, kind)}</select>
<select name="statusas" style="width:auto">{opt(dict([("", "Visi statusai")] + [(k, v) for k, v in STATUS_LT.items() if k != "atmestas"]), status)}</select>
<input name="q" value="{e(s)}" placeholder="Paieška..." style="max-width:260px"><button class="btn g">Filtruoti</button>
<span class="muted">Rodoma: {len(rows)}</span></form>"""
        js = """<script>
function ajaxPost(f, sub){const fd=new FormData(f, sub);return fetch(f.action,{method:'POST',body:new URLSearchParams(fd),redirect:'manual',credentials:'same-origin'});}
document.addEventListener('submit',async ev=>{const f=ev.target,m=f.dataset.ajax;if(!m)return;ev.preventDefault();
 const rows=m==='row'?[f.closest('tr')]:[...document.querySelectorAll('input[name=ids]:checked')].map(x=>x.closest('tr')).filter(Boolean);
 if(!rows.length)return;await ajaxPost(f,ev.submitter);rows.forEach(r=>r.remove());});
</script>"""
        return page("Klientai", "<h2>Klientai</h2>" + tabs + f + bulk + self.lead_table(rows, True, trash) + js, "klientai")

    def drafts(self, c, q):
        st = q.get("statusas", "laukia")
        rows = c.execute("SELECT d.*, l.name, l.email, l.website, l.category FROM drafts d LEFT JOIN leads l ON l.id=d.lead_id WHERE d.status=? ORDER BY d.id DESC LIMIT 100", (st,)).fetchall()
        tabs = " ".join(f'<a class="btn {"" if k == st else "g"}" href="/laiskai?statusas={k}">{v}</a>' for k, v in
                        [("laukia", "Laukia patvirtinimo"), ("issiusta", "Išsiųsti"), ("atmesta", "Atmesti"), ("klaida", "Klaidos")])
        h = f'<h2>Laiškai</h2><div class="row" style="margin-bottom:16px">{tabs}</div>'
        if not rows:
            h += '<div class="box muted">Nėra laiškų.</div>'
        for r in rows:
            dis = "" if st in ("laukia", "klaida") else "disabled"
            h += f"""<div class="box"><div class="row"><b>{e(r['name'])}</b><span class="pill">{e(r['category'])}</span>
<span class="muted">{e(r['email']) or '<span class=bad>nėra el. pašto</span>'} · {e(r['created_at'])}</span>
{f'<a href="{e(r["website"])}" target="_blank">svetainė</a>' if r['website'] else ''}</div>
{f'<div class="bad">{e(r["error"])}</div>' if r['error'] else ''}
<form method="post" action="/laiskas"><input type="hidden" name="id" value="{r['id']}"><br>
<input name="subject" value="{e(r['subject'])}" {dis}><br><br><textarea name="body" {dis}>{e(r['body'])}</textarea><br><br>
{'' if dis else '<div class="row"><button class="btn" name="a" value="siusti">Siųsti</button><button class="btn g" name="a" value="saugoti">Išsaugoti</button><button class="btn r" name="a" value="atmesti">Atmesti</button></div>'}
</form></div>"""
        return page("Laiškai", h, "laiskai")

    def runs(self, c):
        h = "<h2>Agentai</h2><div class='box'><div class='muted' style='margin-bottom:10px'>Agentai dirba pagal grafiką automatiškai. Gali paleisti ir rankiniu būdu – paspaudus atsiranda „eilėje“, nes AI agentai dirba po vieną (Google Maps – lygiagrečiai). Puslapis atsinaujina pats.</div><div class='row'>"
        for k, v in AGENTS.items():
            h += f'<form class="inline" method="post" action="/paleisti"><input type="hidden" name="agent" value="{k}"><button class="btn g">▶ {e(v)}</button></form>'
        h += """</div><div class="muted" style="margin-top:10px">Grafikas: B2B medžiotojas – kasdien 03:10 · Žvalgas – kasdien 07:40 ir 17:40 · Tikrintojas – laikinai išjungtas · Socialinių tinklų žvalgas – kasdien 12:10 · Rašytojas – darbo dienomis 08:30 · Analitikas – pirmadieniais 07:15 · Mokytojas – kasdien 22:30</div></div>"""
        rows = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 60").fetchall()
        h += "<table><tr><th>Agentas</th><th>Pradžia</th><th>Pabaiga</th><th>Būsena</th><th>Rezultatas</th></tr>"
        for r in rows:
            cls = "ok" if r["status"] == "ok" else ("bad" if r["status"] in ("klaida", "nutraukta") else "")
            h += (f'<tr><td>{e(AGENTS.get(r["agent"], r["agent"]))}</td><td>{e(r["started_at"])}</td><td>{e(r["finished_at"])}</td>'
                  f'<td class="{cls}">{e(r["status"])}</td><td><details><summary class="muted">rodyti</summary><pre>{e(r["summary"])}</pre></details></td></tr>')
        if any(r["status"] in ("eilėje", "vyksta") for r in rows):
            h += '<script>setTimeout(()=>{if(!document.querySelector("details[open]"))location.reload()},15000)</script>'
        return page("Agentai", h + "</table>", "agentai")

    def reports(self, c):
        rows = c.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 30").fetchall()
        h = "<h2>Ataskaitos</h2>" + ("".join(f'<div class="box"><b>{e(r["title"])}</b> <span class="muted">{e(r["created_at"])}</span><pre style="margin-top:10px">{e(r["body"])}</pre></div>' for r in rows) or '<div class="box muted">Pirmoji ataskaita bus pirmadienį.</div>')
        return page("Ataskaitos", h, "ataskaitos")

    def lessons(self, q):
        msg = '<div class="box ok">Išsaugota. Agentai laikysis nuo kito paleidimo.</div>' if q.get("ok") else ""
        h = f"""<h2>Pamokos</h2>{msg}<div class="box muted">Mokytojas kasvakar 22:30 peržiūri tavo veiksmus (🗑 išmesti klientai, „Atsakė/Klientas“, pataisyti ir atmesti laiškai) ir čia surašo taisykles, kurių laikosi visi agentai. Gali taisyti ir pats – tavo įrašai turi pirmenybę.</div>
<form method="post" action="/pamokos"><div class="box"><b>Pamokos visiems agentams</b><br><br>
<textarea name="lessons" style="min-height:300px">{e(db.read_text(db.LESSONS_PATH))}</textarea></div>
<div class="box"><b>Netinkami žodžiai</b> <span class="muted">(įmonės, kurių pavadinime ar kategorijoje yra šie žodžiai, nebepridedamos; po vieną eilutėje)</span><br><br>
<textarea name="exclude" style="min-height:140px">{e(db.read_text(db.EXCLUDE_PATH))}</textarea></div>
<button class="btn">Išsaugoti</button></form>
<form method="post" action="/paleisti" style="margin-top:12px"><input type="hidden" name="agent" value="mokytojas"><button class="btn g">▶ Paleisti Mokytoją dabar</button></form>"""
        return page("Pamokos", h, "pamokos")

    def settings(self, q):
        s = db.load_settings()
        mark = lambda k: '<span class="ok">✔ įvesta</span>' if s.get(k) else '<span class="bad">nėra</span>'
        msg = '<div class="box ok">Išsaugota.</div>' if q.get("ok") else ""
        if q.get("testas") == "ok":
            msg = f'<div class="box ok">✔ Testinis laiškas išsiųstas į {e(s.get("smtp_user", "info@galiospikas.lt"))}. Slaptažodis teisingas.</div>'
        elif q.get("testas"):
            msg = f'<div class="box bad">✖ Nepavyko: {e(q.get("testas"))}</div>'
        h = f"""<h2>Nustatymai</h2>{msg}<form method="post" action="/nustatymai">
<div class="box"><b>Claude prisijungimas agentams</b> {mark('claude_token')}<p class="muted">Savo kompiuteryje terminale paleisk <code>claude setup-token</code>, prisijunk ir įklijuok gautą raktą (prasideda <code>sk-ant-oat</code>). Agentai naudos tavo Claude prenumeratą.</p>
<input name="claude_token" type="password" placeholder="Palik tuščią, jei nekeiti"></div>
<div class="box"><b>El. paštas laiškų siuntimui</b> {mark('smtp_password')}<p class="muted">Laiškai siunčiami iš šio Hostinger pašto dėžutės.</p>
<input name="smtp_user" value="{e(s.get('smtp_user', 'info@galiospikas.lt'))}"><br><br>
<input name="smtp_password" type="password" placeholder="Pašto slaptažodis (palik tuščią, jei nekeiti)"><br><br>
<label class="muted">Maks. laiškų per dieną</label><input name="daily_limit" value="{e(s.get('daily_limit', 15))}" style="max-width:120px"></div>
<div class="box"><b>Apify – Facebook įrašų paieška</b> {mark('apify_token')}<p class="muted">console.apify.com → Settings → API &amp; Integrations → nukopijuok „Personal API token“. Nemokamas planas: 5 $/mėn. Kaina ~0,005 $ už įrašą, ~0,0025 $ už komentarą (3 paieškos × 15 įrašų + 5 įrašų komentarai ≈ 0,45 $/d.). Rekomenduojama Apify'e nustatyti mėnesio limitą: console.apify.com/billing#/limits</p>
<input name="apify_token" type="password" placeholder="Apify token (palik tuščią, jei nekeiti)"><br><br>
<div class="row"><label class="muted">Įrašų per paiešką</label><input name="apify_posts" value="{e(s.get('apify_posts', 15))}" style="max-width:90px">
<label class="muted">Paieškų per dieną</label><input name="apify_queries" value="{e(s.get('apify_queries', 3))}" style="max-width:90px">
<label class="muted">Komentarų: kiek populiariausių įrašų tikrinti (0 = ne)</label><input name="apify_comment_posts" value="{e(s.get('apify_comment_posts', 5))}" style="max-width:90px"></div><br>
<label class="muted">Viešos Facebook grupės (po vieną nuorodą eilutėje, pvz. BMW / VAG / auto problemų grupės)</label>
<textarea name="fb_groups" style="min-height:90px">{e(s.get('fb_groups', ''))}</textarea></div>
<button class="btn">Išsaugoti</button></form>
<form method="post" action="/testas-pasto" style="margin-top:12px"><button class="btn g">✉ Išbandyti paštą</button></form>"""
        return page("Nustatymai", h, "nustatymai")

    # ---------- POST ----------
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/prisijungti":
            f = self.form()
            if PASSWORD and hmac.compare_digest(f.get("pw", ""), PASSWORD):
                ts = str(int(time.time()))
                return self.redirect("/", {"Set-Cookie": f"gp={ts}.{sign(ts)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000"})
            time.sleep(1.5)
            return self.login_page("Neteisingas slaptažodis")
        if not self.authed():
            return self.redirect("/")
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self.out(403, "Forbidden", "text/plain")
        f = self.form()
        c = db.conn()
        if p == "/statusas":
            c.execute("UPDATE leads SET status=?, updated_at=? WHERE id=?", (f.get("status"), db.now(), f.get("id"))); c.commit()
            return self.redirect(self.headers.get("Referer") or "/klientai")
        if p == "/pamokos":
            db.write_text(db.LESSONS_PATH, f.get("lessons", "").strip() + "\n")
            words = sorted({w.strip().lower() for w in f.get("exclude", "").splitlines() if 2 < len(w.strip()) < 40})
            db.write_text(db.EXCLUDE_PATH, "\n".join(words) + ("\n" if words else ""))
            return self.redirect("/pamokos?ok=1")
        if p == "/siuksliadeze" and f["_ids"]:
            new = "atmestas" if f.get("a") == "ismesti" else "naujas"
            c.executemany("UPDATE leads SET status=?, updated_at=? WHERE id=?", [(new, db.now(), i) for i in f["_ids"]]); c.commit()
            return self.redirect(self.headers.get("Referer") or "/klientai")
        if p == "/paleisti" and f.get("agent") in AGENTS:
            ag = f["agent"]
            if not c.execute("SELECT 1 FROM runs WHERE agent=? AND status IN ('eilėje','vyksta')", (ag,)).fetchone():
                cur = c.execute("INSERT INTO runs(agent,started_at,status) VALUES(?,?,'eilėje')", (ag, db.now())); c.commit()
                os.makedirs(TRIG, exist_ok=True)
                open(os.path.join(TRIG, f"{ag}.{cur.lastrowid}"), "w").close()
            return self.redirect("/agentai")
        if p == "/laiskas":
            did, a = f.get("id"), f.get("a")
            c.execute("UPDATE drafts SET subject=?, body=? WHERE id=? AND status IN ('laukia','klaida')", (f.get("subject"), f.get("body"), did)); c.commit()
            d = c.execute("SELECT d.*, l.email FROM drafts d LEFT JOIN leads l ON l.id=d.lead_id WHERE d.id=?", (did,)).fetchone()
            if a == "atmesti":
                c.execute("UPDATE drafts SET status='atmesta' WHERE id=?", (did,))
                c.execute("UPDATE leads SET status='atmestas', updated_at=? WHERE id=?", (db.now(), d["lead_id"])); c.commit()
            elif a == "siusti":
                s = db.load_settings()
                sent_today = c.execute("SELECT COUNT(*) FROM drafts WHERE status='issiusta' AND sent_at >= date('now')").fetchone()[0]
                try:
                    if not d["email"]:
                        raise RuntimeError("Klientas neturi el. pašto.")
                    if sent_today >= int(s.get("daily_limit", 15)):
                        raise RuntimeError("Pasiektas dienos laiškų limitas.")
                    send_mail(s, d["email"], f.get("subject"), f.get("body"))
                    c.execute("UPDATE drafts SET status='issiusta', sent_at=?, error=NULL WHERE id=?", (db.now(), did))
                    c.execute("UPDATE leads SET status='issiustas', updated_at=? WHERE id=?", (db.now(), d["lead_id"]))
                except Exception as ex:
                    c.execute("UPDATE drafts SET status='klaida', error=? WHERE id=?", (str(ex)[:500], did))
                c.commit()
            return self.redirect("/laiskai")
        if p == "/testas-pasto":
            s = db.load_settings()
            try:
                send_mail(s, s.get("smtp_user") or "info@galiospikas.lt", "Galios Pikas – pašto testas",
                          "Šis laiškas patvirtina, kad agentų sistema gali siųsti laiškus iš šios dėžutės.")
                res = "ok"
            except Exception as ex:
                res = str(ex)[:200] or "nežinoma klaida"
            return self.redirect("/nustatymai?testas=" + urllib.parse.quote(res))
        if p == "/nustatymai":
            s = db.load_settings()
            for k in ("claude_token", "smtp_password", "apify_token"):
                if f.get(k, "").strip():
                    s[k] = f[k].strip()
            s["smtp_user"] = f.get("smtp_user", "info@galiospikas.lt").strip()
            s["fb_groups"] = f.get("fb_groups", "").strip()
            for k, d, lo, hi in (("apify_posts", 15, 5, 100), ("apify_queries", 3, 1, 8), ("apify_comment_posts", 5, 0, 15)):
                try:
                    s[k] = max(lo, min(hi, int(f.get(k) or d)))
                except ValueError:
                    s[k] = d
            try:
                s["daily_limit"] = max(1, min(100, int(f.get("daily_limit") or 15)))
            except ValueError:
                pass
            db.save_settings(s)
            return self.redirect("/nustatymai?ok=1")
        self.out(404, "Nerasta", "text/plain")


if __name__ == "__main__":
    db.conn()
    print("Panel :8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
