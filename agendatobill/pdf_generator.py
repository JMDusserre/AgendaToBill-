import json
import os
import tempfile
from fpdf import FPDF

from agendatobill.billing import (
    duration_hours,
    event_key,
    invoice_basename,
    match_student,
    paris_date,
    parse_event_line,
    display_name,
)
from agendatobill.paths import data_file, invoice_dir


def load_students():
    try:
        with open(data_file("students.json"), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        print("Fichier students.json introuvable.")
        return {}
    except json.JSONDecodeError:
        print("Erreur de format dans students.json.")
        return {}


def load_invoiced():
    try:
        with open(data_file("invoiced.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return set()


def atomic_write(path, content):
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False)
    try:
        handle.write(content)
        handle.close()
        os.replace(handle.name, path)
    except Exception:
        handle.close()
        if os.path.exists(handle.name):
            os.remove(handle.name)
        raise


def save_invoiced(keys):
    atomic_write(data_file("invoiced.json"), json.dumps(sorted(keys), indent=2, ensure_ascii=False))


def pdf_text(value):
    return (value or "").encode("latin-1", "replace").decode("latin-1")


def unique_invoice_path(basename):
    folder = invoice_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / basename
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(basename)
    index = 2
    while True:
        candidate = invoice_dir() / f"{stem}_{index}{ext}"
        if not os.path.exists(candidate):
            return candidate
        index += 1


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

    path = unique_invoice_path(filename)
    pdf.output(str(path))
    return path


def process_events():
    student_db = load_students()
    result = {"created": 0, "skipped": 0, "warnings": [], "files": []}

    try:
        with open(data_file("raw_events.txt"), "r", encoding="utf-8") as handle:
            lines = handle.read().strip().split("\n")
    except FileNotFoundError:
        result["warnings"].append("Fichier raw_events.txt introuvable.")
        return result

    invoiced = load_invoiced()
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

            path = generate_pdf_invoice(
                student_label,
                formatted_date,
                duration,
                montant,
                parent,
                adresse,
                start,
                end,
            )
            invoiced.add(key)
            save_invoiced(invoiced)

            recap.setdefault(facture_a, {"heures": 0.0, "montant": 0.0})
            recap[facture_a]["heures"] += duration
            recap[facture_a]["montant"] += montant
            total_global += montant
            result["created"] += 1
            result["files"].append(path)
        except Exception as exc:
            result["warnings"].append(f"Ligne {line_number} ignorée : {exc}")

    if result["created"] > 0:
        invoice_dir().mkdir(parents=True, exist_ok=True)
        recap_path = invoice_dir() / "recapitulatif_urssaf.txt"
        with open(recap_path, "w", encoding="utf-8") as handle:
            handle.write("=== RECAPITULATIF DU LOT FACTURE ===\n\n")
            handle.write(f"TOTAL FACTURE SUR CE LOT : {total_global:.2f} EUR\n")
            handle.write("Ce montant correspond aux factures créées lors de cette génération, pas aux encaissements.\n")
            handle.write("\nDetail par client :\n")
            for client, data in recap.items():
                handle.write(f"- {client} : {data['heures']:.2f}h -> {data['montant']:.2f} EUR\n")

    print(f"Termine. {result['created']} facture(s), {result['skipped']} deja facturee(s).")
    return result
