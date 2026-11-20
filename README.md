# Galios Pikas – klientų paieškos sistema

Agentai, kurie ieško klientų Galios Pikui, ir dashboard'as **panel.galiospikas.lt**.

| Agentas | Ką daro | Kada |
|---|---|---|
| B2B medžiotojas | Google Maps: autoservisai, prekeiviai, transporto įmonės → įmonių bazė | kasdien 03:10 |
| Žvalgas | paslaugos.lt, skelbimai, forumai – žmonės, kurie dabar ieško paslaugos | kasdien 07:40, 17:40 |
| Pasiūlymų rašytojas | Asmeniniai B2B laiškai (siunčiami tik paspaudus „Siųsti“) | darbo d. 08:30 |
| Analitikas | Savaitės ataskaita | pirmadieniais 07:15 |

- `app/agents/*.md` – agentų instrukcijos ir verslo kontekstas (keisk čia).
- `app/panel.py` – dashboard, `app/runner.py` – grafikas, `app/db.py` – duomenų bazė.
- Slaptažodžiai ir raktai laikomi tik serveryje, ne šioje repozitorijoje.
- Diegimas: Hostinger VPS → Docker Manager, projektas `galiospikas` (šis `docker-compose.yml`). Po pakeitimų – perkrauti projektą.
