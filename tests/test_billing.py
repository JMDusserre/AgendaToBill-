import json
import os
import tempfile
import unittest
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

    def test_process_events_does_not_invent_a_rate_or_rebill(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            os.environ["AGENDA_DATA_DIR"] = tmp
            os.environ["AGENDA_INVOICE_DIR"] = os.path.join(tmp, "factures")
            try:
                with open("students.json", "w", encoding="utf-8") as handle:
                    json.dump({"camille martin": {"tarif": 40, "parent": "", "adresse": ""}}, handle)
                events = "\n".join([
                    "2026-11-04T17:00:00+01:00|2026-11-04T18:00:00+01:00|Cours Camille Martin",
                    "2026-11-04T19:00:00+01:00|2026-11-04T20:30:00+01:00|Cours Camille Martin",
                    "2026-11-05T17:00:00+01:00|2026-11-05T18:00:00+01:00|Cours Inconnu",
                ])
                with open("raw_events.txt", "w", encoding="utf-8") as handle:
                    handle.write(events)

                with mock.patch("builtins.print"):
                    first = pdf_generator.process_events()
                    second = pdf_generator.process_events()

                self.assertEqual(first["created"], 2)
                self.assertTrue(any("inconnu" in warning.lower() for warning in first["warnings"]))
                self.assertEqual(second["created"], 0)
                self.assertEqual(second["skipped"], 2)
                pdfs = [name for name in os.listdir("factures") if name.endswith(".pdf")]
                self.assertEqual(len(pdfs), 2)
                with open("factures/recapitulatif_urssaf.txt", encoding="utf-8") as handle:
                    recap = handle.read()
                self.assertIn("CE LOT", recap)
                self.assertIn("100.00", recap)
            finally:
                os.environ.pop("AGENDA_DATA_DIR", None)
                os.environ.pop("AGENDA_INVOICE_DIR", None)
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
