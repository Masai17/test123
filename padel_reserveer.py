import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
 
NL = ZoneInfo("Europe/Amsterdam")
 
GEBRUIKERSNUMMER  = os.getenv("KNLTB_GEBRUIKERSNUMMER", "")
WACHTWOORD        = os.getenv("KNLTB_WACHTWOORD", "")
WEBSITE           = os.getenv("KNLTB_WEBSITE", "")
SPEEL_DATUM_TIJD  = os.getenv("SPEEL_DATUM_TIJD", "")
PARTNERS          = os.getenv("PARTNERS", "")
INTRODUCEE_EMAIL  = os.getenv("INTRODUCEE_EMAIL", "")
 
 
def nu_nl():
    return datetime.now(tz=NL)
 
def parse_speeltijd(tekst):
    for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(tekst.strip(), fmt).replace(tzinfo=NL)
        except ValueError:
            continue
    raise ValueError("Ongeldige datum: " + tekst)
 
def bepaal_baan_volgorde(t):
    if t.hour < 19:
        return ["F", "G", "I", "H"]
    else:
        return ["G", "F", "H", "I"]
 
def bepaal_dagdeel(t):
    if t.hour < 12:   return "Ochtend"
    elif t.hour < 19: return "Middag"
    else:             return "Avond"
 
 
