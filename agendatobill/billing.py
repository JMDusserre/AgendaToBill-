import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

PARIS = ZoneInfo("Europe/Paris")


def fold_name(value):
    """Nom comparable : minuscules, sans accents, préfixe « cours » retiré une fois."""
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.lower().replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^cours\b\s*", "", text).strip()
    return text


def ensure_aware(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=PARIS)
    return dt


def as_utc(dt):
    return ensure_aware(dt).astimezone(timezone.utc)


def duration_hours(start, end):
    return (as_utc(end) - as_utc(start)).total_seconds() / 3600


def event_status(start, end, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start_utc = as_utc(start)
    end_utc = as_utc(end)
    if end_utc <= now:
        return "terminé"
    if start_utc <= now < end_utc:
        return "en cours"
    return "à venir"


def paris_date(dt):
    return as_utc(dt).astimezone(PARIS).strftime("%d/%m/%Y")


def expand_occurrences(start, end, rrule_text=None, exdates=None, window_start=None, window_end=None):
    """Déplie une récurrence dans la fenêtre demandée. Sans règle, rend le créneau s'il la croise."""
    start = ensure_aware(start)
    end = ensure_aware(end)
    duration = end - start
    if duration <= timedelta(0):
        return []

    window_start = ensure_aware(window_start) if window_start is not None else start
    window_end = ensure_aware(window_end) if window_end is not None else end
    excluded = set()
    for item in exdates or []:
        if isinstance(item, datetime):
            excluded.add(as_utc(ensure_aware(item)))

    if not rrule_text:
        if as_utc(start) < as_utc(window_end) and as_utc(end) > as_utc(window_start):
            return [(start, end)]
        return []

    rule = rrulestr(str(rrule_text).removeprefix("RRULE:"), dtstart=start)
    occurrences = []
    for occurrence in rule.between(window_start, window_end, inc=True):
        if occurrence.tzinfo is None:
            occurrence = occurrence.replace(tzinfo=start.tzinfo)
        if as_utc(occurrence) in excluded:
            continue
        occurrences.append((occurrence, occurrence + duration))
    return occurrences


def should_keep_previous_events(new_count, previous_raw):
    return new_count == 0 and bool((previous_raw or "").strip())


def event_key(start, end, raw_name):
    return f"{as_utc(start).isoformat()}|{as_utc(end).isoformat()}|{fold_name(raw_name)}"


def parse_event_line(line):
    parts = line.split("|")
    if len(parts) < 3 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(f"Ligne d'événement illisible : {line}")
    start = datetime.fromisoformat(parts[0].strip())
    end = datetime.fromisoformat(parts[1].strip())
    raw_name = "|".join(parts[2:]).strip()
    if not raw_name:
        raise ValueError(f"Nom manquant : {line}")
    return start, end, raw_name


def match_student(raw_name, students):
    folded = fold_name(raw_name)
    if not folded:
        return None, "Nom d'élève vide."
    matches = [key for key in students if fold_name(key) == folded]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"Plusieurs fiches pour « {folded} ». Garde une seule fiche avant de facturer."
    return None, f"Élève inconnu : {folded}. Ajoute-le dans Clients (aucun tarif par défaut)."


def display_name(student_key):
    return student_key.strip().title()


def name_token(name):
    return re.sub(r"\s+", "_", (name or "").strip())


def invoice_basename(client_name, start, end):
    token = name_token(client_name) or "client"
    start_local = as_utc(start).astimezone(PARIS)
    end_local = as_utc(end).astimezone(PARIS)
    return (
        f"Facture_{token}_{start_local.strftime('%d-%m-%Y_%H%M')}"
        f"-{end_local.strftime('%H%M')}.pdf"
    )


def file_matches_person(filename, *names):
    lowered = filename.lower()
    for name in names:
        token = name_token(name).lower()
        if not token:
            continue
        pattern = rf"facture_{re.escape(token)}_\d{{2}}-\d{{2}}-\d{{4}}"
        if re.search(pattern, lowered):
            return True
    return False
