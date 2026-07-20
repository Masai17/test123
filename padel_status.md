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

---

## Nog openstaande problemen

### Hoofdprobleem: Playwright reservering werkt niet betrouwbaar

Symptomen:
- **"DAG NIET GEKLIKT"** — kalender toont de gewenste datum niet (bijv. vandaag boeken kan niet op KNLTB)
- **URL verandert niet na Volgende** — knop geklikt maar pagina ging niet vooruit
- **Baan niet gevonden** — dag niet geselecteerd, dus baanrooster leeg

Meest waarschijnlijke oorzaken:
1. KNLTB-site vereist dat je reserveert voor een **toekomstige** datum (niet dezelfde dag)
2. De dag-selectie logica vindt de kolom wel maar klikt het dagdeel niet goed aan
3. `playwright-stealth` installeert niet (versie-conflict), maar login werkt zonder

### Wat nog niet getest is met de nieuwe code
De fixes (substring-dag-match, URL-checks, RuntimeError-crashes) zijn aangebracht maar **nog niet succesvol getest** op een echte toekomstige reservering met een geldig tijdslot.

### 20-07-2026: onderzoek "waarom geen reservering om 20:30"
Reservering 21-07-2026 20:30 (Ed Rip, Yorrick Bussink, Theo Herkenraad) lukte niet ondanks meerdere pogingen, ook vlak na het openingsmoment (08:30). Live DOM-inspectie via Playwright toonde: alle 4 padelbanen (F/G/H/I) hadden op dat tijdstip de class `disabled`, terwijl de tennisbanen (A-E) op exact dezelfde avond gewoon vrij waren. Dat wijst op een structurele blokkade (padelcompetitie/training elke dinsdagavond 19-21u), niet op een te trage app — al gaf de gebruiker aan dat volgens hun ervaring 5 minuten na opening al te laat kan zijn.
Vervolgens is de timing sowieso verbeterd (zie bug #13), voor de gevallen waar wél echte concurrentie tussen leden meespeelt.
**Open vraag**: is dinsdagavond 19-21u structureel padelcompetitie bij TC Westvoorne? Navragen bij de club om zeker te weten dat 20:30 op dinsdag sowieso nooit boekbaar is.

---

## Geplande reserveringen

| Speeltijd | Partners | Status |
|---|---|---|
| 01-06-2026 20:30 | (zie app) | ⏳ Wacht — venster opent **31-05-2026 om 08:30** |

De watcher reserveert morgenochtend automatisch op 08:30.

---

## Technische details

- **Baan-voorkeur** voor 19:00: F → G → I → H
- **Baan-voorkeur** na 19:00: G → F → H → I
- **Baan-nummers** in selector: F=day6, G=day7, H=day8, I=day9
- **Tijdslot-selector**: `#dayN div[data-hour="HH"]`
- **GitHub account**: Masai17 (via `gh auth switch`)
