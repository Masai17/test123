import asyncio
import json
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
OPENT_ISO         = os.getenv("OPENT_ISO", "").strip()
SESSION_STATE_JSON = os.getenv("KNLTB_SESSION_STATE", "").strip()

POLL_GRACE     = timedelta(seconds=20)  # hoe lang na 'opent' we nog blijven pollen
POLL_INTERVAL  = 0.15


def nu_nl():
    return datetime.now(tz=NL)

def parse_opent_iso(tekst):
    if not tekst:
        return None
    try:
        return datetime.fromisoformat(tekst)
    except ValueError:
        return None

def parse_session_state(tekst):
    if not tekst:
        return None
    try:
        return json.loads(tekst)
    except (json.JSONDecodeError, ValueError):
        return None

TUSSENVOEGSELS = {"van", "der", "den", "de", "het", "ter", "ten", "te", "aan", "in", "'t"}

def titel_case_naam(naam):
    woorden = naam.strip().split()
    resultaat = []
    for i, w in enumerate(woorden):
        wl = w.lower()
        resultaat.append(wl if i > 0 and wl in TUSSENVOEGSELS else wl.capitalize())
    return " ".join(resultaat)

def poll_deadline(opent):
    """Tot wanneer we mogen blijven pollen: net na het bekende openingsmoment,
    of een korte vaste periode als dat moment niet is meegegeven (bv. handmatige test)."""
    if opent:
        return opent + POLL_GRACE
    return nu_nl() + timedelta(seconds=20)

async def poll_tot(check_fn, deadline):
    while True:
        resultaat = await check_fn()
        if resultaat:
            return resultaat
        if nu_nl() >= deadline:
            return None
        await asyncio.sleep(POLL_INTERVAL)

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


async def klik_volgende(page, verwachte_url_deel=None):
    """Klik de Volgende-knop en verifieer optioneel dat de URL het verwachte deel bevat."""
    from playwright.async_api import TimeoutError as PWTimeout
    url_voor = page.url
    gelukt = False

    try:
        btn = page.get_by_role("button", name="Volgende")
        if await btn.count() > 0:
            await btn.last.click(timeout=8000)
            await page.wait_for_load_state("load", timeout=15000)
            await asyncio.sleep(0.5)
            print("  Volgende: OK")
            gelukt = True
    except PWTimeout:
        pass

    if not gelukt:
        try:
            btn = page.locator("button").filter(has_text="Volgende").last
            await btn.click(timeout=8000)
            await page.wait_for_load_state("load", timeout=15000)
            await asyncio.sleep(0.5)
            print("  Volgende: OK (filter)")
            gelukt = True
        except PWTimeout:
            pass

    if not gelukt:
        try:
            await page.evaluate(
                "() => { const knoppen = [...document.querySelectorAll('button')]; for (const k of knoppen.reverse()) { if ((k.textContent||'').includes('Volgende')) { k.click(); return; } } }"
            )
        except Exception as e:
            # "Execution context was destroyed" = klik triggerde navigatie, dat is prima
            if "context was destroyed" not in str(e).lower() and "execution context" not in str(e).lower():
                raise
            print("  Volgende: navigatie gedetecteerd (OK)")
        await page.wait_for_load_state("load", timeout=15000)
        await asyncio.sleep(0.5)
        print("  Volgende: OK (JS)")
        gelukt = True

    # URL-verificatie: check of pagina vooruitgegaan is
    url_na = page.url
    if url_na == url_voor:
        raise RuntimeError("Pagina niet vooruitgegaan na klikken Volgende (URL: " + url_na + ")")

    # Optioneel: check of URL het verwachte deel bevat
    if verwachte_url_deel and verwachte_url_deel not in url_na:
        raise RuntimeError(
            "Onverwachte URL na Volgende: verwacht '" + verwachte_url_deel + "' maar kreeg: " + url_na
        )


