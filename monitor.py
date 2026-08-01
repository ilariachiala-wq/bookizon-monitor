"""
Monitor disponibilita' Bookizon (Sun Bay - Lido Bruno)
--------------------------------------------------------
Controlla il calendario di prenotazione e invia una notifica sul telefono
(tramite ntfy.sh) quando compare una nuova data disponibile.

Non serve modificare nulla tranne, se vuoi, il valore NTFY_TOPIC piu' sotto.
"""

import json
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# =========================
# CONFIGURAZIONE
# =========================

URL = "https://bookizon.it/web/n/sun-bay/modulo-seats/booking-engine?map_id=7"

# Nome "canale" di notifica. Deve essere lo stesso che apri nell'app ntfy sul telefono.
# Scegline uno univoco (non un nome generico), per evitare che altri lo indovinino.
NTFY_TOPIC = "Sunbay"

# Quanti mesi in avanti controllare a partire da quello corrente
MESI_DA_CONTROLLARE = 1

# File dove viene salvata la lista delle date disponibili trovate l'ultima volta
STATO_FILE = Path(__file__).parent / "stato_date_disponibili.json"


# =========================
# FUNZIONI
# =========================

def invia_notifica(messaggio: str, titolo: str = "Nuova data disponibile - Sun Bay", tags: str = "beach_umbrella") -> None:
    """Invia una notifica push tramite ntfy.sh (gratuito, nessun account richiesto)."""
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    data = messaggio.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Title", titolo)
    req.add_header("Priority", "high")
    req.add_header("Tags", tags)
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"[{datetime.now():%H:%M:%S}] Notifica inviata: {messaggio}")
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] ERRORE invio notifica: {e}")


