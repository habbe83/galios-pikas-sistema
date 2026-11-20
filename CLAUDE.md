# Galios Pikas – projekto kontekstas Claude'ui

## Kas aš ir kaip dirbame
- Karolis Dragunaitis. Verslas **Galios Pikas** – **mobilus** automobilių programavimas ir diagnostika **Vilniuje** (atvykstame pas klientą, fizinio adreso nenurodome). Tel. +37062142133, info@galiospikas.lt.
- Bendrauk **lietuviškai, trumpai ir konkrečiai**. Nedaryk dalykų, kol neaišku ko noriu – bet ir neklausinėk nereikalingų klausimų. Pildyk esamą projektą, neperdaryk iš naujo. Siūlyk naujausius, patikrintus sprendimus, ne iš atminties.

## Paslaugos (tik šios)
1. Chiptuning: Stage 1/2, ECO, custom, pops&bangs, launch control, rev limiter, VMAX, TCU programavimas.
2. Sistemų programavimas: DPF/FAP, EGR, AdBlue/SCR/UREA, NOx, sklendės, TVA, GPF/OPF, readiness, lambda, EVAP, DTC, hot/cold start, IMMO.
3. ECU/TCU klonavimas, blokų pririšimas.
4. Kompiuterinė diagnostika: lengvieji, sunkvežimiai, motociklai.
NEdarome: europinimo, kodavimo, kondicionierių, salono valymo.

## Sistema (šioje repozitorijoje)
Klientų paieškos agentai + dashboard **https://panel.galiospikas.lt** (prisijungimas slaptažodžiu).
- Veikia Hostinger VPS `srv1918590` (Docker + Traefik), Docker projektas `galiospikas` (`docker-compose.yml`). Konteineriai paleidžiant pasiima kodą iš šios repozitorijos `main` šakos → **po pakeitimų reikia perkrauti projektą** (hPanel → VPS → Docker Manager → galiospikas → Restart).
- `app/panel.py` – dashboard (Python stdlib, SQLite `/data/galiospikas.db`).
- `app/runner.py` – grafikas ir agentų paleidimas (Claude Code `claude -p` su Karolio prenumeratos raktu iš Nustatymų).
- `app/db.py` – DB ir CLI agentams.
- `app/agents/*.md` – agentų instrukcijos: `verslas.md` (kontekstas), `zvalgas.md`, `socialai.md`, `rasytojas.md`, `tikrintojas.md`, `analitikas.md`, `mokytojas.md`, `klaidos.md` (klaidų kodai paieškai).
- Pamokos (mokymasis iš Karolio veiksmų) saugomos serveryje `/data/pamokos/`, redaguojamos dashboard'e.

### Agentai
| Agentas | Ką daro | Kada |
|---|---|---|
| B2B medžiotojas | Google Maps (gosom scraper): maži autoservisai Vilniuje pagal rajonus, sunkvežimių servisai, transporto įmonės, naudotų auto pardavėjai. Be naujų auto salonų, oficialių atstovų, detalių parduotuvių | 03:10 |
| Žvalgas | paslaugos.lt, skelbimai, forumai, klaidų kodai – žmonės, kurie dabar ieško paslaugos | 07:40, 17:40 |
| Socialinių tinklų žvalgas | Facebook įrašai + komentarai per Apify (raktas Nustatymuose) | 12:10 |
| Tikrintojas | rekvizitai.lt – **išjungtas** (blokuoja); planas: Registrų centras + Sodra atviri duomenys | – |
| Pasiūlymų rašytojas | B2B laiškai (be adreso, su paslaugų sąrašu, tel.), siunčiami tik paspaudus „Siųsti“ | darbo d. 08:30 |
| Analitikas | savaitės ataskaita | pirm. 07:15 |
| Mokytojas | mokosi iš 🗑, „Atsakė/Klientas“, pataisytų laiškų → pamokos | 22:30 |

Taisyklės: šaltus laiškus tik verslams (BDAR). Reklamoje ne „DPF OFF“, o „diagnostika ir klaidų sprendimai“.

## Darbų sąrašas
1. Papildyti `app/agents/klaidos.md` pagal markes/variklius ir realias frazes.
2. Patikrinti, ar Socialinių tinklų žvalgas veikia su Apify raktu.
3. info@galiospikas.lt slaptažodis (pašto planas ebcmor@gmail.com Hostinger paskyroje, galioja iki 2027-11-04) → dashboard „Išbandyti paštą“.
4. **Svetainė galiospikas.lt** – mobilus servisas Vilniuje, paslaugų ir klaidų kodų puslapiai (SEO), užklausos forma. Laiškų nesiųsti, kol jos nėra.
5. Google verslo profilis kaip mobilus servisas (be adreso, zona Vilnius).
6. Google Search Console.
7. Search Skill auditas (paketas Karolio kompiuteryje) – po svetainės.
8. Tikrintojas su Registrų centro ir Sodros duomenimis.
9. Facebook grupių sąrašas (viešos → Nustatymai).
10. galiospikas.com baigiasi 2026-12-27 – nuspręsti dėl pratęsimo.

## Kiti resursai
- Hostinger: domenas galiospikas.lt (Karolio paskyra), VPS `srv1918590` (šis) ir `srv1918661` (n8n, nenaudojamas).
- Slaptažodžių ir raktų šioje repozitorijoje NĖRA ir neturi būti.