async def klik_volgende(page):
    from playwright.async_api import TimeoutError as PWTimeout
    try:
        btn = page.get_by_role("button", name="Volgende")
        if await btn.count() > 0:
            await btn.last.click(timeout=8000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(0.5)
            print("  Volgende: OK")
            return
    except PWTimeout:
        pass
    try:
        btn = page.locator("button").filter(has_text="Volgende").last
        await btn.click(timeout=8000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(0.5)
        print("  Volgende: OK (filter)")
        return
    except PWTimeout:
        pass
    try:
        await page.evaluate(
            "() => { const knoppen = [...document.querySelectorAll('button')]; for (const k of knoppen.reverse()) { if ((k.textContent||'').includes('Volgende')) { k.click(); return; } } }"
        )
    except Exception as e:
        # "Execution context was destroyed" = klik triggerde navigatie, dat is prima
        if "context was destroyed" not in str(e).lower() and "execution context" not in str(e).lower():
            raise
        print("  Volgende: navigatie gedetecteerd (OK)")
    await page.wait_for_load_state("networkidle", timeout=15000)
    await asyncio.sleep(0.5)
    print("  Volgende: OK (JS)")
 
 
async def probeer_tijdcel(page, baan, speeltijd):
    dag_nummer = {"F": "6", "G": "7", "H": "8", "I": "9"}[baan]
    uur        = str(speeltijd.hour)
    selector   = "#day" + dag_nummer + " div[data-hour=\"" + uur + "\"]"
    print("  Probeer baan " + baan + " (" + selector + ")")
    try:
        tijdcel = page.locator(selector).first
        await tijdcel.wait_for(state="visible", timeout=3000)
        await tijdcel.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await tijdcel.click()
        await asyncio.sleep(1.5)
        print("  Baan " + baan + " geselecteerd!")
        return True
    except Exception as e:
        print("  Baan " + baan + " niet beschikbaar: " + str(e)[:60])
        return False
 
 
async def voeg_introducee_toe(page, naam, email):
    """Klik op 'Introducé toevoegen +', vul naam en e-mail in, klik 'Toevoegen'."""
    print("  Introducé toevoegen: " + naam)
    try:
        # Gebruik JS om de knop te vinden (omzeilt é/speciale tekens problemen)
        geklikt = await page.evaluate(
            "() => { const knoppen = [...document.querySelectorAll('button, a')]; "
            "const k = knoppen.find(b => (b.textContent||'').toLowerCase().includes('introduc')); "
            "if (k) { k.click(); return true; } return false; }"
        )
        if not geklikt:
            print("  FOUT: Introducé knop niet gevonden op pagina")
            return False
        await asyncio.sleep(1.5)
 
        # Vul naam in — eerste zichtbare text-input in de modal
        naam_veld = page.locator("input[type='text']").first
        await naam_veld.wait_for(state="visible", timeout=5000)
        await naam_veld.fill(naam)
        await asyncio.sleep(0.3)
 
        # Vul e-mail in — second input of type email, or second text input
        email_veld = page.locator("input[type='email']").first
        if await email_veld.count() == 0:
            email_veld = page.locator("input[type='text']").nth(1)
        await email_veld.fill(email)
        await asyncio.sleep(0.3)
 
        # Klik "Toevoegen" via JS (vermijdt ambiguïteit met andere knoppen)
        await page.evaluate(
            "() => { const knoppen = [...document.querySelectorAll('button')]; "
            "const k = knoppen.find(b => (b.textContent||'').trim().toLowerCase() === 'toevoegen'); "
            "if (k) k.click(); }"
        )
        await asyncio.sleep(1)
        print("  + Introducé toegevoegd: " + naam)
        return True
    except Exception as e:
        print("  FOUT bij introducé toevoegen: " + str(e)[:80])
        return False
 
 
async def reserveer(speeltijd, baan_volgorde, partners):
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
 
    tijd_str  = speeltijd.strftime("%H:%M")
    datum_dag = str(speeltijd.day)
    dagdeel   = bepaal_dagdeel(speeltijd)
 
    dag_afkortingen = ["", "ma", "di", "wo", "do", "vr", "za", "zo"]
    zoek_tekst      = dag_afkortingen[speeltijd.isoweekday()] + " " + datum_dag
 
    async with async_playwright() as p:
        print("Browser openen...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page    = await context.new_page()
 
        # Stap 0: Inloggen
        print("Inloggen...")
        await page.goto(WEBSITE, wait_until="networkidle", timeout=30000)
        try:
            await page.select_option("select", label="Bondsnummer")
        except Exception:
            pass
        await asyncio.sleep(0.3)
        await page.locator('input[type="text"]').first.fill(GEBRUIKERSNUMMER)
        await page.fill('input[type="password"]', WACHTWOORD)
        await page.locator('button:has-text("Inloggen")').click()
        await page.wait_for_load_state("networkidle", timeout=20000)
        print("  Ingelogd!")
 
        # Stap 1: Baan reserveringen tab
        print("Naar Baan reserveringen...")
        await page.locator('text=Baan reserveringen').click()
        await page.wait_for_load_state("networkidle", timeout=10000)
 
        # Stap 2: Baan afhangen
        print("Baan afhangen...")
        await page.locator('text=Baan afhangen').click()
        await page.wait_for_load_state("networkidle", timeout=10000)
 
        # Stap 3: Partners
        print("Partners: " + str(partners))
        for partner in partners:
            # Controleer of dit een introducé is (prefix "introducee:")
            if partner.lower().startswith("introducee:"):
                introducee_naam = partner[len("introducee:"):].strip()
                await voeg_introducee_toe(page, introducee_naam, INTRODUCEE_EMAIL)
                await asyncio.sleep(0.5)
                continue
 
            toegevoegd = False
            try:
                zoek = page.locator('#searchPlayerText')
                if await zoek.count() == 0:
                    zoek = page.locator('input[type="text"]').first
                await zoek.click()
                await zoek.type(partner, delay=80)
                print("  Getypt: " + partner)
                await asyncio.sleep(2)
 
                try:
                    dropdown = page.locator(".ui-autocomplete li, [class*=autocomplete] li, [class*=result] li").first
                    await dropdown.wait_for(state="visible", timeout=4000)
                    await dropdown.click()
                    print("  + " + partner + " (dropdown)")
                    toegevoegd = True
                except Exception:
                    pass
 
                if not toegevoegd:
                    try:
                        item    = page.get_by_text(partner, exact=False).first
                        box     = await item.bounding_box()
                        zoek_box = await page.locator("#searchPlayerText").bounding_box()
                        if box and zoek_box and box["y"] > zoek_box["y"] + zoek_box["height"]:
                            await item.click(timeout=3000)
                            print("  + " + partner + " (positie)")
                            toegevoegd = True
                    except Exception as e:
                        print("  Fout: " + str(e))
            except Exception as e:
                print("  Fout: " + str(e))
 
            if not toegevoegd:
                print("  WAARSCHUWING: " + partner + " niet gevonden")
            await asyncio.sleep(0.5)
 
        await klik_volgende(page)
        print("  URL na partners: " + page.url)
 
        # Stap 4: Dag + dagdeel
        print("Dag: " + zoek_tekst + " dagdeel: " + dagdeel)
        await asyncio.sleep(1)  # geef pagina tijd om volledig te laden na Volgende
 
        for _ in range(8):
            try:
                zichtbaar = await page.evaluate(
                    "(dag) => { const els = document.querySelectorAll('td, th, div, span'); for (const el of els) { if ((el.innerText||'').trim().includes(dag)) return true; } return false; }",
                    datum_dag
                )
            except Exception as e:
                if "context was destroyed" in str(e).lower() or "execution context" in str(e).lower():
                    await asyncio.sleep(1)
                    continue
                raise
            if zichtbaar:
                break
            try:
                await page.locator('button:has-text(">")').click(timeout=2000)
                await asyncio.sleep(0.5)
            except PWTimeout:
                break
 
        dag_geklikt = False
        try:
            dag_x   = None
            alle_els = page.locator("td, th, div, span")
            for i in range(await alle_els.count()):
                el = alle_els.nth(i)
                try:
                    tekst = (await el.inner_text()).strip()
                    if tekst.split("\n")[0].strip().lower() == zoek_tekst.lower():
                        box = await el.bounding_box()
                        if box and box["width"] > 0:
                            dag_x = box["x"] + box["width"] / 2
                            print("  Kolom gevonden op x=" + str(round(dag_x)))
                            break
                except Exception:
                    continue
 
            if dag_x is not None:
                dagdeel_els  = page.locator("td, div")
                beste_el     = None
                beste_afstand = 9999
                for i in range(await dagdeel_els.count()):
                    el = dagdeel_els.nth(i)
                    try:
                        tekst = (await el.inner_text()).strip()
                        if tekst != dagdeel:
                            continue
                        box = await el.bounding_box()
                        if not box or box["width"] <= 0:
                            continue
                        afstand = abs(box["x"] + box["width"] / 2 - dag_x)
                        if afstand < beste_afstand:
                            beste_afstand = afstand
                            beste_el      = el
                    except Exception:
                        continue
 
                if beste_el is not None:
                    await beste_el.scroll_into_view_if_needed()
                    await beste_el.click()
                    print("  Dagdeel geklikt: " + dagdeel)
                    dag_geklikt = True
        except Exception as e:
            print("  Dag fout: " + str(e))
 
        if not dag_geklikt:
            print("  DAG NIET GEKLIKT!")
 
        await asyncio.sleep(0.5)
        await klik_volgende(page)
        print("  URL na dag: " + page.url)
 
        # Stap 5: Tijdcel - probeer banen in volgorde
        print("Tijdslot " + tijd_str + " voorkeur: " + str(baan_volgorde))
        gekozen_baan = None
        for baan in baan_volgorde:
            if await probeer_tijdcel(page, baan, speeltijd):
                gekozen_baan = baan
                break
 
        if not gekozen_baan:
            print("  GEEN BAAN BESCHIKBAAR!")
 
        await klik_volgende(page)
        print("  URL na baan: " + page.url)
 
        # Stap 6: Bevestigen
        print("Bevestigen...")
        await asyncio.sleep(1)
        bevestigd = False
        for sel in ["#confirmReservationButton", "a.btn-primary", "a[data-url*=SaveReservation]"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    print("  Bevestigen OK: " + sel)
                    bevestigd = True
                    break
            except Exception:
                continue
        if not bevestigd:
            try:
                await page.get_by_role("link", name="Bevestigen").click(timeout=5000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                print("  Bevestigen OK (link)")
                bevestigd = True
            except Exception:
                pass
        if not bevestigd:
            print("  BEVESTIGEN MISLUKT!")
 
        baan_naam = "Baan " + (gekozen_baan or "?")
        eind      = speeltijd + timedelta(hours=1)
        print("KLAAR! " + baan_naam + " op " + speeltijd.strftime('%d-%m-%Y') + " om " + tijd_str + "-" + eind.strftime('%H:%M'))
        await context.close()
        await browser.close()
 
 
async def main():
    print("Padel Auto-Reservering")
    print("======================")
 
    if not GEBRUIKERSNUMMER or not WACHTWOORD:
        raise ValueError("Stel KNLTB_GEBRUIKERSNUMMER en KNLTB_WACHTWOORD in als GitHub Secrets!")
    if not WEBSITE:
        raise ValueError("Stel KNLTB_WEBSITE in als GitHub Secret!")
    if not SPEEL_DATUM_TIJD:
        raise ValueError("Stel SPEEL_DATUM_TIJD in.")
 
    speeltijd     = parse_speeltijd(SPEEL_DATUM_TIJD)
    baan_volgorde = bepaal_baan_volgorde(speeltijd)
    partners      = [p.strip() for p in PARTNERS.split(",") if p.strip()] if PARTNERS else []
 
    print("Speeltijd:     " + speeltijd.strftime('%d-%m-%Y om %H:%M') + " (NL tijd)")
    print("Baan volgorde: " + str(baan_volgorde))
    print("Partners:      " + (", ".join(partners) if partners else "(geen)"))
    print("Nu:            " + nu_nl().strftime('%d-%m-%Y om %H:%M:%S') + " (NL tijd)")
    print()
 
    await reserveer(speeltijd, baan_volgorde, partners)
 
 
if __name__ == "__main__":
    asyncio.run(main())
