import os
from datetime import datetime, timezone

from fpdf import FPDF

from agendatobill.billing import (
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


def pdf_text(value):
    return (value or "").encode("latin-1", "replace").decode("latin-1")


def unique_invoice_filename(basename):
    if db.session.get(InvoiceDocument, basename) is None:
        return basename
    stem, ext = os.path.splitext(basename)
    index = 2
    while db.session.get(InvoiceDocument, f"{stem}_{index}{ext}") is not None:
        index += 1
    return f"{stem}_{index}{ext}"


def generate_pdf_invoice(student_name, date_str, duration, montant, parent="", adresse="", start=None, end=None):
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(200, 10, txt="FACTURE / RECU DE COURS", ln=True, align="C")
    pdf.ln(10)

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

    filename = unique_invoice_filename(filename)
    payload = bytes(pdf.output())
    db.session.add(InvoiceDocument(
        filename=filename,
        content=payload,
        created_at=datetime.now(timezone.utc),
    ))
    return filename


def store_recap(text):
    payload = text.encode("utf-8")
    now = datetime.now(timezone.utc)
    row = db.session.get(InvoiceDocument, RECAP_FILENAME)
    if row is None:
        db.session.add(InvoiceDocument(filename=RECAP_FILENAME, content=payload, created_at=now))
    else:
        row.content = payload
        row.created_at = now
    db.session.commit()


def process_events():
    student_db = students_map()
    result = {"created": 0, "skipped": 0, "warnings": [], "files": []}

    raw_events = cache_text(RAW_EVENTS_KEY)
    if raw_events is None:
        result["warnings"].append("Aucun cours synchronisé.")
        return result

    lines = raw_events.strip().split("\n")
    invoiced = invoiced_keys()
    recap = {}
    total_global = 0.0

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
            facture_a = parent if parent else student_label
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
            )
            db.session.add(InvoicedEvent(event_key=key))
            db.session.commit()
            invoiced.add(key)

            recap.setdefault(facture_a, {"heures": 0.0, "montant": 0.0})
            recap[facture_a]["heures"] += duration
            recap[facture_a]["montant"] += montant
            total_global += montant
            result["created"] += 1
            result["files"].append(filename)
        except Exception as exc:
            db.session.rollback()
            result["warnings"].append(f"Ligne {line_number} ignorée : {exc}")

    if result["created"] > 0:
        lines_out = [
            "=== RECAPITULATIF DU LOT FACTURE ===\n",
            f"TOTAL FACTURE SUR CE LOT : {total_global:.2f} EUR\n",
            "Ce montant correspond aux factures créées lors de cette génération, pas aux encaissements.\n",
            "\nDetail par client :\n",
        ]
        for client, data in recap.items():
            lines_out.append(f"- {client} : {data['heures']:.2f}h -> {data['montant']:.2f} EUR\n")
        store_recap("".join(lines_out))

    print(f"Termine. {result['created']} facture(s), {result['skipped']} deja facturee(s).")
    return result
