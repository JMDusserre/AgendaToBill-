import os
import re
import zlib
from datetime import datetime, timezone

from fpdf import FPDF
from sqlalchemy import func, text

from agendatobill.billing import (
    PARIS,
    display_name,
    duration_hours,
    event_key,
    invoice_basename,
    match_student,
    paris_date,
    parse_event_line,
)
from agendatobill.models import (
    RAW_EVENTS_KEY,
    InvoiceDocument,
    InvoicedEvent,
    cache_text,
    db,
    invoiced_keys,
    students_map,
)

RECAP_FILENAME = "recapitulatif_urssaf.txt"
FRENCH_MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]
_AMOUNT_IN_PDF = re.compile(r"Montant total .{0,30}?([0-9]+\.[0-9]{2}) EUR")
_COURSE_STAMP = re.compile(r"(\d{2})-(\d{2})-(\d{4})(?:_(\d{4}))?")
_NUMBER_SUFFIX = re.compile(r"_n\d+(?=\.pdf$)", re.IGNORECASE)
_INVOICE_LABEL = re.compile("Facture n° \\d+".encode("latin-1"))


def pdf_plain_text(content):
    raw = bytes(content or b"")
    chunks = [raw]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        data = match.group(1)
        try:
            chunks.append(zlib.decompress(data))
        except zlib.error:
            chunks.append(data)
    return b"\n".join(chunks).decode("latin-1", "replace")


def course_moment(filename, created_at=None):
    """Date du cours imprimée dans le nom du fichier, sinon la date d'enregistrement."""
    match = _COURSE_STAMP.search(filename or "")
    if match:
        day, month, year, hm = match.groups()
        hour = int(hm[:2]) if hm else 0
        minute = int(hm[2:]) if hm else 0
        try:
            return datetime(int(year), int(month), int(day), hour, minute, tzinfo=PARIS)
        except ValueError:
            pass
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(PARIS)


def filename_with_number(filename, number):
    if _NUMBER_SUFFIX.search(filename or ""):
        return _NUMBER_SUFFIX.sub(f"_n{number}", filename, count=1)
    stem, ext = os.path.splitext(filename)
    return f"{stem}_n{number}{ext}"


def replace_invoice_label(content, number):
    """Met à jour « Facture n° … » sans changer la longueur du flux PDF."""
    label = f"Facture n° {number}".encode("latin-1")
    raw = bytes(content or b"")

    def rewrite(data):
        match = _INVOICE_LABEL.search(data)
        if not match or len(label) != len(match.group(0)):
            return data
        return data[:match.start()] + label + data[match.end():]

    changed = False

    def replace_stream(match):
        nonlocal changed
        data = match.group(1)
        prefix = match.group(0)[:match.start(1) - match.start()]
        suffix = match.group(0)[match.end(1) - match.start():]
        try:
            plain = zlib.decompress(data)
        except zlib.error:
            plain = data
            updated = rewrite(plain)
            if updated != plain:
                changed = True
                return prefix + updated + suffix
            return match.group(0)
        updated = rewrite(plain)
        if updated == plain:
            return match.group(0)
        changed = True
        return prefix + zlib.compress(updated) + suffix

    new_raw = re.sub(rb"stream\r?\n(.*?)\r?\nendstream", replace_stream, raw, flags=re.S)
    return new_raw if changed else raw


def amount_in_pdf_bytes(content):
    match = _AMOUNT_IN_PDF.search(pdf_plain_text(content))
    if not match:
        return None
    return float(match.group(1))


def pdf_text(value):
    return (value or "").encode("latin-1", "replace").decode("latin-1")


def starting_invoice_number():
    raw = (os.environ.get("STARTING_INVOICE_NUMBER") or "1").strip()
    try:
        number = int(raw)
    except ValueError:
        number = 1
    return number if number > 0 else 1


def next_invoice_number():
    current = db.session.query(func.max(InvoiceDocument.invoice_number)).scalar()
    if current is None:
        return starting_invoice_number()
    return int(current) + 1


