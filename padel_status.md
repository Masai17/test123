# Padel Auto-Reservering — Status & Logboek

## Wat het systeem doet

Een GitHub Actions-gebaseerde PWA die automatisch padelbanen reserveert op TC Westvoorne via KNLTB.
- **App**: https://masai17.github.io/test123/
- **Repo**: https://github.com/Masai17/test123

### Flow
1. Gebruiker plant reservering via de app (datum + tijd + partners)
2. App triggert `plan_reservering.yml` workflow via GitHub API
3. **Window >5u weg**: opgeslagen in `reserveringen.json`, watcher pakt op
4. **Window <5u weg**: workflow wacht en reserveert op exact openingsmoment
5. **Window al open**: direct reserveren
6. Watcher draait elke 15 minuten en slaapt tot het exacte openingsmoment

Boekingsvenster KNLTB = speeltijd − 36 uur

---

## Opgeloste bugs (chronologisch)

| # | Probleem | Oplossing |
|---|---|---|
| 1 | GitHub API 403 bij plannen | Token was van verkeerde account (circus0181 i.p.v. Masai17) |
| 2 | `git pull --rebase` faalde door unstaged changes | `git add` vóór pull + `--autostash` |
| 3 | Bot-detectie op KNLTB-site | `headless=False` + Xvfb + `--disable-blink-features=AutomationControlled` |
| 4 | Nep-bevestigingen: script zei "KLAAR" zonder echte reservering | URL-check + paginatekst-verificatie na bevestigen |
| 5 | "GEEN BAAN" → script ging toch door | `RuntimeError` i.p.v. print |
| 6 | "DAG NIET GEKLIKT" → script ging toch door | `RuntimeError` i.p.v. print |
| 7 | Dag-zoeken: exacte eerste-regel match | Substring match (robuuster) |
| 8 | Dagdeel-match hoofdlettergevoelig | Case-insensitive vergelijking |
| 9 | URL-check na Volgende ontbrak | RuntimeError als pagina niet vooruitging |
| 10 | Duplicate-commit: `git commit` faalde bij al-geplande entry | `actie=geen` bij duplicaat, `git diff --cached --quiet \|\| git commit` |
| 11 | Slaapdrempel 6u te dicht bij GitHub timeout (370 min) | Drempel verlaagd naar 5u |
| 12 | Reserveringen direct uitgevoerd zonder JSON-entry | Stap toegevoegd: sla altijd op als `gedaan: true` na succesvolle run |
| 13 | Te traag na openingsmoment: dependencies installeren + login/partners/dag-navigatie gebeurden pas ná het exacte openingsmoment (~30-90s verlies), en een bezette baan liet Playwright 30s blind hangen | Dependencies nu vóór het wachten geïnstalleerd; login/partners/dag-selectie gebeuren al binnen een voorbereidingsbuffer van 3 min vóór opening; dag- en baanselectie pollen nu elke 150ms en klikken direct via JS zodra een cel niet meer disabled is (geen 30s-timeout meer) |
| 14 | Elke reservering = nieuwe login = KNLTB-telefoon-app logt gebruiker uit (bevestigd: 2 losse browsersessies met zelfde account hinderden elkaar niet op websiteniveau, dus het inlog-*event* zelf is de trigger, niet "2 sessies tegelijk") | Nieuwe secret `KNLTB_SESSION_STATE` (cookies van een ingelogde sessie, buiten de repo om als encrypted GitHub Secret). Script probeert die eerst; alleen bij verlopen sessie valt hij terug op een echte login |
| 15 | `plan_reservering.yml` (directe aanvraag in de app) had de fixes van #13/#14 niet: dependencies nog na het wachten, geen sessie-hergebruik | Zelfde structuur als `padel_watcher.yml` toegepast: dependencies vooraf, prep-buffer, sessie-hergebruik, `OPENT_ISO` doorgegeven |
| 16 | Race condition: 2 gelijktijdige workflow-runs die allebei `reserveringen.json` wijzigen kunnen op een merge-conflict lopen via `git pull --rebase --autostash`, waardoor een aanvraag stilletjes verloren gaat (gebeurde echt tijdens testen op 20-07-2026) | Alle 4 schrijfplekken (opslaan bij aanvraag, opslaan als wachtend, 2x markeren als gedaan) gebruiken nu een retry-loop: fetch + `reset --hard origin/main`, wijziging vers toepassen, commit, push; bij falende push (race) tot 5x opnieuw |

