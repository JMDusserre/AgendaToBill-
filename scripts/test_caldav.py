import os
import sys
from pathlib import Path

import caldav
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agendatobill.paths import env_file

load_dotenv(env_file(), override=True)

CALDAV_URL = "https://caldav.icloud.com/"


def test_icloud_connection():
    username = (os.environ.get("ICLOUD_EMAIL") or "").strip()
    password = (os.environ.get("ICLOUD_PASSWORD") or "").strip()
    if not username or not password:
        raise SystemExit("Renseigne ICLOUD_EMAIL et ICLOUD_PASSWORD dans .env.")

    try:
        client = caldav.DAVClient(url=CALDAV_URL, username=username, password=password)
        principal = client.principal()
        calendars = principal.calendars()
        print(f"Connexion reussie. {len(calendars)} calendrier(s) trouve(s).")

        for calendar in calendars:
            print(f"- Calendrier : {calendar.get_display_name()}")
            for event in calendar.events():
                try:
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, "summary") else ""
                    dtstart = str(vevent.dtstart.value) if hasattr(vevent, "dtstart") else ""
                    if "cours" in summary.lower():
                        print(f"   Trouve : {summary} (debut : {dtstart})")
                except Exception:
                    continue
    except Exception as exc:
        print(f"Erreur de connexion CalDAV : {exc}")


if __name__ == "__main__":
    test_icloud_connection()
