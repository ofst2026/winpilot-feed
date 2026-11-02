"""WinPilot regression tests. Run: python -m unittest -v test_winpilot"""
import datetime as dt
import unittest
from unittest.mock import patch
import fetch_feed as f

class WinPilotTests(unittest.TestCase):
    def test_numeric_titles_removed(self):
        self.assertFalse(f.meaningful_title('3047447'))
        self.assertTrue(f.meaningful_title('Tickets für ein Konzert gewinnen'))
    def test_normalize_tracking(self):
        self.assertEqual(f.normalize_url('https://example.org/aktion/?utm_source=abc&x=2#top'), 'https://example.org/aktion?x=2')
    def test_action_without_keyword_in_url(self):
        self.assertTrue(f.is_contest_candidate('https://example.org/promo/stories/123', 'Tickets gewinnen'))
    def test_aggregator_sections_excluded(self):
        self.assertFalse(f.is_contest_candidate('https://example.org/gewinnspiele/', 'Gewinnspiele'))
    def test_known_deadline(self):
        self.assertEqual(f.deadline_from_title('Teilnahmeschluss: 30.11.2026'), '2026-11-30')
    def test_unknown_deadline(self):
        self.assertEqual(f.deadline_from_title('Teilnahmeschluss: 30.11.'), '')
    def test_dates_with_slashes_and_month(self):
        with patch.object(f,'TODAY',dt.date(2026,11,2)):
            self.assertEqual(f.extract_deadline('Teilnahmeschluss: 30/11/2026'), '2026-11-30')
            self.assertEqual(f.extract_deadline('Einsendeschluss am 15. Dezember 2026'), '2026-12-15')
            self.assertEqual(f.extract_deadline('Aktionsende: 01.01.2025'), '')
    def test_no_verification_from_search(self):
        self.assertEqual(f.reason_for({'direct_link':False,'deadline':False,'free':False,'country':False,'entry':False},'Google News'), 'Pressehinweis: kein bestätigter direkter Veranstalterlink')
    def test_positive_page_with_explicit_evidence(self):
        html='<h1>Gewinnspiel: Tickets gewinnen</h1><p>Jetzt teilnehmen</p><form action="/entry"></form>'
        text='Gewinnspiel: Tickets gewinnen. Teilnahmebedingungen. Teilnahmeschluss: 30.11.2026. Kostenlose Teilnahme. Teilnahmeberechtigt sind Personen mit Wohnsitz in Österreich. Jetzt teilnehmen.'
        with patch.object(f,'TODAY',dt.date(2026,11,2)),patch.object(f,'read_official_page',return_value=(text,html,[], 'https://example.org/gewinnspiel/tickets')):
            verified,deadline,checks=f.check_page('https://example.org/gewinnspiel/tickets','Österreich')
            self.assertTrue(verified)
            self.assertEqual(deadline,'2026-11-30')
            self.assertTrue(all(checks.values()))
    def test_no_auto_verification_without_entry_form(self):
        text='Gewinnspiel Tickets gewinnen. Teilnahmebedingungen. Teilnahmeschluss: 30.11.2026. Kostenlose Teilnahme. Teilnahmeberechtigt sind Personen mit Wohnsitz in Österreich. Jetzt teilnehmen.'
        with patch.object(f,'TODAY',dt.date(2026,11,2)),patch.object(f,'read_official_page',return_value=(text,'<h1>Gewinnspiel</h1>',[], 'https://example.org/gewinnspiel/tickets')):
            self.assertFalse(f.check_page('https://example.org/gewinnspiel/tickets','Österreich')[0])
    def test_restricted_age_not_verified(self):
        text='Gewinnspiel Tickets gewinnen. Teilnahmebedingungen. Teilnahmeschluss: 30.11.2026. Kostenlose Teilnahme. Teilnahmeberechtigt sind Personen mit Wohnsitz in Österreich ab 18 Jahren. Jetzt teilnehmen.'
        with patch.object(f,'TODAY',dt.date(2026,11,2)),patch.object(f,'read_official_page',return_value=(text,'<form></form>',[], 'https://example.org/gewinnspiel/tickets')):
            self.assertFalse(f.check_page('https://example.org/gewinnspiel/tickets','Österreich')[0])

if __name__=='__main__': unittest.main()