def unique_invoice_filename(basename):
    if db.session.get(InvoiceDocument, basename) is None:
        return basename
    stem, ext = os.path.splitext(basename)
    index = 2
    while db.session.get(InvoiceDocument, f"{stem}_{index}{ext}") is not None:
        index += 1
    return f"{stem}_{index}{ext}"


def generate_pdf_invoice(student_name, date_str, duration, montant, parent="", adresse="", start=None, end=None, event_key=None):
    number = next_invoice_number()
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(200, 10, txt="FACTURE / RECU DE COURS", ln=True, align="C")
    pdf.ln(4)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(200, 8, txt=pdf_text(f"Facture n° {number}"), ln=True, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", size=11)
    pdf.cell(200, 6, txt=pdf_text("Prestataire : Jean-Michel Dusserre"), ln=True)
    pdf.cell(200, 6, txt="SIREN : 912 347 028", ln=True)
    pdf.cell(200, 6, txt=pdf_text("Dispensé de l'immatriculation au RCS et au RM"), ln=True)
    pdf.ln(15)

    pdf.set_font("Helvetica", style="B", size=12)
    client_name = parent if parent else student_name
    pdf.cell(200, 8, txt=pdf_text(f"Facturé à : {client_name}"), ln=True)

    pdf.set_font("Helvetica", size=11)
    if adresse:
        pdf.cell(200, 6, txt=pdf_text(adresse), ln=True)
    pdf.ln(10)

    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(200, 8, txt=pdf_text("Détail de la prestation :"), ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(200, 6, txt=pdf_text(f"Élève : {student_name}"), ln=True)
    pdf.cell(200, 6, txt=pdf_text(f"Date du cours : {date_str}"), ln=True)
    pdf.cell(200, 6, txt=pdf_text(f"Durée : {duration:.2f} heure(s)"), ln=True)
    pdf.ln(10)

    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(200, 10, txt=pdf_text(f"Montant total à régler : {montant:.2f} EUR"), ln=True)
    pdf.ln(5)

    pdf.set_font("Helvetica", style="I", size=10)
    pdf.cell(200, 6, txt=pdf_text("TVA non applicable, art. 293 B du CGI."), ln=True)
    pdf.cell(200, 6, txt=pdf_text("Paiement à réception par virement bancaire ou espèces."), ln=True)

    if start is not None and end is not None:
        filename = invoice_basename(client_name, start, end)
    else:
        safe_name = client_name.replace(" ", "_").replace("/", "-")
        safe_date = date_str.replace("/", "-")
        filename = f"Facture_{safe_name}_{safe_date}.pdf"

    stem, ext = os.path.splitext(filename)
    filename = unique_invoice_filename(f"{stem}_n{number}{ext}")
    payload = bytes(pdf.output())
    db.session.add(InvoiceDocument(
        filename=filename,
        content=payload,
        created_at=datetime.now(timezone.utc),
        invoice_number=number,
        montant=float(montant),
        event_key=event_key,
    ))
    return filename


def store_recap(text):
    payload = text.encode("utf-8")
    row = db.session.get(InvoiceDocument, RECAP_FILENAME)
    if row is None:
        db.session.add(InvoiceDocument(
            filename=RECAP_FILENAME,
            content=payload,
            created_at=datetime.now(timezone.utc),
        ))
        db.session.commit()
        return
    if bytes(row.content or b"") == payload:
        return
    row.content = payload
    db.session.commit()


def invoice_amount(row):
    if row.montant is not None:
        return float(row.montant)
    amount = amount_in_pdf_bytes(row.content)
    if amount is None:
        return None
    row.montant = amount
    return amount


def refresh_urssaf_recap():
    """Réécrit le récapitulatif avec le total facturé de chaque mois."""
    rows = InvoiceDocument.query.filter(InvoiceDocument.filename.endswith(".pdf")).all()
    totals = {}
    for row in rows:
        amount = invoice_amount(row)
        moment = course_moment(row.filename, row.created_at)
        if amount is None or moment is None:
            continue
        key = (moment.year, moment.month)
        totals[key] = totals.get(key, 0.0) + amount

    lines = [
        "=== RECAPITULATIF URSSAF ===\n\n",
        "Somme des factures générées, pour la déclaration.\n\n",
    ]
    grand = 0.0
    for year, month in sorted(totals, reverse=True):
        amount = totals[(year, month)]
        grand += amount
        lines.append(f"- {FRENCH_MONTHS[month - 1]} {year} : {amount:.2f} EUR\n")
    if not totals:
        lines.append("Aucune facture générée.\n")
    lines.append(f"\nTOTAL FACTURE : {grand:.2f} EUR\n")
    store_recap("".join(lines))


def assign_invoice_numbers():
    """Numérote les factures sans numéro, dans l'ordre de la date du cours."""
    rows = InvoiceDocument.query.filter(InvoiceDocument.filename.endswith(".pdf")).all()
    rows.sort(key=lambda row: (
        course_moment(row.filename, row.created_at) or datetime.min.replace(tzinfo=timezone.utc),
        row.filename,
    ))
    start = starting_invoice_number()
    plan = []
    already_ok = True
    for index, row in enumerate(rows):
        number = start + index
        new_name = filename_with_number(row.filename, number)
        if row.invoice_number != number or row.filename != new_name:
            already_ok = False
        plan.append({
            "old": row.filename,
            "new": new_name,
            "number": number,
            "content": replace_invoice_label(bytes(row.content or b""), number),
        })
    if already_ok or not plan:
        return
    for index, item in enumerate(plan):
        db.session.execute(
            text("UPDATE invoice_document SET invoice_number = NULL, filename = :tmp WHERE filename = :old"),
            {"tmp": f"__tmp_{index}.pdf", "old": item["old"]},
        )
    db.session.flush()
    for index, item in enumerate(plan):
        db.session.execute(
            text(
                "UPDATE invoice_document SET filename = :name, invoice_number = :number, content = :content "
                "WHERE filename = :tmp"
            ),
            {
                "name": item["new"],
                "number": item["number"],
                "content": item["content"],
                "tmp": f"__tmp_{index}.pdf",
            },
        )
    db.session.commit()
    db.session.expire_all()


def process_events():
    student_db = students_map()
    result = {"created": 0, "skipped": 0, "warnings": [], "files": []}

    raw_events = cache_text(RAW_EVENTS_KEY)
    if raw_events is None:
        result["warnings"].append("Aucun cours synchronisé.")
        return result

    lines = raw_events.strip().split("\n")
    invoiced = invoiced_keys()

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            start, end, raw_name = parse_event_line(line)
            if "cours" not in raw_name.lower():
                continue

            key = event_key(start, end, raw_name)
            if key in invoiced:
                result["skipped"] += 1
                continue

            student_key, error = match_student(raw_name, student_db)
            if error:
                result["warnings"].append(error)
                continue

            student_data = student_db.get(student_key, {})
            if "tarif" not in student_data:
                result["warnings"].append(f"Tarif manquant pour {student_key}.")
                continue

            duration = duration_hours(start, end)
            if duration <= 0:
                result["warnings"].append(f"Durée invalide pour {raw_name}.")
                continue

            rate = float(student_data["tarif"])
            parent = student_data.get("parent", "")
            adresse = student_data.get("adresse", "")
            montant = duration * rate
            student_label = display_name(student_key)
            formatted_date = paris_date(start)

            filename = generate_pdf_invoice(
                student_label,
                formatted_date,
                duration,
                montant,
                parent,
                adresse,
                start,
                end,
                key,
            )
            db.session.add(InvoicedEvent(event_key=key))
            db.session.commit()
            invoiced.add(key)

            result["created"] += 1
            result["files"].append(filename)
        except Exception as exc:
            db.session.rollback()
            result["warnings"].append(f"Ligne {line_number} ignorée : {exc}")

    if result["created"] > 0:
        refresh_urssaf_recap()

    print(f"Termine. {result['created']} facture(s), {result['skipped']} deja facturee(s).")
    return result
