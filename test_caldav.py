import caldav
from datetime import datetime

USERNAME = "jean-michel.dusserre@hotmail.fr"
PASSWORD = "REMOVED"
CALDAV_URL = "https://caldav.icloud.com/"

def test_icloud_connection():
    try:
        client = caldav.DAVClient(
            url=CALDAV_URL,
            username=USERNAME,
            password=PASSWORD
        )
        
        principal = client.principal()
        calendars = principal.calendars()
        print(f"✅ Connexion réussie ! {len(calendars)} calendrier(s) trouvé(s).")
        
        for calendar in calendars:
            # Utilisation de la nouvelle méthode recommandée pour le nom
            print(f"- Calendrier : {calendar.get_display_name()}")
            events = calendar.events()
            for event in events:
                try:
                    # On extrait le résumé (titre) via le composant iCalendar
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else ""
                    dtstart = str(vevent.dtstart.value) if hasattr(vevent, 'dtstart') else ""
                    
                    if "cours" in summary.lower():
                        print(f"   🎸 Trouvé : {summary} (Début : {dtstart})")
                except Exception:
                    continue
                    
    except Exception as e:
        print(f"❌ Erreur de connexion CalDAV : {e}")

if __name__ == "__main__":
    test_icloud_connection()