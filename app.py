import io
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import caldav
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template_string, request, send_file, session, url_for

import agendatobill.pdf_generator as pdf_generator
from agendatobill.billing import (
    PARIS,
    as_utc,
    duration_hours,
    event_key,
    event_status,
    expand_occurrences,
    file_matches_person,
    fold_name,
    match_student,
    parse_event_line,
    should_keep_previous_events,
)
from agendatobill.models import (
    RAW_EVENTS_KEY,
    InvoiceDocument,
    InvoicedEvent,
    Student,
    SyncCache,
    cache_text,
    db,
    invoiced_keys,
    load_agenda_events,
    save_sync,
    students_map,
)
from agendatobill.paths import data_file, env_file, invoice_dir

load_dotenv(env_file(), override=True)


def database_uri():
    forced = (os.environ.get("AGENDA_DATABASE_URL") or "").strip()
    url = forced or (os.environ.get("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg2://" + url[len("postgresql+psycopg://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url:
        return url
    return "sqlite:///" + data_file("local.db").as_posix()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SQLALCHEMY_DATABASE_URI=database_uri(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
)
db.init_app(app)

if not app.config["SECRET_KEY"]:
    app.config["SECRET_KEY"] = secrets.token_hex(32)

CALDAV_URL = "https://caldav.icloud.com/"
SYNC_PAST = timedelta(days=120)
SYNC_FUTURE = timedelta(days=62)

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
        .warning { background: #fff3cd; color: #856404; padding: 15px; border-radius: 12px; font-weight: 600; margin-bottom: 12px; text-align: center;}
        
        .form-group { margin-bottom: 15px; }
        label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 5px; color: #3a3a3c; }
        input[type="text"], input[type="number"], input[type="email"] { width: 100%; padding: 12px; border: 1px solid #c7c7cc; border-radius: 8px; font-size: 16px; box-sizing: border-box; }
        
        .search-bar { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-bar input { flex: 1; padding: 10px; border: 1px solid #c7c7cc; border-radius: 8px; font-size: 15px; }
        .search-bar button { background: #007AFF; color: white; border: none; border-radius: 8px; padding: 0 15px; font-size: 16px; cursor: pointer; }
        
        .nav-bar { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(255,255,255,0.9); backdrop-filter: blur(10px); border-top: 1px solid #c7c7cc; display: flex; justify-content: space-around; padding: 10px 0 25px 0; z-index: 1000;}
        .nav-item { text-decoration: none; color: #8e8e93; font-size: 12px; text-align: center; font-weight: 500; display: flex; flex-direction: column; align-items: center; width: 33%; }
        .logout-btn { position: absolute; top: 4px; right: 12px; background: none; border: none; color: #8e8e93; font-size: 11px; cursor: pointer; padding: 0; }
        .nav-item.active { color: #007AFF; }
        .nav-icon { font-size: 24px; margin-bottom: 4px; }
        
        .archive-list { list-style: none; padding: 0; margin: 0; }
        .archive-list li { padding: 12px 0; border-bottom: 1px solid #e5e5ea; display: flex; justify-content: space-between; align-items: center; }
        .archive-list li:last-child { border-bottom: none; }
        .archive-list a { text-decoration: none; color: #007AFF; font-weight: 500; font-size: 15px; display: flex; align-items: center; flex: 1; word-break: break-all; margin-right: 10px; }
        details { margin-top: 6px; }
        summary { cursor: pointer; padding: 8px 0; font-weight: 700; color: #0056b3; outline: none; }
        summary:focus { outline: none; }
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
            document.getElementById('form-original').value = btn.getAttribute('data-nom');
            document.getElementById('form-tarif').value = btn.getAttribute('data-tarif');
            document.getElementById('form-parent').value = btn.getAttribute('data-parent');
            document.getElementById('form-adresse').value = btn.getAttribute('data-adresse');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        function resetClientForm() {
            ['form-eleve', 'form-original', 'form-tarif', 'form-parent', 'form-adresse'].forEach(function(id) {
                var field = document.getElementById(id);
                if (field) field.value = '';
            });
        }
    </script>
</head>
<body>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            <div class="{{ 'success' if category == 'success' else 'warning' }}">{{ message }}</div>
        {% endfor %}
    {% endwith %}
    {% for note in notices or [] %}
        <div class="warning">{{ note }}</div>
    {% endfor %}

    {% if page == 'factures' %}
        <h2>🎸 Facturation</h2>
        {% if preview_data %}
            <div class="card">
                <p style="font-size: 13px; color: #8e8e93; margin-top: 0; margin-bottom: 15px;">
                        Voici la liste des cours passés qui sont en attente d'être facturés.
                </p>
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
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <button type="submit" class="btn">1. Générer les factures</button>
            </form>
        {% else %}
            <div class="card" style="text-align: center; color: #8e8e93; font-size: 14px;">
                Aucun cours n'est actuellement en attente de facturation.
            </div>
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
                {% for group in archives %}
                <details {% if loop.first %}open{% endif %}>
                    <summary>{{ group.month }}</summary>
                    <ul class="archive-list">
                    {% for item in group.files %}
                        <li>
                            <a href="/view/{{ item.filename }}" target="_blank" style="display: flex; align-items: center; text-decoration: none;">
                                {% if item.student %}
                                    <span style="background: #eef7ff; color: #0056b3; padding: 4px 8px; border-radius: 6px; font-size: 11px; margin-right: 10px; font-weight: 600; border: 1px solid #b6d4fe; white-space: nowrap;">
                                        🎓 {{ item.student }}
                                    </span>
                                {% endif %}
                                <span style="font-size: 14px; color: #007AFF; word-break: break-all;">📄 {{ item.filename }}</span>
                            </a>
                            <form action="/delete_file" method="POST" style="margin:0;" onsubmit="return confirm('Supprimer ce fichier définitivement ?');">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                                <input type="hidden" name="filename" value="{{ item.filename }}">
                                <button type="submit" class="delete-icon" title="Supprimer">🗑️</button>
                            </form>
                        </li>
                    {% endfor %}
                    </ul>
                </details>
                {% endfor %}
                <form action="/download_zip" method="POST" style="margin-top: 20px;">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
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
                    const empty = document.createElement('div');
                    empty.className = 'day-cell day-empty';
                    grid.appendChild(empty);
                }
                
                for(let d=1; d<=daysInMonth; d++) {
                    const monthStr = String(month + 1).padStart(2, '0');
                    const dayStr = String(d).padStart(2, '0');
                    const dateString = year + '-' + monthStr + '-' + dayStr;
                    const cell = document.createElement('div');
                    cell.className = 'day-cell';
                    const num = document.createElement('div');
                    num.className = 'day-num';
                    num.textContent = String(d);
                    cell.appendChild(num);

                    rawEvents.forEach(ev => {
                        if(!ev.iso_start.startsWith(dateString)) return;
                        let cssClass = 'c-avenir';
                        if(ev.status === 'terminé') cssClass = 'c-termine';
                        if(ev.status === 'en cours') cssClass = 'c-encours';
                        const eventDate = new Date(ev.iso_start);
                        const timeStr = eventDate.toLocaleTimeString('fr-FR', {hour: '2-digit', minute:'2-digit'});
                        const block = document.createElement('div');
                        block.className = 'event-block ' + cssClass;
                        const time = document.createElement('span');
                        time.style.opacity = '0.65';
                        time.style.marginRight = '3px';
                        time.textContent = timeStr;
                        const label = document.createElement('span');
                        label.textContent = ev.summary;
                        block.appendChild(time);
                        block.appendChild(label);
                        cell.appendChild(block);
                    });
                    grid.appendChild(cell);
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
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <input type="hidden" id="form-original" name="original" value="">
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
                <button type="button" class="btn-edit" onclick="resetClientForm()">Nouvelle fiche</button>
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
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
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
                    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                    <input type="hidden" name="eleve" value="{{ nom }}">
                    <button type="submit" class="delete-icon" style="font-size: 20px; padding: 10px;" title="Supprimer">🗑️</button>
                </form>
            </div>
        </div>
        {% endfor %}
    {% endif %}

    <div class="nav-bar">
        <form action="/logout" method="POST" style="margin:0;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <button type="submit" class="logout-btn">Déconnexion</button>
        </form>
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

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
    <title>Connexion</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #f2f2f7; color: #1c1c1e; padding: 24px; }
        .card { background: white; border-radius: 12px; padding: 16px; max-width: 420px; margin: 48px auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        h2 { margin-top: 0; }
        input { width: 100%; padding: 12px; margin-bottom: 10px; font-size: 16px; box-sizing: border-box; border-radius: 8px; border: 1px solid #c7c7cc; }
        button { width: 100%; margin-top: 12px; padding: 16px; background: #007AFF; color: white; border: none; border-radius: 12px; font-size: 17px; font-weight: 600; cursor: pointer; }
        .warning { background: #fff3cd; color: #856404; padding: 12px; border-radius: 12px; margin-bottom: 12px; font-weight: 600; }
    </style>
</head>
<body>
    <div class="card">
        <h2>App Guitare</h2>
        {% with messages = get_flashed_messages() %}
            {% for message in messages %}<div class="warning">{{ message }}</div>{% endfor %}
        {% endwith %}
        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="text" name="username" placeholder="Nom" autocomplete="username" autofocus>
            <input type="password" name="password" placeholder="Mot de passe" autocomplete="current-password">
            <button type="submit">Entrer</button>
        </form>
    </div>
</body>
</html>
"""

def import_legacy_files():
    """Copie une fois les anciens fichiers si les tables sont encore vides."""
    import json

    if Student.query.count() == 0:
        path = data_file("students.json")
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                for nom, info in data.items():
                    if not isinstance(info, dict) or "tarif" not in info:
                        continue
                    nom = str(nom).strip().lower()
                    if not nom or db.session.get(Student, nom) is not None:
                        continue
                    db.session.add(Student(
                        nom=nom,
                        tarif=float(info["tarif"]),
                        parent=(info.get("parent") or ""),
                        adresse=(info.get("adresse") or ""),
                    ))

    if db.session.query(InvoicedEvent).count() == 0:
        path = data_file("invoiced.json")
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []
            if isinstance(data, list):
                seen = set()
                for key in data:
                    key = str(key or "").strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    db.session.add(InvoicedEvent(event_key=key))

    if db.session.get(SyncCache, RAW_EVENTS_KEY) is None:
        raw_path = data_file("raw_events.txt")
        agenda_path = data_file("agenda.json")
        if raw_path.is_file():
            db.session.add(SyncCache(key=RAW_EVENTS_KEY, data_text=raw_path.read_text(encoding="utf-8")))
        if agenda_path.is_file():
            db.session.add(SyncCache(key="agenda_events", data_text=agenda_path.read_text(encoding="utf-8")))

    if InvoiceDocument.query.count() == 0:
        folder = invoice_dir()
        if folder.is_dir():
            for path in folder.iterdir():
                if not path.is_file() or path.suffix.lower() not in {".pdf", ".txt"}:
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                db.session.add(InvoiceDocument(
                    filename=path.name,
                    content=path.read_bytes(),
                    created_at=modified,
                ))

    db.session.commit()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not token or not expected or not secrets.compare_digest(token, expected):
        abort(400)


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token()}


def app_credentials():
    load_dotenv(env_file(), override=True)
    username = (os.environ.get("APP_USERNAME") or "Simon Granger").strip()
    password = (os.environ.get("APP_PASSWORD") or "").strip()
    return username, password


def same_text(given, expected, ignore_case=False):
    given = (given or "").strip()
    expected = (expected or "").strip()
    if ignore_case:
        given = given.casefold()
        expected = expected.casefold()
    if not expected or len(given) != len(expected):
        return False
    return secrets.compare_digest(given, expected)


@app.before_request
def require_login():
    if request.method == "POST":
        validate_csrf()
    if request.endpoint in {"login", "static"}:
        return
    if not session.get("logged_in"):
        return redirect(url_for("login"))


def safe_filename(filename):
    return bool(filename) and os.path.basename(filename) == filename and not filename.startswith(".")


def redirect_back(fallback):
    parsed = urlparse(request.referrer or "")
    if parsed.netloc == request.host and parsed.path.startswith("/") and not parsed.path.startswith("//"):
        query = f"?{parsed.query}" if parsed.query else ""
        return redirect(parsed.path + query)
    return redirect(fallback)


def icloud_credentials():
    load_dotenv(env_file(), override=True)
    email = (os.environ.get("ICLOUD_EMAIL") or "").strip()
    password = (os.environ.get("ICLOUD_PASSWORD") or "").strip()
    return email, password


def rrule_text(vevent):
    if not hasattr(vevent, "rrule"):
        return None
    value = vevent.rrule.value
    return value if isinstance(value, str) else str(value)


def exdates_of(vevent):
    if not hasattr(vevent, "exdate"):
        return []
    value = vevent.exdate.value
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, datetime)]


def calendar_events(calendar, window_start, window_end):
    try:
        return calendar.search(start=window_start, end=window_end, event=True, expand=True)
    except TypeError:
        return calendar.search(start=window_start, end=window_end, event=True)


def fetch_icloud_events():
    email, password = icloud_credentials()
    if not email or not password:
        return "Identifiants iCloud manquants. Les cours déjà enregistrés n'ont pas été modifiés."
    try:
        client = caldav.DAVClient(url=CALDAV_URL, username=email, password=password)
        principal = client.principal()
        raw_lines = []
        agenda_events = []
        skipped = 0
        failed_calendars = 0
        seen_calendars = 0
        now = datetime.now(timezone.utc)
        window_start = now - SYNC_PAST
        window_end = now + SYNC_FUTURE

        for calendar in principal.calendars():
            seen_calendars += 1
            try:
                events = calendar_events(calendar, window_start, window_end)
            except Exception:
                failed_calendars += 1
                continue
            for event in events:
                try:
                    vevent = event.vobject_instance.vevent
                    summary = str(vevent.summary.value) if hasattr(vevent, "summary") else ""
                    if "cours" not in summary.lower():
                        continue
                    summary = summary.replace("|", " ").strip()
                    dtstart = vevent.dtstart.value
                    dtend = vevent.dtend.value if hasattr(vevent, "dtend") else dtstart
                    if not isinstance(dtstart, datetime) or not isinstance(dtend, datetime):
                        skipped += 1
                        continue
                    instances = expand_occurrences(
                        dtstart,
                        dtend,
                        rrule_text(vevent),
                        exdates_of(vevent),
                        window_start,
                        window_end,
                    )
                    for start, end in instances:
                        status = event_status(start, end, now)
                        start_utc = as_utc(start)
                        end_utc = as_utc(end)
                        if status == "terminé":
                            raw_lines.append(f"{start_utc.isoformat()}|{end_utc.isoformat()}|{summary}")
                        agenda_events.append({
                            "iso_start": start_utc.isoformat(),
                            "summary": summary,
                            "status": status,
                        })
                except Exception:
                    skipped += 1

        if seen_calendars and failed_calendars == seen_calendars:
            return "Aucun calendrier n'a pu être lu. Les cours déjà enregistrés n'ont pas été modifiés."
        previous_raw = cache_text(RAW_EVENTS_KEY) or ""
        if should_keep_previous_events(len(agenda_events), previous_raw):
            return "La synchro n'a renvoyé aucun cours. Les cours déjà enregistrés ont été conservés."

        save_sync(raw_lines, agenda_events)
        notes = []
        if failed_calendars:
            notes.append(f"{failed_calendars} calendrier(s) illisible(s) ignoré(s).")
        if skipped:
            notes.append(f"{skipped} événement(s) illisible(s) ignoré(s).")
        return " ".join(notes) or None
    except Exception as exc:
        db.session.rollback()
        return f"Synchro iCloud impossible : {exc}. Les cours déjà enregistrés n'ont pas été modifiés."


def load_agenda():
    return load_agenda_events()


def unique_notes(notes):
    seen = set()
    ordered = []
    for note in notes:
        if note and note not in seen:
            seen.add(note)
            ordered.append(note)
    return ordered


def get_preview_data():
    student_db = students_map()
    invoiced = invoiced_keys()
    preview_data = []
    warnings = []
    total_global = 0.0
    raw_events = cache_text(RAW_EVENTS_KEY)
    if raw_events is None:
        return [], "0.00", ["Aucun cours synchronisé."]
    lines = raw_events.strip().split("\n")

    for line in lines:
        if not line.strip():
            continue
        try:
            start, end, raw_name = parse_event_line(line)
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        if "cours" not in raw_name.lower():
            continue
        if event_key(start, end, raw_name) in invoiced:
            continue
        student_key, error = match_student(raw_name, student_db)
        if error:
            warnings.append(error)
            continue
        if "tarif" not in student_db[student_key]:
            warnings.append(f"Tarif manquant pour {student_key}.")
            continue
        duration = duration_hours(start, end)
        if duration <= 0:
            warnings.append(f"Durée invalide pour {raw_name}.")
            continue
        montant = duration * float(student_db[student_key]["tarif"])
        total_global += montant
        preview_data.append({
            "date": as_utc(start).astimezone(PARIS).strftime("%d/%m"),
            "nom": student_key.title(),
            "duree": f"{duration:.2f}",
            "montant": f"{montant:.2f}",
        })
    return preview_data, f"{total_global:.2f}", unique_notes(warnings)


FRENCH_MONTHS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def month_label(moment):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(PARIS)
    return f"{FRENCH_MONTHS[moment.month - 1]} {moment.year}"


def list_archives_with_info(search_query=""):
    documents = InvoiceDocument.query.order_by(InvoiceDocument.created_at.desc()).all()
    if search_query:
        documents = [doc for doc in documents if search_query in doc.filename.lower()]

    students = students_map()
    groups = []
    by_month = {}

    for document in documents:
        filename = document.filename
        label = month_label(document.created_at)
        if label not in by_month:
            group = {"month": label, "files": []}
            by_month[label] = group
            groups.append(group)

        student_display = ""
        if filename.endswith(".txt"):
            student_display = "URSSAF"
        else:
            for nom, data in students.items():
                parent = data.get("parent", "").strip()
                student_name = nom.title()
                client_name = parent if parent else student_name
                if file_matches_person(filename, client_name):
                    student_display = student_name
                    break

        by_month[label]["files"].append({
            "filename": filename,
            "student": student_display,
        })

    return groups

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected_username, expected_password = app_credentials()
        username_ok = same_text(request.form.get("username", ""), expected_username, ignore_case=True)
        password_ok = same_text(request.form.get("password", ""), expected_password)
        if username_ok and password_ok:
            session["logged_in"] = True
            session["username"] = expected_username
            return redirect("/")
        flash("Nom ou mot de passe incorrect.")
    return render_template_string(LOGIN_TEMPLATE)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
def index():
    search_query = request.args.get("search", "").strip().lower()
    notices = []
    if not search_query:
        sync_error = fetch_icloud_events()
        if sync_error:
            notices.append(sync_error)
    preview_data, total, warnings = get_preview_data()
    notices.extend(warnings)
    return render_template_string(
        HTML_TEMPLATE,
        page="factures",
        preview_data=preview_data,
        total=total,
        archives=list_archives_with_info(search_query),
        search_query=search_query,
        notices=unique_notes(notices),
        agenda_events=[],
        students={},
        client_invoices={},
    )


@app.route("/agenda", methods=["GET"])
def agenda():
    sync_error = fetch_icloud_events()
    notices = [sync_error] if sync_error else []
    return render_template_string(
        HTML_TEMPLATE,
        page="agenda",
        agenda_events=load_agenda(),
        notices=notices,
        preview_data=[],
        total="0.00",
        archives=[],
        search_query="",
        students={},
        client_invoices={},
    )


@app.route("/clients", methods=["GET"])
def clients():
    students = students_map()
    filenames = [
        row.filename
        for row in InvoiceDocument.query.order_by(InvoiceDocument.created_at.desc()).all()
        if row.filename.endswith(".pdf")
    ]
    client_invoices = {}
    for nom, data in students.items():
        parent = data.get("parent", "")
        client_invoices[nom] = [
            name for name in filenames if file_matches_person(name, nom.title(), parent)
        ]
    return render_template_string(
        HTML_TEMPLATE,
        page="clients",
        students=students,
        client_invoices=client_invoices,
        notices=[],
        preview_data=[],
        total="0.00",
        archives=[],
        search_query="",
        agenda_events=[],
    )


@app.route("/clients/save", methods=["POST"])
def save_client():
    eleve = (request.form.get("eleve") or "").strip().lower()
    original = (request.form.get("original") or "").strip()
    parent = (request.form.get("parent") or "").strip()
    adresse = (request.form.get("adresse") or "").strip()
    if not eleve:
        flash("Le nom de l'élève est obligatoire.", "warning")
        return redirect("/clients")
    try:
        tarif = float(request.form.get("tarif") or "")
    except ValueError:
        flash("Le tarif doit être un nombre.", "warning")
        return redirect("/clients")
    if tarif < 0:
        flash("Le tarif ne peut pas être négatif.", "warning")
        return redirect("/clients")

    students = students_map()
    conflicts = [
        key for key in students
        if fold_name(key) == fold_name(eleve) and key not in {eleve, original}
    ]
    if conflicts:
        flash("Une autre fiche correspond déjà à ce nom (accents ignorés).", "warning")
        return redirect("/clients")
    if original and original in students and original != eleve:
        previous = db.session.get(Student, original)
        if previous is not None:
            db.session.delete(previous)
            db.session.flush()
    row = db.session.get(Student, eleve)
    if row is None:
        row = Student(nom=eleve)
        db.session.add(row)
    row.tarif = tarif
    row.parent = parent
    row.adresse = adresse
    db.session.commit()
    flash("Fiche enregistrée.", "success")
    return redirect("/clients")


@app.route("/clients/delete", methods=["POST"])
def delete_client():
    eleve = (request.form.get("eleve") or "").strip()
    students = students_map()
    if eleve not in students:
        folded = fold_name(eleve)
        matches = [key for key in students if key.lower() == eleve.lower() or fold_name(key) == folded]
        eleve = matches[0] if len(matches) == 1 else ""
    row = db.session.get(Student, eleve) if eleve else None
    if row is not None:
        db.session.delete(row)
        db.session.commit()
        flash("Fiche supprimée.", "success")
    return redirect("/clients")


@app.route("/delete_file", methods=["POST"])
def delete_file():
    filename = request.form.get("filename")
    if safe_filename(filename):
        document = db.session.get(InvoiceDocument, filename)
        if document is not None:
            db.session.delete(document)
            db.session.commit()
            flash("Fichier supprimé.", "success")
    return redirect_back("/")


@app.route("/generate", methods=["POST"])
def generate():
    result = pdf_generator.process_events()
    if result["created"]:
        flash(f"{result['created']} facture(s) créée(s).", "success")
    else:
        flash("Aucune nouvelle facture créée.", "warning")
    if result["skipped"]:
        flash(f"{result['skipped']} cours déjà facturé(s), ignoré(s).", "warning")
    for warning in unique_notes(result["warnings"]):
        flash(warning, "warning")
    return redirect("/")


@app.route("/download_zip", methods=["POST"])
def download_zip():
    documents = InvoiceDocument.query.order_by(InvoiceDocument.filename).all()
    if not documents:
        flash("Aucun document à archiver.", "warning")
        return redirect("/")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for document in documents:
            archive.writestr(document.filename, bytes(document.content))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="factures_export.zip",
    )


@app.route("/view/<filename>")
def view_file(filename):
    if not safe_filename(filename):
        abort(404)
    document = db.session.get(InvoiceDocument, filename)
    if document is None:
        abort(404)
    mimetype = "application/pdf" if filename.endswith(".pdf") else "text/plain"
    return send_file(
        io.BytesIO(bytes(document.content)),
        mimetype=mimetype,
        as_attachment=False,
        download_name=filename,
    )


with app.app_context():
    db.create_all()
    import_legacy_files()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)