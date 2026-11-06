import json
import os
from datetime import datetime
from fpdf import FPDF

def load_students():
    try:
        with open('students.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️ Fichier students.json introuvable.")
        return {}
    except json.JSONDecodeError:
        print("❌ Erreur de format dans students.json.")
        return {}

def generate_pdf_invoice(student_name, date_str, duration, montant, parent="", adresse=""):
    if not os.path.exists('factures'):
        os.makedirs('factures')

    pdf = FPDF()
    pdf.add_page()
    
    # En-tête (Informations du Professeur)
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(200, 10, txt="FACTURE / REÇU DE COURS", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Helvetica", size=11)
    pdf.cell(200, 6, txt="Prestataire : Jean-Michel Dusserre", ln=True)
    pdf.cell(200, 6, txt="SIREN : 912 347 028", ln=True)
    pdf.cell(200, 6, txt="Dispensé de l'immatriculation au RCS et au RM", ln=True)
    pdf.ln(15)
    
    # NOUVEAU : Informations du Client (Le parent qui paie, ou l'élève par défaut)
    pdf.set_font("Helvetica", style="B", size=12)
    client_name = parent if parent else student_name
    pdf.cell(200, 8, txt=f"Facturé à : {client_name}", ln=True)
    
    pdf.set_font("Helvetica", size=11)
    if adresse:
        pdf.cell(200, 6, txt=adresse, ln=True)
    pdf.ln(10)
    
    # Détails de la prestation
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(200, 8, txt="Détail de la prestation :", ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(200, 6, txt=f"Élève : {student_name}", ln=True)
    pdf.cell(200, 6, txt=f"Date du cours : {date_str}", ln=True)
    pdf.cell(200, 6, txt=f"Durée : {duration} heure(s)", ln=True)
    pdf.ln(10)
    
    # Montant et mentions légales
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(200, 10, txt=f"Montant total à régler : {montant:.2f} EUR", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Helvetica", style="I", size=10)
    pdf.cell(200, 6, txt="TVA non applicable, art. 293 B du CGI.", ln=True)
    pdf.cell(200, 6, txt="Paiement à réception par virement bancaire ou espèces.", ln=True)
    
    # Sauvegarde (on utilise le nom du client facturé pour le nom de fichier)
    safe_name = client_name.replace(" ", "_").replace("/", "-")
    safe_date = date_str.replace("/", "-")
    filename = f"factures/Facture_{safe_name}_{safe_date}.pdf"
    
    pdf.output(filename)
    return filename

def process_events():
    student_db = load_students()
    
    try:
        with open('raw_events.txt', 'r', encoding='utf-8') as file:
            lines = file.read().strip().split('\n')
    except FileNotFoundError:
        print("❌ Fichier raw_events.txt introuvable.")
        return

    print("🚀 Début de la génération des factures...")
    factures_creees = 0
    recap = {}
    total_global = 0.0

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
            
        try:
            start_str, end_str, raw_name = line.split('|')
            
            if "cours" not in raw_name.lower():
                continue
                
            start_time = datetime.fromisoformat(start_str.strip())
            end_time = datetime.fromisoformat(end_str.strip())
            duration = (end_time - start_time).total_seconds() / 3600
            
            clean_name = raw_name.lower().replace("cours", "").strip()
            
            # NOUVEAU : Récupération directe de toutes les infos depuis le dictionnaire (remplace get_price)
            student_data = student_db.get(clean_name, {})
            rate = student_data.get("tarif", 30.0)
            parent = student_data.get("parent", "")
            adresse = student_data.get("adresse", "")
            
            montant = duration * rate
            formatted_date = start_time.strftime("%d/%m/%Y")
            
            # NOUVEAU : Pour le récapitulatif URSSAF, on cumule sur le compte du parent s'il existe
            facture_a = parent if parent else clean_name.title()
            if facture_a not in recap:
                recap[facture_a] = {'heures': 0.0, 'montant': 0.0}
            
            recap[facture_a]['heures'] += duration
            recap[facture_a]['montant'] += montant
            total_global += montant
            
            # Génération du PDF
            generate_pdf_invoice(clean_name.title(), formatted_date, duration, montant, parent, adresse)
            factures_creees += 1
            
        except Exception as e:
            print(f"⚠️ Erreur à la ligne {line_number} : {e}")

    # Création du fichier de synthèse
    if factures_creees > 0:
        recap_path = 'factures/recapitulatif_urssaf.txt'
        with open(recap_path, 'w', encoding='utf-8') as f:
            f.write("=== RÉCAPITULATIF POUR DÉCLARATION URSSAF ===\n\n")
            f.write(f"TOTAL GLOBAL ENCAISSÉ : {total_global:.2f} EUR\n")
            f.write("\nDétail par client :\n")
            for client, data in recap.items():
                f.write(f"- {client} : {data['heures']}h -> {data['montant']:.2f} EUR\n")

    print(f"\n🎉 Terminé ! {factures_creees} facture(s) générée(s).")