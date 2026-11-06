import os
from flask import Flask, request, render_template_string, redirect, send_file, send_from_directory
import json
from datetime import datetime, timezone
import shutil
import caldav
import pdf_generator

app = Flask(__name__)

USERNAME = "jean-michel.dusserre@hotmail.fr"
PASSWORD = "REMOVED"
CALDAV_URL = "https://caldav.icloud.com/"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
    <title>App Guitare</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; padding: 20px 20px 80px 20px; margin: auto; background: #f2f2f7; color: #1c1c1e; }
        h2 { margin-top: 0; }
        .card { background: white; border-radius: 12px; padding: 15px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: 14px; }
        th, td { padding: 10px 5px; border-bottom: 1px solid #e5e5ea; text-align: left; }
        .btn { display: block; width: 100%; padding: 16px; background: #007AFF; color: white; text-align: center; border: none; border-radius: 12px; font-size: 17px; font-weight: 600; cursor: pointer; text-decoration: none; margin-bottom: 10px; box-sizing: border-box; }
        .btn:active { background: #0056b3; }
        .btn-success { background: #34c759; }
        .btn-success:active { background: #28a745; }
        
        .action-group { display: flex; gap: 10px; margin-top: 10px; }
        .btn-edit { background: #e5e5ea; color: #000; padding: 10px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; flex: 1; text-align: center; }
        .delete-icon { background: none; border: none; cursor: pointer; color: #ff3b30; font-size: 16px; padding: 5px 10px; }
        
        .total { font-size: 22px; font-weight: 700; text-align: right; color: #000; margin-top: 10px; }
        .success { background: #d4edda; color: #155724; padding: 15px; border-radius: 12px; font-weight: bold; margin-bottom: 20px; text-align: center;}
        
        .form-group { margin-bottom: 15px; }
        label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 5px; color: #3a3a3c; }
        input[type="text"], input[type="number"], input[type="email"] { width: 100%; padding: 12px; border: 1px solid #c7c7cc; border-radius: 8px; font-size: 16px; box-sizing: border-box; }
        
        .search-bar { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-bar input { flex: 1; padding: 10px; border: 1px solid #c7c7cc; border-radius: 8px; font-size: 15px; }
        .search-bar button { background: #007AFF; color: white; border: none; border-radius: 8px; padding: 0 15px; font-size: 16px; cursor: pointer; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(255,255,255,0.9); backdrop-filter: blur(10px); border-top: 1px solid #c7c7cc; display: flex; justify-content: space-around; padding: 10px 0 25px 0; z-index: 1000;}
        .nav-item { text-decoration: none; color: #8e8e93; font-size: 12px; text-align: center; font-weight: 500; display: flex; flex-direction: column; align-items: center; width: 33%; }
        .nav-item.active { color: #007AFF; }
        .nav-icon { font-size: 24px; margin-bottom: 4px; }
        
        .archive-list { list-style: none; padding: 0; margin: 0; }
        .archive-list li { padding: 12px 0; border-bottom: 1px solid #e5e5ea; display: flex; justify-content: space-between; align-items: center; }
        .archive-list li:last-child { border-bottom: none; }
        .archive-list a { text-decoration: none; color: #007AFF; font-weight: 500; font-size: 15px; display: flex; align-items: center; flex: 1; word-break: break-all; margin-right: 10px; }
        .section-title { font-size: 13px; font-weight: 600; color: #8e8e93; margin-top: 15px; border-top: 1px solid #e5e5ea; padding-top: 10px; text-transform: uppercase; }
        
        .calendar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .calendar-btn { background: #e5e5ea; border: none; border-radius: 8px; padding: 8px 12px; font-weight: 600; cursor: pointer; font-size: 13px; }
        .calendar-title { font-size: 16px; font-weight: 600; text-transform: capitalize; }
        .calendar-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 5px; }
        .day-name { text-align: center; font-size: 10px; font-weight: 600; color: #8e8e93; margin-bottom: 5px; text-transform: uppercase; }
        .day-cell { background: white; border-radius: 6px; min-height: 75px; padding: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); display: flex; flex-direction: column; gap: 2px; overflow: hidden; }
        .day-empty { background: transparent; box-shadow: none; }
        .day-num { font-size: 12px; font-weight: 600; color: #1c1c1e; margin-bottom: 2px; }
        .event-block { font-size: 9px; padding: 3px; border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.2; }
        .c-termine { background: #d4edda; color: #155724; }
        .c-encours { background: #fff3cd; color: #856404; }
        .c-avenir { background: #cce5ff; color: #004085; }
    </style>
    <script>
        function editClient(btn) {
            document.getElementById('form-eleve').value = btn.getAttribute('data-nom');
            document.getElementById('form-tarif').value = btn.getAttribute('data-tarif');
            document.getElementById('form-parent').value = btn.getAttribute('data-parent');
            document.getElementById('form-adresse').value = btn.getAttribute('data-adresse');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    </script>
</head>
<body>
    
    {% if success %}
        <div class="success">✅ Action réussie !</div>
    {% endif %}

    {% if page == 'factures' %}
        <h2>🎸 Facturation</h2>
        {% if preview_data %}
            <div class="card">
                <table>
                    <tr><th>Élève</th><th>Date</th><th>Durée</th><th>€</th></tr>
                    {% for row in preview_data %}
                    <tr>
                        <td>{{ row.nom }}</td>
                        <td>{{ row.date }}</td>
                        <td>{{ row.duree }}h</td>
                        <td>{{ row.montant }}</td>
                    </tr>
                    {% endfor %}
                </table>
                <div class="total">Total : {{ total }} €</div>
            </div>
            <form action="/generate" method="POST">
                <button type="submit" class="btn">1. Générer les factures</button>
            </form>
        {% else %}
            <div class="card">Aucun événement terminé en attente.</div>
        {% endif %}
        
        <div class="card">
            <h3 style="margin-top: 0; font-size: 16px; text-transform: uppercase; color: #8e8e93;">📄 Base documentaire globale</h3>
            
            <form action="/" method="GET" class="search-bar">
                <input type="text" name="search" placeholder="Rechercher (ex: URSSAF, Nom)..." value="{{ search_query }}">
                <button type="submit">🔍</button>
                {% if search_query %}
                    <a href="/" class="btn-edit" style="margin-top: 0; padding: 10px; text-decoration: none; width: auto; flex: none;">❌</a>
                {% endif %}
            </form>

            {% if archives %}
                <ul class="archive-list">
                {% for file in archives %}
                    <li>
                        <a href="/view/{{ file }}" target="_blank">📄 {{ file }}</a>
                        <form action="/delete_file" method="POST" style="margin:0;" onsubmit="return confirm('Supprimer ce fichier définitivement ?');">
                            <input type="hidden" name="filename" value="{{ file }}">
                            <button type="submit" class="delete-icon" title="Supprimer">🗑️</button>
                        </form>
                    </li>
                {% endfor %}
                </ul>
                <form action="/download_zip" method="GET" style="margin-top: 20px;">
                    <button type="submit" class="btn btn-success">2. Télécharger l'archive ZIP</button>
                </form>
            {% else %}
                <div style="color: #8e8e93; font-size: 14px; text-align: center; margin-top: 15px;">Aucun document trouvé.</div>
            {% endif %}
        </div>
    {% endif %}

    {% if page == 'agenda' %}
        <h2>📅 Mon Agenda</h2>
        <div class="card" style="padding: 15px 10px;">
            <div class="calendar-header">
                <button class="calendar-btn" onclick="changeMonth(-1)">Précédent</button>
                <div id="monthYear" class="calendar-title"></div>
                <button class="calendar-btn" onclick="changeMonth(1)">Suivant</button>
            </div>
            <div class="calendar-grid">
                <div class="day-name">Lun</div><div class="day-name">Mar</div><div class="day-name">Mer</div>
                <div class="day-name">Jeu</div><div class="day-name">Ven</div><div class="day-name">Sam</div><div class="day-name">Dim</div>
            </div>
            <div id="calendarGrid" class="calendar-grid"></div>
        </div>
        
        <div style="display: flex; justify-content: center; gap: 15px; font-size: 11px; margin-bottom: 20px; font-weight: 600;">
            <div style="display: flex; align-items: center; gap: 5px;"><div style="width: 10px; height: 10px; background: #d4edda; border-radius: 2px;"></div> Terminé</div>
            <div style="display: flex; align-items: center; gap: 5px;"><div style="width: 10px; height: 10px; background: #fff3cd; border-radius: 2px;"></div> En cours</div>
            <div style="display: flex; align-items: center; gap: 5px;"><div style="width: 10px; height: 10px; background: #cce5ff; border-radius: 2px;"></div> À venir</div>
        </div>

       <script>
            let currentDate = new Date();
            const rawEvents = {{ agenda_events | tojson | safe }};
            
            function renderCalendar() {
                const year = currentDate.getFullYear();
                const month = currentDate.getMonth();
                
                const formatter = new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric' });
                document.getElementById('monthYear').textContent = formatter.format(new Date(year, month, 1));
                
                const firstDay = new Date(year, month, 1).getDay();
                const daysInMonth = new Date(year, month + 1, 0).getDate();
                const grid = document.getElementById('calendarGrid');
                grid.innerHTML = '';
                
                let startOffset = firstDay === 0 ? 6 : firstDay - 1;
                for(let i=0; i<startOffset; i++) {
                    grid.innerHTML += '<div class="day-cell day-empty"></div>';
                }
                
                for(let d=1; d<=daysInMonth; d++) {
                    const monthStr = String(month + 1).padStart(2, '0');
                    const dayStr = String(d).padStart(2, '0');
                    const dateString = year + '-' + monthStr + '-' + dayStr;
                    
                    let eventsHtml = '';
                    rawEvents.forEach(ev => {
                        if(ev.iso_start.startsWith(dateString)) {
                            let cssClass = 'c-avenir';
                            if(ev.status === 'terminé') cssClass = 'c-termine';
                            if(ev.status === 'en cours') cssClass = 'c-encours';
                            
                            const eventDate = new Date(ev.iso_start);
                            const timeStr = eventDate.toLocaleTimeString('fr-FR', {hour: '2-digit', minute:'2-digit'});
                            
                            eventsHtml += '<div class="event-block ' + cssClass + '"><span style="opacity: 0.65; margin-right: 3px;">' + timeStr + '</span>' + ev.summary + '</div>';
                        }
                    });
                    
                    grid.innerHTML += '<div class="day-cell"><div class="day-num">' + d + '</div>' + eventsHtml + '</div>';
                }
            }
            
            function changeMonth(delta) {
                currentDate.setMonth(currentDate.getMonth() + delta);
                renderCalendar();
            }
            
            renderCalendar();
        </script>
    {% endif %}

    {% if page == 'clients' %}
        <h2>👥 Base Élèves</h2>
        
        <div class="card" style="background: #eef7ff; border: 1px solid #b6d4fe;">
            <h3 style="margin-top: 0; font-size: 16px; color: #0056b3;">Ajouter / Modifier un élève</h3>
            <form action="/clients/save" method="POST">
                <div class="form-group">
                    <label>Nom de l'élève (agenda)</label>
                    <input type="text" id="form-eleve" name="eleve" required>
                </div>
                <div class="form-group">
                    <label>Tarif horaire (€)</label>
                    <input type="number" id="form-tarif" name="tarif" step="0.5" required>
                </div>
                <div class="form-group">
                    <label>Contact facturation (Parent)</label>
                    <input type="text" id="form-parent" name="parent">
                </div>
                <div class="form-group">
                    <label>Adresse postale</label>
                    <input type="text" id="form-adresse" name="adresse">
                </div>
                <button type="submit" class="btn" style="padding: 12px; font-size: 15px;">Enregistrer la fiche</button>
            </form>
        </div>

        {% for nom, data in students.items() %}
        <div class="card">
            <div style="font-weight: 700; font-size: 18px; margin-bottom: 5px;">{{ nom.title() }}</div>
            <div style="font-size: 14px; color: #3a3a3c;">
                Tarif : {{ data.tarif }} €/h<br>
                {% if data.parent %}Contact : {{ data.parent }}<br>{% endif %}
                {% if data.adresse %}Adresse : {{ data.adresse }}{% endif %}
            </div>
            
            {% if client_invoices[nom] %}
                <div class="section-title">Historique des factures</div>
                <ul class="archive-list" style="margin-top: 5px;">
                {% for file in client_invoices[nom] %}
                    <li>
                        <a href="/view/{{ file }}" target="_blank" style="font-size: 14px;">📄 {{ file }}</a>
                        <form action="/delete_file" method="POST" style="margin:0;" onsubmit="return confirm('Supprimer la facture de {{ nom.title() }} ?');">
                            <input type="hidden" name="filename" value="{{ file }}">
                            <button type="submit" class="delete-icon" title="Supprimer">🗑️</button>
                        </form>
                    </li>
                {% endfor %}
                </ul>
            {% endif %}

            <div class="action-group" style="align-items: center;">
                <button type="button" class="btn-edit" style="flex: 1;"
                        onclick="editClient(this)" 
                        data-nom="{{ nom }}" 
                        data-tarif="{{ data.tarif }}" 
                        data-parent="{{ data.parent }}" 
                        data-adresse="{{ data.adresse }}">
                    ✏️ Modifier
                </button>
                <form action="/clients/delete" method="POST" style="margin: 0;" onsubmit="return confirm('Supprimer définitivement la fiche de {{ nom.title() }} ?');">
                    <input type="hidden" name="eleve" value="{{ nom }}">
                    <button type="submit" class="delete-icon" style="font-size: 20px; padding: 10px;" title="Supprimer">🗑️</button>
                </form>
            </div>
        </div>
        {% endfor %}
    {% endif %}

    <div class="nav-bar">
        <a href="/" class="nav-item {% if page == 'factures' %}active{% endif %}">
            <span class="nav-icon">🧾</span><span>Factures</span>
        </a>
        <a href="/agenda" class="nav-item {% if page == 'agenda' %}active{% endif %}">
            <span class="nav-icon">📅</span><span>Agenda</span>
        </a>
        <a href="/clients" class="nav-item {% if page == 'clients' %}active{% endif %}">
            <span class="nav-icon">👥</span><span>Clients</span>
        </a>
    </div>
</body>
</html>
"""

def fetch_icloud_events():
    try:
        client = caldav.DAVClient(url=CALDAV_URL, username=USERNAME, password=PASSWORD)
        principal = client.principal()
        raw_lines = []
        agenda_events = []
        now = datetime.now(timezone.utc)
        
        for calendar in principal.calendars():
            try:
                for event in calendar.events():
                    try:
                        vevent = event.vobject_instance.vevent
                        summary = str(vevent.summary.value) if hasattr(vevent, 'summary') else ""
                        if "cours" not in summary.lower():
                            continue
                        
                        dtstart = vevent.dtstart.value
                        dtend = vevent.dtend.value if hasattr(vevent, 'dtend') else dtstart
                        
                        if type(dtstart) is not datetime:
                            continue
                            
                        end_time_utc = dtend.astimezone(timezone.utc) if dtend.tzinfo else dtend.replace(tzinfo=timezone.utc)
                        start_time_utc = dtstart.astimezone(timezone.utc) if dtstart.tzinfo else dtstart.replace(tzinfo=timezone.utc)
                        
                        duration = (dtend - dtstart).total_seconds() / 3600
                        
                        if end_time_utc <= now:
                            status = 'terminé'
                            raw_lines.append(f"{dtstart.isoformat()}|{dtend.isoformat()}|{summary}")
                        elif start_time_utc <= now < end_time_utc:
                            status = 'en cours'
                        else:
                            status = 'à venir'
                            
                        agenda_events.append({
                            "iso_start": dtstart.isoformat(),
                            "summary": summary.replace("cours", "").strip().title(),
                            "status": status
                        })
                    except Exception:
                        continue
            except Exception:
                continue
                
        with open('raw_events.txt', 'w', encoding='utf-8') as f:
            f.write('\n'.join(raw_lines))
            
        with open('agenda.json', 'w', encoding='utf-8') as f:
            json.dump(agenda_events, f, ensure_ascii=False, indent=4)
            
    except Exception as e:
        print(f"Erreur de synchronisation CalDAV : {e}")

def load_students():
    try:
        with open('students.json', 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return {}

def load_agenda():
    try:
        with open('agenda.json', 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return []

def save_students(data):
    with open('students.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_preview_data():
    student_db = load_students()
    preview_data = []
    total_global = 0.0
    try:
        with open('raw_events.txt', 'r', encoding='utf-8') as file:
            lines = file.read().strip().split('\n')
        for line in lines:
            if not line.strip(): continue
            start_str, end_str, raw_name = line.split('|')
            if "cours" not in raw_name.lower(): continue
            start_time = datetime.fromisoformat(start_str.strip())
            end_time = datetime.fromisoformat(end_str.strip())
            duration = (end_time - start_time).total_seconds() / 3600
            clean_name = raw_name.lower().replace("cours", "").strip()
            rate = student_db.get(clean_name, {}).get("tarif", 30.0)
            montant = duration * rate
            total_global += montant
            preview_data.append({"date": start_time.strftime("%d/%m"), "nom": clean_name.title(), "duree": duration, "montant": f"{montant:.0f}"})
    except Exception: pass
    return preview_data, f"{total_global:.2f}"

@app.route('/', methods=['GET'])
def index():
    success = request.args.get('success')
    search_query = request.args.get('search', '').strip().lower()
    
    if not search_query:
        fetch_icloud_events()
        
    preview_data, total = get_preview_data()
    archives = []
    
    if os.path.exists('factures'):
        all_files = sorted([f for f in os.listdir('factures') if f.endswith('.pdf') or f.endswith('.txt')], reverse=True)
        if search_query:
            archives = [f for f in all_files if search_query in f.lower()]
        else:
            archives = all_files

    return render_template_string(HTML_TEMPLATE, page='factures', preview_data=preview_data, total=total, success=success, archives=archives, search_query=search_query)

@app.route('/agenda', methods=['GET'])
def agenda():
    fetch_icloud_events()
    agenda_events = load_agenda()
    return render_template_string(HTML_TEMPLATE, page='agenda', agenda_events=agenda_events)

@app.route('/clients', methods=['GET'])
def clients():
    success = request.args.get('success')
    students = load_students()
    client_invoices = {nom: [] for nom in students.keys()}
    
    if os.path.exists('factures'):
        all_files = sorted([f for f in os.listdir('factures') if f.endswith('.pdf')], reverse=True)
        for nom, data in students.items():
            safe_student = nom.title().replace(" ", "_").replace("/", "-")
            safe_parent = data.get('parent', '').replace(" ", "_").replace("/", "-") if data.get('parent') else ""
            
            for f in all_files:
                if safe_student.lower() in f.lower() or (safe_parent and safe_parent.lower() in f.lower()):
                    client_invoices[nom].append(f)

    return render_template_string(HTML_TEMPLATE, page='clients', students=students, success=success, client_invoices=client_invoices)

@app.route('/clients/save', methods=['POST'])
def save_client():
    eleve = request.form.get('eleve').strip().lower()
    tarif = float(request.form.get('tarif'))
    parent = request.form.get('parent', '').strip()
    adresse = request.form.get('adresse', '').strip()
    students = load_students()
    students[eleve] = {"tarif": tarif, "parent": parent, "adresse": adresse}
    save_students(students)
    return redirect('/clients?success=1')

@app.route('/clients/delete', methods=['POST'])
def delete_client():
    eleve = request.form.get('eleve').strip()
    students = load_students()
    if eleve in students:
        del students[eleve]
        save_students(students)
    return redirect('/clients?success=1')

@app.route('/delete_file', methods=['POST'])
def delete_file():
    filename = request.form.get('filename')
    if filename and '/' not in filename and '\\' not in filename:
        filepath = os.path.join('factures', filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    return redirect(request.referrer or '/?success=1')

@app.route('/generate', methods=['POST'])
def generate():
    pdf_generator.process_events()
    return redirect('/?success=1')

@app.route('/download_zip', methods=['GET'])
def download_zip():
    shutil.make_archive('factures_export', 'zip', 'factures')
    return send_file('factures_export.zip', as_attachment=True)

@app.route('/view/<filename>')
def view_file(filename):
    mimetype = 'application/pdf' if filename.endswith('.pdf') else 'text/plain'
    return send_from_directory('factures', filename, as_attachment=False, mimetype=mimetype)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)