def carica_stato_precedente() -> set:
    if STATO_FILE.exists():
        try:
            return set(json.loads(STATO_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def salva_stato(date_disponibili: set) -> None:
    STATO_FILE.write_text(
        json.dumps(sorted(date_disponibili), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def leggi_date_disponibili() -> set:
    """
    Apre la pagina con un browser reale (nascosto), apre il calendario,
    e legge quali giorni NON hanno la classe 'is-locked' (= disponibili),
    scorrendo in avanti per MESI_DA_CONTROLLARE mesi.
    """
    date_disponibili = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Blocchiamo immagini, font, fogli di stile e media: non ci servono
        # (leggiamo solo attributi HTML nascosti), e saltarli velocizza parecchio
        # il caricamento della pagina.
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("image", "font", "media", "stylesheet")
            else route.continue_(),
        )

        try:
            page.goto(URL, timeout=60000)

            # Il banner dei cookie compare ad ogni esecuzione (browser sempre "pulito"),
            # e puo' bloccare il click su "Scegli una data" se rimane visibile sopra.
            # Proviamo a chiuderlo, ma senza bloccarci se non c'e' o ha un nome diverso.
            try:
                page.locator(
                    "#iubenda-cs-accept-btn, .iubenda-cs-accept-btn, "
                    "button:has-text('Accetta'), button:has-text('Accetto'), "
                    "button:has-text('OK')"
                ).first.click(timeout=2000)
                page.wait_for_timeout(300)
            except Exception:
                pass  # nessun banner trovato, o gia' chiuso: va bene cosi'

            # Apre il popup "Modifica prenotazione" -> calendario.
            page.get_by_text("Scegli una data").click(timeout=30000)
            page.wait_for_selector(".litepicker .day-item", state="attached", timeout=15000)
            page.wait_for_timeout(500)  # piccola pausa per far assestare le animazioni

            mese_precedente_testo = None

            for mese_indice in range(MESI_DA_CONTROLLARE):
                # Legge l'intestazione mese/anno mostrata, es: "agosto 2026"
                try:
                    intestazione = page.locator(".litepicker .month-item-header").first.inner_text()
                except Exception:
                    intestazione = f"mese #{mese_indice + 1}"

                giorni = page.locator(".litepicker .day-item").all()
                for giorno in giorni:
                    classe = giorno.get_attribute("class") or ""
                    data_time = giorno.get_attribute("data-time")
                    if "is-locked" not in classe and data_time:
                        # data-time e' un timestamp in millisecondi
                        ts = int(data_time) / 1000
                        data_leggibile = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                        date_disponibili.add(f"{data_leggibile} ({intestazione})")

                # Passa al mese successivo, se non e' l'ultimo giro.
                # Verifichiamo che il mese sia DAVVERO cambiato prima di continuare,
                # altrimenti rischiamo di leggere due volte lo stesso mese e saltarne
                # uno (il che ci ha gia' fatto perdere una data disponibile in passato).
                if mese_indice < MESI_DA_CONTROLLARE - 1:
                    mese_precedente_testo = intestazione
                    cambiato = False
                    for tentativo in range(3):
                        try:
                            page.locator(".litepicker .button-next").first.click(force=True)
                            page.wait_for_timeout(900)
                            nuova_intestazione = page.locator(".litepicker .month-item-header").first.inner_text()
                            if nuova_intestazione != mese_precedente_testo:
                                cambiato = True
                                break
                        except Exception as e:
                            print(f"[{datetime.now():%H:%M:%S}] Tentativo {tentativo + 1}: click 'mese successivo' fallito: {e}")
                            page.wait_for_timeout(1000)

                    if not cambiato:
                        print(
                            f"[{datetime.now():%H:%M:%S}] ATTENZIONE: non sono riuscito a passare al mese "
                            f"successivo dopo '{mese_precedente_testo}'. Mesi successivi NON controllati in questo giro."
                        )
                        break

        except Exception:
            # Se qualcosa va storto, salviamo uno screenshot della pagina
            # cosi' possiamo vedere cosa stava mostrando il sito in quel momento
            try:
                screenshot_path = Path(__file__).parent / "errore_screenshot.png"
                page.screenshot(path=str(screenshot_path))
                print(f"[{datetime.now():%H:%M:%S}] Screenshot dell'errore salvato in {screenshot_path}")
            except Exception as e2:
                print(f"[{datetime.now():%H:%M:%S}] Non sono riuscito a salvare lo screenshot: {e2}")
            raise

        finally:
            browser.close()

    return date_disponibili


def _estrai_data(voce: str) -> "datetime.date | None":
    """Estrae la data (YYYY-MM-DD) dall'inizio di una voce tipo '2026-08-01 (agosto2026)'."""
    try:
        return datetime.strptime(voce.split(" ")[0], "%Y-%m-%d").date()
    except Exception:
        return None


def controlla_una_volta() -> None:
    print(f"[{datetime.now():%H:%M:%S}] Controllo in corso...")

    date_attuali = None
    ultimo_errore = None
    for tentativo in range(2):
        try:
            date_attuali = leggi_date_disponibili()
            break
        except Exception as e:
            ultimo_errore = e
            print(f"[{datetime.now():%H:%M:%S}] Tentativo {tentativo + 1}/2 fallito: {e}")
            if tentativo == 0:
                print(f"[{datetime.now():%H:%M:%S}] Riprovo subito una seconda volta...")

    if date_attuali is None:
        print(f"[{datetime.now():%H:%M:%S}] Entrambi i tentativi falliti. Interrompo questo giro.")
        raise ultimo_errore

    date_precedenti = carica_stato_precedente()

    if len(date_attuali) == 0:
        print(f"[{datetime.now():%H:%M:%S}] ATTENZIONE: nessuna data letta in questo giro (possibile problema tecnico).")

    nuove_date = date_attuali - date_precedenti

    # Date che c'erano prima e ora non ci sono piu'. Escludiamo pero' quelle
    # ormai nel passato: se "ieri" sparisce dal calendario e' normale (il tempo
    # e' passato), non vuol dire che qualcuno l'abbia richiusa attivamente.
    oggi = datetime.utcnow().date()
    date_sparite = date_precedenti - date_attuali
    date_richiuse = set()
    for voce in date_sparite:
        data = _estrai_data(voce)
        if data is None or data >= oggi:
            date_richiuse.add(voce)

    if nuove_date:
        elenco = "\n".join(sorted(nuove_date))
        print(f"[{datetime.now():%H:%M:%S}] Trovate nuove date: {elenco}")
        invia_notifica(f"Nuove date aperte alla prenotazione:\n{elenco}")

    if date_richiuse:
        elenco = "\n".join(sorted(date_richiuse))
        print(f"[{datetime.now():%H:%M:%S}] Date richiuse: {elenco}")
        invia_notifica(f"Date NON piu' disponibili:\n{elenco}", titolo="Date richiuse - Sun Bay", tags="no_entry_sign")

    if not nuove_date and not date_richiuse:
        print(f"[{datetime.now():%H:%M:%S}] Nessuna novita'. Date disponibili attuali: {len(date_attuali)}")

    salva_stato(date_attuali)


if __name__ == "__main__":
    # Nota: qui NON c'e' un ciclo infinito. Questo script e' pensato per
    # essere eseguito UNA VOLTA ogni tot minuti da GitHub Actions (vedi
    # ISTRUZIONI.md), che si occupa lui della ripetizione programmata.
    controlla_una_volta()
