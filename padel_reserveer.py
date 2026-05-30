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

    dag_afkortingen = ["", "ma", "di", "wo", "do", "vr", "za", "zo"]
    zoek_tekst      = dag_afkortingen[speeltijd.isoweekday()] + " " + datum_dag

    async with async_playwright() as p:
        print("Browser openen...")
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

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

            # Stap 0: Inloggen
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
                                if (t === naam || t.startsWith(naam + '\\n') || t.endsWith('\\n' + naam)) {
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
                        await zoek.type(partner, delay=80)
                        print("  Getypt: " + partner)
                        await asyncio.sleep(2.5)
                        dropdown = page.locator(
                            ".ui-autocomplete li, [class*=autocomplete] li, "
                            "[class*=result] li, [class*=suggestion] li, [class*=dropdown] li"
                        ).first
                        await dropdown.wait_for(state="visible", timeout=5000)
                        await dropdown.click()
                        print("  + " + partner + " (zoekbalk)")
                        toegevoegd = True
                    except Exception as e:
                        print("  Zoek-strategie fout: " + str(e)[:80])

                if not toegevoegd:
                    print("  WAARSCHUWING: " + partner + " niet gevonden")
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

            dag_geklikt = False

            # Strategie 1: JS via data-date + dagdeel-tekst (meest betrouwbaar)
            try:
                datum_str = speeltijd.strftime("%Y-%m-%d")
                resultaat = await page.evaluate("""
                    ([datum, dagdeelTekst]) => {
                        // Probeer eerst niet-disabled
                        for (const sel of ['.daypart:not(.disabled)', '.daypart', '[class*=daypart]']) {
                            const els = document.querySelectorAll(sel);
                            for (const el of els) {
                                const d = el.dataset.date || el.getAttribute('data-date') || '';
                                if (!d.startsWith(datum)) continue;
                                const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                                if (t === dagdeelTekst.toLowerCase()) {
                                    el.click();
                                    return sel + '|' + d + '|' + el.className;
                                }
                            }
                        }
                        return null;
                    }
                """, [datum_str, dagdeel])
                if resultaat:
                    print("  Dagdeel geklikt via data-date: " + str(resultaat))
                    await asyncio.sleep(0.8)
                    dag_geklikt = True
                else:
                    print("  data-date: geen match voor " + datum_str + "/" + dagdeel)
            except Exception as e:
                print("  data-date strategie fout: " + str(e)[:80])

            if not dag_geklikt:
                raise RuntimeError("DAG NIET GEVONDEN IN KALENDER: " + zoek_tekst + " / " + dagdeel)

            await asyncio.sleep(0.5)

            # Volgende na dag — verwacht /me/ReservationsCourt
            await klik_volgende(page, verwachte_url_deel="/me/ReservationsCourt")
            print("  URL na dag: " + page.url)

            # Stap 5: Tijdcel - probeer banen in volgorde
            print("Tijdslot " + tijd_str + " voorkeur: " + str(baan_volgorde))
            gekozen_baan = None
            for baan in baan_volgorde:
                if await probeer_tijdcel(page, baan, speeltijd):
                    gekozen_baan = baan
                    break

            if not gekozen_baan:
                raise RuntimeError("GEEN BAAN BESCHIKBAAR - reservering afgebroken")

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

    print("Speeltijd:     " + speeltijd.strftime('%d-%m-%Y om %H:%M') + " (NL tijd)")
    print("Baan volgorde: " + str(baan_volgorde))
    print("Partners:      " + (", ".join(partners) if partners else "(geen)"))
    print("Nu:            " + nu_nl().strftime('%d-%m-%Y om %H:%M:%S') + " (NL tijd)")
    print()

    await reserveer(speeltijd, baan_volgorde, partners)


if __name__ == "__main__":
    asyncio.run(main())
