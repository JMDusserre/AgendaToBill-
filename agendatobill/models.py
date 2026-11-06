import json
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

RAW_EVENTS_KEY = "raw_events"
AGENDA_EVENTS_KEY = "agenda_events"


class Student(db.Model):
    __tablename__ = "student"

    nom = db.Column(db.String(200), primary_key=True)
    tarif = db.Column(db.Float, nullable=False)
    parent = db.Column(db.String(200), nullable=False, default="")
    adresse = db.Column(db.String(500), nullable=False, default="")


class InvoicedEvent(db.Model):
    __tablename__ = "invoiced_event"

    event_key = db.Column(db.String(500), primary_key=True)


class InvoiceDocument(db.Model):
    __tablename__ = "invoice_document"

    filename = db.Column(db.String(255), primary_key=True)
    content = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    invoice_number = db.Column(db.Integer, unique=True, nullable=True)
    montant = db.Column(db.Float, nullable=True)
    event_key = db.Column(db.String(500), nullable=True)


class SyncCache(db.Model):
    __tablename__ = "sync_cache"

    key = db.Column(db.String(64), primary_key=True)
    data_text = db.Column(db.Text, nullable=False, default="")


def students_map():
    rows = Student.query.order_by(Student.nom).all()
    return {
        row.nom: {
            "tarif": row.tarif,
            "parent": row.parent or "",
            "adresse": row.adresse or "",
        }
        for row in rows
    }


def invoiced_keys():
    return {row.event_key for row in InvoicedEvent.query.all()}


def cache_text(key):
    row = db.session.get(SyncCache, key)
    if row is None:
        return None
    return row.data_text or ""


def write_cache(key, text):
    row = db.session.get(SyncCache, key)
    if row is None:
        db.session.add(SyncCache(key=key, data_text=text))
    else:
        row.data_text = text


def load_agenda_events():
    raw = cache_text(AGENDA_EVENTS_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_sync(raw_lines, agenda_events):
    write_cache(RAW_EVENTS_KEY, "\n".join(raw_lines))
    write_cache(AGENDA_EVENTS_KEY, json.dumps(agenda_events, ensure_ascii=False))
    db.session.commit()