async def check_en_klik_baan(page, baan_volgorde, uur, tijd_str):
    """Kijkt in de DOM welke van de voorkeursbanen nu niet-disabled is. De cel
    zelf is een lege wrapper (onclick=""); de echte selectie zit in een
    <select data-court="..."> erin, dus die kiezen we via Playwright's
    select_option (vuurt het change-event dat de site nodig heeft)."""
    dag_nummers = {"F": "6", "G": "7", "H": "8", "I": "9"}
    for baan in baan_volgorde:
        dagNr = dag_nummers[baan]
        info = await page.evaluate(
            """([dagNr, uur]) => {
                const cel = document.querySelector('#day' + dagNr + ' div[data-hour="' + uur + '"]');
                if (!cel) return { gevonden: false };
                if (cel.className.includes('disabled')) return { gevonden: true, disabled: true };
                const sel = cel.querySelector('select');
                const opties = sel ? Array.from(sel.options).map(o => ({v: o.value, t: o.textContent.trim()})) : null;
                return { gevonden: true, disabled: false, selectAanwezig: !!sel, selectOpties: opties };
            }""",
            [dagNr, uur],
        )
        if info.get("disabled") or not info.get("gevonden") or not info.get("selectAanwezig"):
            continue

        opties = info.get("selectOpties") or []

        gekozen_value = None
        for o in opties:
            if tijd_str in o["t"]:
                gekozen_value = o["v"]
                break
        if gekozen_value is None:
            for o in opties:
                if o["v"]:
                    gekozen_value = o["v"]
                    break
        if gekozen_value is None:
            continue

        select_locator = page.locator('#day' + dagNr + ' div[data-hour="' + uur + '"] select')
        await select_locator.select_option(value=gekozen_value, timeout=3000)

        na_waarde = await page.evaluate(
            """([dagNr, uur]) => {
                const sel = document.querySelector('#day' + dagNr + ' div[data-hour="' + uur + '"] select');
                return sel ? sel.value : null;
            }""",
            [dagNr, uur],
        )
        if na_waarde == gekozen_value:
            return baan
    return None


async def voeg_introducee_toe(page, naam, email):
    """Klik op 'Introducé toevoegen', vul naam + email in #guestModal, klik Toevoegen."""
    print("  Introducé toevoegen: " + naam)
    try:
        # ── Stap 1: open de modal via JS (zelfde als onclick in de HTML) ──────
        await page.evaluate("() => $('#guestModal').modal('show')")
        print("  Modal geopend")

        # ── Stap 2: wacht tot #guestModal zichtbaar is ────────────────────────
        modal = page.locator("#guestModal")
        await modal.wait_for(state="visible", timeout=6000)
        await asyncio.sleep(0.5)

        # ── Stap 3: naam invullen — eerste input in de modal ──────────────────
        naam_input = modal.locator("input").first
        await naam_input.wait_for(state="visible", timeout=4000)
        await naam_input.click()
        await naam_input.fill(naam)
        print("  Naam ingevuld: " + naam)
        await asyncio.sleep(0.2)

        # ── Stap 4: email invullen — tweede input in de modal ─────────────────
        email_input = modal.locator("input").nth(1)
        await email_input.click()
        await email_input.fill(email)
        print("  Email ingevuld: " + email)
        await asyncio.sleep(0.2)

        # ── Stap 5: klik "Toevoegen" knop in de modal ─────────────────────────
        toevoegen_btn = modal.locator("button").filter(has_text="Toevoegen")
        await toevoegen_btn.click(timeout=5000)
        await asyncio.sleep(1.5)

        # Wacht tot modal dicht is
        await modal.wait_for(state="hidden", timeout=5000)
        print("  + Introducé toegevoegd: " + naam)
        return True
    except Exception as e:
        print("  FOUT bij introducé toevoegen: " + str(e)[:100])
        return False


