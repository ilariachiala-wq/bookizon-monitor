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
MESI_DA_CONTROLLARE = 3

# File dove viene salvata la lista delle date disponibili trovate l'ultima volta
STATO_FILE = Path(__file__).parent / "stato_date_disponibili.json"


# =========================
# FUNZIONI
# =========================

def invia_notifica(messaggio: str) -> None:
    """Invia una notifica push tramite ntfy.sh (gratuito, nessun account richiesto)."""
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    data = messaggio.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Title", "Nuova data disponibile - Sun Bay")
    req.add_header("Priority", "high")
    req.add_header("Tags", "beach_umbrella")
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
        page.goto(URL, timeout=60000)

        # Apre il popup "Modifica prenotazione" -> calendario.
        # Clicca sul testo/data mostrata, che apre il datepicker Litepicker.
        page.get_by_text("Scegli una data").click()
        page.wait_for_selector(".litepicker .day-item", timeout=15000)

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

            # Passa al mese successivo, se non e' l'ultimo giro
            if mese_indice < MESI_DA_CONTROLLARE - 1:
                try:
                    page.locator(".litepicker .button-next").first.click()
                    page.wait_for_timeout(700)
                except Exception:
                    break

        browser.close()

    return date_disponibili


def controlla_una_volta() -> None:
    print(f"[{datetime.now():%H:%M:%S}] Controllo in corso...")
    date_attuali = leggi_date_disponibili()
    date_precedenti = carica_stato_precedente()

    nuove_date = date_attuali - date_precedenti

    if nuove_date:
        elenco = "\n".join(sorted(nuove_date))
        print(f"[{datetime.now():%H:%M:%S}] Trovate nuove date: {elenco}")
        invia_notifica(f"Nuove date aperte alla prenotazione:\n{elenco}")
    else:
        print(f"[{datetime.now():%H:%M:%S}] Nessuna novita'. Date disponibili attuali: {len(date_attuali)}")

    salva_stato(date_attuali)


if __name__ == "__main__":
    # Nota: qui NON c'e' un ciclo infinito. Questo script e' pensato per
    # essere eseguito UNA VOLTA ogni tot minuti da GitHub Actions (vedi
    # ISTRUZIONI.md), che si occupa lui della ripetizione programmata.
    controlla_una_volta()
