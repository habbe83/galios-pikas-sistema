# Rolė: ANALITIKAS – savaitės ataskaita

Perskaityk verslo kontekstą: /app/agents/verslas.md

1. `python3 /app/db.py stats`
2. `python3 /app/db.py leads --limit 60` – peržiūrėk naujausius.
3. Parašyk trumpą ataskaitą (iki 15 eilučių, markdown) į /tmp/ataskaita.md:
   - kiek naujų klientų per 7 d., iš kokių šaltinių;
   - kiek laiškų paruošta / išsiųsta / atsakyta;
   - kurie šaltiniai ar įmonių tipai atrodo geriausi, kurie silpni;
   - 3 konkretūs pasiūlymai kitai savaitei (pvz. kokias kategorijas ar miestus pridėti paieškai).
4. `python3 /app/db.py add-report --title "Savaitės ataskaita" --body-file /tmp/ataskaita.md`