async def reserveer(speeltijd, baan_volgorde, partners):
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    tijd_str  = speeltijd.strftime("%H:%M")
    datum_dag = str(speeltijd.day)
    dagdeel   = bepaal_dagdeel(speeltijd)
    opent     = parse_opent_iso(OPENT_ISO)

    dag_afkortingen = ["", "ma", "di", "wo", "do", "vr", "za", "zo"]
    zoek_tekst      = dag_afkortingen[speeltijd.isoweekday()] + " " + datum_dag

    async with async_playwright() as p:
        print("Browser openen...")
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        session_state = parse_session_state(SESSION_STATE_JSON)
        context_opties = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
        if session_state:
            context_opties["storage_state"] = session_state
        context = await browser.new_context(**context_opties)

        page = await context.new_page()

        try:
            async def accepteer_cookie_banner():
                try:
                    btn = page.locator("button:has-text('Accepteer'), button:has-text('Accept')")
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        await asyncio.sleep(0.5)
                        print("  Cookie-banner geaccepteerd")
                except Exception:
                    pass

            # Stap 0: Inloggen — probeer eerst de bewaarde sessie (geen nieuw inlog-event)
            # Let op: dit vervangt alleen het invullen van het inlogformulier. De navigatie
            # erna (tab "Baan reserveringen" + knop "Baan afhangen") blijft nodig om de
            # reserveringswizard op te starten — direct naar /me/ReservationsPlayers linken
            # slaat die wizard-state over en levert een 404 op (bug: gebeurde bij elke run
            # sinds sessie-hergebruik werd toegevoegd).
            ingelogd_via_sessie = False
            if session_state:
                print("Probeer bewaarde sessie (KNLTB_SESSION_STATE)...")
                try:
                    await page.goto(WEBSITE, wait_until="domcontentloaded", timeout=30000)
                    await accepteer_cookie_banner()
                    if await page.locator('input[type="password"]').count() == 0:
                        ingelogd_via_sessie = True
                        print("  Bewaarde sessie werkt nog - geen nieuwe login nodig")
                    else:
                        print("  Bewaarde sessie verlopen - normaal inloggen")
                except Exception as e:
                    print("  Bewaarde sessie mislukt: " + str(e)[:80] + " - normaal inloggen")

            if not ingelogd_via_sessie:
                print("Inloggen...")
                await page.goto(WEBSITE, wait_until="domcontentloaded", timeout=60000)
                await accepteer_cookie_banner()
                try:
                    await page.select_option("select", label="Bondsnummer")
                except Exception:
                    pass
                await asyncio.sleep(0.3)
                await page.locator('input[type="text"]').first.fill(GEBRUIKERSNUMMER)
                await page.fill('input[type="password"]', WACHTWOORD)
                login_knop = page.locator("button:has-text('Log in'), button:has-text('Inloggen')").first
                await login_knop.click(timeout=15000)
                await page.wait_for_load_state("load", timeout=20000)
                print("  Ingelogd! URL: " + page.url)

            # Stap 1+2: partners-stap bereiken (site redirect na login automatisch)
            await asyncio.sleep(1)
            print("  Na login URL: " + page.url)

            if "/me/Reservations" not in page.url:
                print("Klik Baan reserveringen tab...")
                for sel in ["a:has-text('Baan reserveringen')", "text=Baan reserveringen"]:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.click(timeout=8000)
                            await page.wait_for_load_state("load", timeout=10000)
                            print("  Tab geklikt: " + sel)
                            break
                    except Exception:
                        continue
                await asyncio.sleep(0.5)

            # Klik "Baan afhangen" als die zichtbaar is (opent de reserveringswizard)
            if "/me/ReservationsPlayers" not in page.url:
                await accepteer_cookie_banner()
                print("Klik Baan afhangen...")
                for sel in ["text=Baan afhangen", "a:has-text('Baan afhangen')",
                            "button:has-text('Baan afhangen')"]:
                    try:
                        el = page.locator(sel).first
                        if await el.count() > 0:
                            await el.click(timeout=8000)
                            await page.wait_for_load_state("load", timeout=10000)
                            print("  Baan afhangen geklikt: " + sel)
                            break
                    except Exception:
                        continue

            await accepteer_cookie_banner()
            await asyncio.sleep(1)
            print("  Op: " + page.url)

            # Debug-screenshot partners-pagina
            await page.screenshot(path="/tmp/partners_debug.png")

            # Stap 3: Partners
            print("Partners: " + str(partners))
            for partner in partners:
                if partner.startswith("+"):
                    introducee_naam = partner[1:].strip()
                    await voeg_introducee_toe(page, introducee_naam, INTRODUCEE_EMAIL)
                    await asyncio.sleep(0.5)
                    continue

                toegevoegd = False

                # Strategie A: JS — zoek naam in alle elementen, klik + button
                try:
                    resultaat = await page.evaluate("""
                        (naam) => {
                            const els = Array.from(document.querySelectorAll('*'));
                            for (const el of els) {
                                const t = (el.innerText || el.textContent || '').trim();
                                if (t.toLowerCase() === naam.toLowerCase() || t.toLowerCase().startsWith(naam.toLowerCase() + '\\n') || t.toLowerCase().endsWith('\\n' + naam.toLowerCase())) {
                                    // Zoek button in parent-keten (ook siblings)
                                    let cur = el;
                                    for (let i = 0; i < 8; i++) {
                                        // Button in huidig element
                                        const btn = cur.querySelector('button, [onclick], [role="button"]');
                                        if (btn && btn !== el) { btn.click(); return 'child:' + cur.className; }
                                        // Sibling button
                                        let sib = cur.nextElementSibling;
                                        while (sib) {
                                            if (sib.tagName === 'BUTTON' || sib.getAttribute('role') === 'button') {
                                                sib.click(); return 'sibling';
                                            }
                                            const sbtn = sib.querySelector('button, [role="button"]');
                                            if (sbtn) { sbtn.click(); return 'sib-child'; }
                                            sib = sib.nextElementSibling;
                                        }
                                        if (!cur.parentElement) break;
                                        cur = cur.parentElement;
                                    }
                                }
                            }
                            return null;
                        }
                    """, partner)
                    if resultaat:
                        await asyncio.sleep(1)
                        print("  + " + partner + " (JS: " + str(resultaat) + ")")
                        toegevoegd = True
                except Exception as e:
                    print("  JS-strategie fout: " + str(e)[:60])

                # Strategie B: zoekbalk
                if not toegevoegd:
                    naam_getypt = titel_case_naam(partner)
                    try:
                        for sel in ["input[placeholder*='Speler']", "input[placeholder*='speler']",
                                    "#searchPlayerText", "input[type='search']", "input[type='text']"]:
                            if await page.locator(sel).count() > 0:
                                zoek = page.locator(sel).first
                                break
                        else:
                            zoek = page.locator("input").first
                        await zoek.click()
                        await zoek.fill("")
                        await zoek.type(naam_getypt, delay=80)
                        print("  Getypt: " + naam_getypt)
                        await asyncio.sleep(2.5)

                        # Breed op tekst matchen i.p.v. blind vertrouwen op 1 geraden CSS-class
                        # (de dropdown-markup van de site is al eens zonder aankondiging veranderd)
                        resultaat = await page.evaluate("""
                            (naam) => {
                                const stopwoorden = ['van','der','den','de','het','ter','ten','te'];
                                const woorden = naam.toLowerCase().split(/\\s+/).filter(w => w.length > 1 && !stopwoorden.includes(w));
                                const kandidaten = Array.from(document.querySelectorAll(
                                    'li, [role="option"], [class*=result], [class*=suggestion], '
                                    + '[class*=autocomplete], [class*=dropdown], [class*=typeahead], [class*=item], [class*=option]'
                                ));
                                for (const el of kandidaten) {
                                    const t = (el.innerText || el.textContent || '').toLowerCase();
                                    if (t.length < 200 && woorden.length > 0 && woorden.every(w => t.includes(w))) {
                                        el.click();
                                        return el.className || el.tagName;
                                    }
                                }
                                return null;
                            }
                        """, naam_getypt)
                        if resultaat:
                            await asyncio.sleep(1)
                            print("  + " + partner + " (zoekbalk, match: " + str(resultaat)[:60] + ")")
                            toegevoegd = True
                        else:
                            dropdown = page.locator(
                                ".ui-autocomplete li, [class*=autocomplete] li, "
                                "[class*=result] li, [class*=suggestion] li, [class*=dropdown] li"
                            ).first
                            await dropdown.wait_for(state="visible", timeout=8000)
                            await dropdown.click()
                            print("  + " + partner + " (zoekbalk)")
                            toegevoegd = True
                    except Exception as e:
                        print("  Zoek-strategie fout: " + str(e)[:80])

                if not toegevoegd:
                    print("  WAARSCHUWING: " + partner + " niet gevonden")
                    try:
                        bestandsnaam = "/tmp/partner_niet_gevonden_" + partner.replace(" ", "_") + ".png"
                        await page.screenshot(path=bestandsnaam)
                        print("  Diagnose-screenshot: " + bestandsnaam)
                    except Exception:
                        pass
                await asyncio.sleep(0.5)

            # Volgende na partners — verwacht /me/ReservationsDay
            await klik_volgende(page, verwachte_url_deel="/me/ReservationsDay")
            print("  URL na partners: " + page.url)

            # Stap 4: Dag + dagdeel
            print("Dag: " + zoek_tekst + " dagdeel: " + dagdeel)
            await asyncio.sleep(1)

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

            datum_str = speeltijd.strftime("%Y-%m-%d")

            async def daypart_beschikbaar():
                try:
                    return await page.evaluate("""
                        ([datum, dagdeelTekst]) => {
                            const els = document.querySelectorAll('.daypart:not(.disabled)');
                            for (const el of els) {
                                const d = el.dataset.date || el.getAttribute('data-date') || '';
                                if (!d.startsWith(datum)) continue;
                                const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                                if (t === dagdeelTekst.toLowerCase()) {
                                    el.click();
                                    return d + '|' + el.className;
                                }
                            }
                            return null;
                        }
                    """, [datum_str, dagdeel])
                except Exception as e:
                    if "context was destroyed" in str(e).lower() or "execution context" in str(e).lower():
                        return None
                    raise

            resultaat = await poll_tot(daypart_beschikbaar, poll_deadline(opent))
            if not resultaat:
                raise RuntimeError("DAG NIET GEVONDEN IN KALENDER: " + zoek_tekst + " / " + dagdeel)
            print("  Dagdeel geklikt via data-date: " + str(resultaat))
            await asyncio.sleep(0.5)

            # Volgende na dag — verwacht /me/ReservationsCourt
            await klik_volgende(page, verwachte_url_deel="/me/ReservationsCourt")
            print("  URL na dag: " + page.url)

            # Stap 5: Tijdcel - poll de voorkeursbanen en klik zodra er een vrij is
            print("Tijdslot " + tijd_str + " voorkeur: " + str(baan_volgorde))
            uur = str(speeltijd.hour)

            async def baan_beschikbaar():
                return await check_en_klik_baan(page, baan_volgorde, uur, tijd_str)

            gekozen_baan = await poll_tot(baan_beschikbaar, poll_deadline(opent))
            if not gekozen_baan:
                raise RuntimeError("GEEN BAAN BESCHIKBAAR - reservering afgebroken")
            print("  Baan " + gekozen_baan + " geselecteerd!")
            await asyncio.sleep(0.5)

            # Volgende na baan — verwacht /me/ReservationsConfirm
            await klik_volgende(page, verwachte_url_deel="/me/ReservationsConfirm")
            print("  URL na baan: " + page.url)

            # Stap 6: Bevestigen
            print("Bevestigen...")
            await asyncio.sleep(1)
            await accepteer_cookie_banner()
            await asyncio.sleep(0.5)

            bevestigd = False
            for sel in ["#confirmReservationButton", "button:has-text('Bevestigen')",
                        "a.btn-primary", "a[data-url*=SaveReservation]"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=3000):
                        await el.click()
                        try:
                            await page.wait_for_url(
                                lambda url: "ReservationsConfirm" not in url,
                                timeout=10000
                            )
                        except Exception:
                            await page.wait_for_load_state("load", timeout=10000)
                        print("  Bevestigen OK: " + sel)
                        bevestigd = True
                        break
                except Exception:
                    continue
            if not bevestigd:
                raise RuntimeError("BEVESTIGEN MISLUKT: knop niet gevonden")

            # Stap 7: Verifieer bevestiging
            await asyncio.sleep(2)
            url_na = page.url
            print("  URL na bevestiging: " + url_na)
            pagina = (await page.content()).lower()

            if "/me/Reservations" in url_na and "Confirm" not in url_na:
                pass  # URL veranderd naar succes-pagina
            elif "ReservationsConfirm" in url_na:
                # AJAX-bevestiging: URL blijft zelfde. Check op echte foutmeldingen.
                fout_woorden = ["mislukt", "fout", "error", "niet gelukt", "niet beschikbaar",
                                "not available", "unavailable", "al gereserveerd"]
                if any(w in pagina for w in fout_woorden):
                    raise RuntimeError("RESERVERING MISLUKT: fout op pagina (url=" + url_na + ")")
                print("  AJAX-bevestiging: geen fout gevonden, succes aangenomen")
            else:
                raise RuntimeError("ONVERWACHTE URL na bevestiging: " + url_na)

            baan_naam = "Baan " + gekozen_baan
            eind      = speeltijd + timedelta(hours=1)
            print("KLAAR! " + baan_naam + " op " + speeltijd.strftime('%d-%m-%Y') + " om " + tijd_str + "-" + eind.strftime('%H:%M'))

        except Exception as exc:
            # Bij elke fout: screenshot maken voor diagnose
            try:
                await page.screenshot(path="/tmp/padel_screenshot.png")
                print("  Screenshot opgeslagen: /tmp/padel_screenshot.png")
            except Exception as screenshot_exc:
                print("  Screenshot mislukt: " + str(screenshot_exc)[:80])
            raise


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

    opent = parse_opent_iso(OPENT_ISO)

    print("Speeltijd:     " + speeltijd.strftime('%d-%m-%Y om %H:%M') + " (NL tijd)")
    print("Baan volgorde: " + str(baan_volgorde))
    print("Partners:      " + (", ".join(partners) if partners else "(geen)"))
    print("Nu:            " + nu_nl().strftime('%d-%m-%Y om %H:%M:%S') + " (NL tijd)")
    print("Opent:         " + (opent.strftime('%d-%m-%Y om %H:%M:%S') if opent else "(onbekend - handmatige test?)"))
    print()

    await reserveer(speeltijd, baan_volgorde, partners)


if __name__ == "__main__":
    asyncio.run(main())
