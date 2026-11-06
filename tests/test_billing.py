import os
import tempfile
import unittest
import zlib
from datetime import datetime, timezone
from unittest import mock

import agendatobill.pdf_generator as pdf_generator
from agendatobill.billing import (
    duration_hours,
    event_key,
    event_status,
    expand_occurrences,
    file_matches_person,
    fold_name,
    invoice_basename,
    match_student,
    paris_date,
    parse_event_line,
    should_keep_previous_events,
    starts_before_day,
)


class BillingTests(unittest.TestCase):
    def test_fold_name_ignores_accents_and_cours_prefix_only(self):
        self.assertEqual(fold_name("Cours Clément Bresson"), "clement bresson")
        self.assertEqual(fold_name("discours"), "discours")
        self.assertEqual(fold_name("Cours de guitare Anna"), "de guitare anna")

    def test_match_student_unknown_and_ambiguous(self):
        students = {
            "clement bresson": {"tarif": 80},
            "clément bresson": {"tarif": 30},
            "laura clément": {"tarif": 22.5},
        }
        key, error = match_student("Cours Laura Clément", students)
        self.assertEqual(key, "laura clément")
        self.assertIsNone(error)

        key, error = match_student("Cours Clément Bresson", students)
        self.assertIsNone(key)
        self.assertIn("Plusieurs fiches", error)

        key, error = match_student("Cours Inconnu", students)
        self.assertIsNone(key)
        self.assertIn("Élève inconnu", error)

    def test_naive_datetime_is_paris_not_utc(self):
        start = datetime(2026, 11, 6, 10, 0)
        end = datetime(2026, 11, 6, 11, 0)
        now = datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)
        self.assertEqual(event_status(start, end, now), "terminé")
        self.assertAlmostEqual(duration_hours(start, end), 1.0)

    def test_event_key_is_stable_across_offsets(self):
        paris = datetime.fromisoformat("2026-11-04T17:00:00+01:00")
        utc = datetime.fromisoformat("2026-11-04T16:00:00+00:00")
        end = datetime.fromisoformat("2026-11-04T18:00:00+01:00")
        end_utc = datetime.fromisoformat("2026-11-04T17:00:00+00:00")
        self.assertEqual(
            event_key(paris, end, "Cours Laura"),
            event_key(utc, end_utc, "cours laura"),
        )

    def test_parse_keeps_pipe_inside_the_name(self):
        start, end, name = parse_event_line(
            "2026-11-04T17:00:00+01:00 | 2026-11-04T18:00:00+01:00 | Cours A | B"
        )
        self.assertEqual(name, "Cours A | B")
        self.assertEqual(start.hour, 17)

    def test_same_day_invoices_have_distinct_names(self):
        first = invoice_basename(
            "Martine Dusserre",
            datetime.fromisoformat("2026-11-04T17:00:00+01:00"),
            datetime.fromisoformat("2026-11-04T18:00:00+01:00"),
        )
        second = invoice_basename(
            "Martine Dusserre",
            datetime.fromisoformat("2026-11-04T19:00:00+01:00"),
            datetime.fromisoformat("2026-11-04T20:00:00+01:00"),
        )
        self.assertNotEqual(first, second)
        self.assertIn("17", first)
        self.assertTrue(file_matches_person(first, "Martine Dusserre"))
        self.assertFalse(file_matches_person("Facture_Jean_Michel_Dusserre_04-11-2026_1700-1800.pdf", "Jean"))

    def test_paris_date_uses_local_day_not_utc(self):
        late_evening = datetime.fromisoformat("2026-11-06T23:30:00+00:00")
        self.assertEqual(paris_date(late_evening), "07/11/2026")

    def test_weekly_recurrence_is_expanded_inside_the_window(self):
        start = datetime.fromisoformat("2026-11-02T10:00:00+01:00")
        end = datetime.fromisoformat("2026-11-02T11:00:00+01:00")
        window_start = datetime.fromisoformat("2026-11-01T00:00:00+01:00")
        window_end = datetime.fromisoformat("2026-11-24T00:00:00+01:00")
        occurrences = expand_occurrences(
            start, end, "FREQ=WEEKLY", None, window_start, window_end
        )
        self.assertEqual(len(occurrences), 4)
        skipped = expand_occurrences(
            start, end, "FREQ=WEEKLY", [start], window_start, window_end
        )
        self.assertEqual(len(skipped), 3)
        outside = expand_occurrences(
            start, end, None, None,
            datetime.fromisoformat("2026-12-01T00:00:00+01:00"),
            datetime.fromisoformat("2026-12-08T00:00:00+01:00"),
        )
        self.assertEqual(outside, [])

    def test_empty_sync_keeps_existing_events(self):
        self.assertTrue(should_keep_previous_events(0, "un cours\n"))
        self.assertFalse(should_keep_previous_events(2, "un cours\n"))
        self.assertFalse(should_keep_previous_events(0, ""))

    def test_sync_ignores_days_before_the_start_date(self):
        limit = datetime(2026, 11, 1).date()
        october = datetime.fromisoformat("2026-10-31T23:30:00+01:00")
        november = datetime.fromisoformat("2026-11-01T00:30:00+01:00")
        self.assertTrue(starts_before_day(october, limit))
        self.assertFalse(starts_before_day(november, limit))
        self.assertFalse(starts_before_day(october, None))

    def test_amount_is_read_from_a_compressed_pdf(self):
        stream = zlib.compress("Montant total à régler : 22.50 EUR".encode("latin-1"))
        pdf = b"stream\n" + stream + b"\nendstream"
        self.assertEqual(pdf_generator.amount_in_pdf_bytes(pdf), 22.5)

    def test_process_events_does_not_invent_a_rate_or_rebill(self):
        db_file = tempfile.NamedTemporaryFile(prefix="agendatobill-", suffix=".sqlite", delete=False)
        db_file.close()
        os.environ["AGENDA_DATABASE_URL"] = "sqlite:///" + db_file.name
        try:
            import app as webapp
            from agendatobill.models import InvoiceDocument, InvoicedEvent, Student, SyncCache, db

            events = "\n".join([
                "2026-11-04T17:00:00+01:00|2026-11-04T18:00:00+01:00|Cours Camille Martin",
                "2026-11-04T19:00:00+01:00|2026-11-04T20:30:00+01:00|Cours Camille Martin",
                "2026-11-05T17:00:00+01:00|2026-11-05T18:00:00+01:00|Cours Inconnu",
            ])
            with webapp.app.app_context():
                db.drop_all()
                db.create_all()
                db.session.add(Student(nom="camille martin", tarif=40, parent="", adresse=""))
                db.session.add(SyncCache(key="raw_events", data_text=events))
                db.session.commit()

                with mock.patch("builtins.print"):
                    first = pdf_generator.process_events()
                    second = pdf_generator.process_events()

                self.assertEqual(first["created"], 2)
                self.assertTrue(any("inconnu" in warning.lower() for warning in first["warnings"]))
                self.assertEqual(second["created"], 0)
                self.assertEqual(second["skipped"], 2)
                pdfs = InvoiceDocument.query.filter(InvoiceDocument.filename.endswith(".pdf")).all()
                self.assertEqual(len(pdfs), 2)
                self.assertEqual(sorted(row.invoice_number for row in pdfs), [1, 2])
                self.assertTrue(all(bytes(row.content).startswith(b"%PDF") for row in pdfs))
                self.assertTrue(any("_n1.pdf" in row.filename for row in pdfs))
                self.assertAlmostEqual(sum(row.montant for row in pdfs), 100.0)
                recap = db.session.get(InvoiceDocument, "recapitulatif_urssaf.txt")
                text = bytes(recap.content).decode("utf-8")
                self.assertIn("Novembre 2026", text)
                self.assertIn("100.00", text)
                self.assertIn("TOTAL FACTURE", text)

                client = webapp.app.test_client()
                with client.session_transaction() as sess:
                    sess["logged_in"] = True
                    sess["csrf_token"] = "token-test"
                viewed = client.get("/view/" + pdfs[0].filename)
                self.assertEqual(viewed.status_code, 200)
                self.assertEqual(viewed.mimetype, "application/pdf")
                self.assertTrue(viewed.data.startswith(b"%PDF"))
                archived = client.post("/download_zip", data={"csrf_token": "token-test"})
                self.assertEqual(archived.status_code, 200)
                self.assertTrue(archived.data.startswith(b"PK"))
                latest = max(pdfs, key=lambda row: row.invoice_number)
                removed_key = latest.event_key
                removed = client.post("/delete_file", data={
                    "csrf_token": "token-test",
                    "filename": latest.filename,
                })
                self.assertEqual(removed.status_code, 302)
                self.assertIsNone(db.session.get(InvoiceDocument, latest.filename))
                self.assertIsNone(db.session.get(InvoicedEvent, removed_key))

                with mock.patch("builtins.print"):
                    third = pdf_generator.process_events()
                self.assertEqual(third["created"], 1)
                self.assertEqual(third["skipped"], 1)
                pdfs = InvoiceDocument.query.filter(InvoiceDocument.filename.endswith(".pdf")).all()
                self.assertEqual(sorted(row.invoice_number for row in pdfs), [1, 2])

                db.session.add(InvoiceDocument(
                    filename="Facture_Camille_Martin_01-11-2026.pdf",
                    content=b"%PDF-1.3",
                    created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                    montant=10,
                ))
                db.session.commit()
                pdf_generator.assign_invoice_numbers()
                numbered = (
                    InvoiceDocument.query
                    .filter(InvoiceDocument.filename.endswith(".pdf"))
                    .order_by(InvoiceDocument.invoice_number)
                    .all()
                )
                self.assertEqual([row.invoice_number for row in numbered], [1, 2, 3])
                self.assertIn("01-11-2026", numbered[0].filename)
                self.assertTrue(numbered[0].filename.endswith("_n1.pdf"))
        finally:
            os.environ.pop("AGENDA_DATABASE_URL", None)
            os.remove(db_file.name)


if __name__ == "__main__":
    unittest.main()