---

## Nog openstaande problemen

### Hoofdprobleem: Playwright reservering werkt niet betrouwbaar (voor deel opgelost, zie hieronder)

Meest waarschijnlijke resterende oorzaken:
1. `playwright-stealth` installeert niet (versie-conflict), maar login werkt zonder — geen actie nodig
2. Onbekend of `KNLTB_SESSION_STATE` in de praktijk lang genoeg geldig blijft om echt te helpen — moet blijken uit productiegebruik

### 20-07-2026: onderzoek "waarom geen reservering om 20:30" (opgelost)
Reservering 21-07-2026 20:30 (Ed Rip, Yorrick Bussink, Theo Herkenraad) lukte niet, ook niet vlak na openingsmoment. Live DOM-inspectie toonde alle 4 padelbanen (F/G/H/I) als `disabled` op dat tijdstip, terwijl de tennisbanen dezelfde avond gewoon vrij waren — leek op een structurele blokkade. **Gebruiker bevestigde: dinsdag is geen vaste competitiedag, alle reserveringen gaan op aanvraag** — dus het was gewoon een kwestie van net te laat zijn na opening, geen structureel probleem. Bug #13 (timing) was dus wel degelijk de juiste fix. Reservering zelf is nadien verwijderd uit `reserveringen.json` (niet meer relevant).

### Live tests lopen nog (gestart 20-07-2026 ~22:40)
Twee testreserveringen met Rens Dekker, bedoeld om beide code-paden te verifiëren:
- **22-07-2026 12:30** — binnen-5u-pad (`plan_reservering.yml` reserveert zelf, wacht tot opent 21-07 00:30). Run: https://github.com/Masai17/test123/actions/runs/29777112881
- **23-07-2026 12:30** — buiten-5u-pad (opgeslagen voor de watcher, opent 22-07 00:30)

**Bij volgende sessie checken:**
- Is de 22-07-boeking gelukt? (`gh run view 29777112881 --repo Masai17/test123 --log`)
- Bleef de telefoon-app ingelogd tijdens die run, of is er alsnog uitgelogd?
- Heeft de watcher de 23-07-boeking succesvol opgepakt?
- Stond er "Bewaarde sessie werkt nog" in de log, of viel hij terug op een nieuwe login?

---

## Geplande reserveringen

| Speeltijd | Partners | Status |
|---|---|---|
| 22-07-2026 12:30 | Rens Dekker | ⏳ Test binnen-5u-pad, workflow loopt |
| 23-07-2026 12:30 | Rens Dekker | ⏳ Test buiten-5u-pad, wacht op watcher |

---

## Technische details

- **Baan-voorkeur** voor 19:00: F → G → I → H
- **Baan-voorkeur** na 19:00: G → F → H → I
- **Baan-nummers** in selector: F=day6, G=day7, H=day8, I=day9
- **Tijdslot-selector**: `#dayN div[data-hour="HH"]`
- **GitHub account voor dit repo**: **Masai17** (niet circus0181 — dat account heeft geen push-toegang tot `Masai17/test123`, getest en bevestigd op 20-07-2026; dit wijkt af van de standaard CLAUDE.md-regel maar is voor dit project zo afgesproken). `gh auth switch --user Masai17` vóór pushen.
- **Secrets in de repo**: `KNLTB_GEBRUIKERSNUMMER`, `KNLTB_WACHTWOORD`, `KNLTB_WEBSITE`, `INTRODUCEE_EMAIL`, `KNLTB_SESSION_STATE` (nieuw, bevat cookies van een ingelogde sessie — nooit als bestand opslaan, alleen als secret)
