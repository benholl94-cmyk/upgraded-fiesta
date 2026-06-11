#!/usr/bin/env python3
"""Unit tests for scripts/validate.py logic."""
import importlib.util
import json
import re
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load validate module without executing main() at import time.
# ---------------------------------------------------------------------------
_VALIDATE_PATH = Path(__file__).resolve().parent / 'validate.py'
_spec = importlib.util.spec_from_file_location('validate', _VALIDATE_PATH)
_validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validate)

GUIDE_BLOCKLIST = _validate.GUIDE_BLOCKLIST
REQUIRED_HTML = _validate.REQUIRED_HTML
TEXT_FILES = _validate.TEXT_FILES


class TestFailHelper(unittest.TestCase):
    def test_fail_exits_with_code_1(self):
        with self.assertRaises(SystemExit) as ctx:
            _validate.fail('something went wrong')
        self.assertEqual(ctx.exception.code, 1)

    def test_fail_writes_to_stderr(self):
        with self.assertRaises(SystemExit):
            with patch('sys.stderr', new_callable=StringIO) as fake_err:
                _validate.fail('test error message')
                self.assertIn('test error message', fake_err.getvalue())
                self.assertIn('validation failed', fake_err.getvalue())


class TestGuideBlocklistPatterns(unittest.TestCase):
    """Each pattern in GUIDE_BLOCKLIST must match bad content and not match clean content."""

    def _matches(self, pattern, text):
        return bool(re.search(pattern, text, flags=re.I))

    def test_photo_ocr_pattern_matches_Foto(self):
        pattern = GUIDE_BLOCKLIST[0]
        self.assertTrue(self._matches(pattern, 'Ein Foto wurde gescannt'))

    def test_photo_ocr_pattern_matches_photo(self):
        pattern = GUIDE_BLOCKLIST[0]
        self.assertTrue(self._matches(pattern, 'upload a photo here'))

    def test_photo_ocr_pattern_matches_OCR(self):
        pattern = GUIDE_BLOCKLIST[0]
        self.assertTrue(self._matches(pattern, 'OCR-Erkennung aktiv'))

    def test_photo_ocr_pattern_matches_Bildfehler(self):
        pattern = GUIDE_BLOCKLIST[0]
        self.assertTrue(self._matches(pattern, 'Bildfehler im Dokument'))

    def test_photo_ocr_pattern_does_not_match_clean_text(self):
        pattern = GUIDE_BLOCKLIST[0]
        self.assertFalse(self._matches(pattern, 'git clone und python3 ausführen'))

    def test_photo_ocr_pattern_word_boundary_prevents_partial(self):
        pattern = GUIDE_BLOCKLIST[0]
        # "photograph" should not match "\bFoto\b"
        self.assertFalse(self._matches(pattern, 'photograph'))

    def test_todo_fixme_pattern_matches_TODO(self):
        pattern = GUIDE_BLOCKLIST[1]
        self.assertTrue(self._matches(pattern, '# TODO: implement this'))

    def test_todo_fixme_pattern_matches_FIXME(self):
        pattern = GUIDE_BLOCKLIST[1]
        self.assertTrue(self._matches(pattern, 'FIXME: broken logic'))

    def test_todo_fixme_pattern_matches_XXX(self):
        pattern = GUIDE_BLOCKLIST[1]
        self.assertTrue(self._matches(pattern, 'XXX remove before release'))

    def test_todo_fixme_pattern_does_not_match_clean_text(self):
        pattern = GUIDE_BLOCKLIST[1]
        self.assertFalse(self._matches(pattern, 'git commit -m "add feature"'))

    def test_blind_remote_exec_pattern_matches_curl_pipe_sh(self):
        pattern = GUIDE_BLOCKLIST[2]
        self.assertTrue(self._matches(pattern, 'curl https://example.org/install.sh | sh'))

    def test_blind_remote_exec_pattern_matches_wget_pipe_bash(self):
        pattern = GUIDE_BLOCKLIST[2]
        self.assertTrue(self._matches(pattern, 'wget -q https://host/script | bash'))

    def test_blind_remote_exec_pattern_does_not_match_plain_curl(self):
        pattern = GUIDE_BLOCKLIST[2]
        self.assertFalse(self._matches(pattern, 'curl https://api.example.org/data'))

    def test_blind_remote_exec_pattern_does_not_match_plain_wget(self):
        pattern = GUIDE_BLOCKLIST[2]
        self.assertFalse(self._matches(pattern, 'wget -O file.txt https://host/file'))

    def test_example_com_pattern_matches(self):
        pattern = GUIDE_BLOCKLIST[3]
        self.assertTrue(self._matches(pattern, 'visit http://example.com/page'))

    def test_example_com_pattern_case_insensitive(self):
        pattern = GUIDE_BLOCKLIST[3]
        self.assertTrue(self._matches(pattern, 'EXAMPLE.COM'))

    def test_example_com_pattern_does_not_match_other_domains(self):
        pattern = GUIDE_BLOCKLIST[3]
        self.assertFalse(self._matches(pattern, 'https://github.com/user/repo'))

    def test_none_artifact_pattern_matches_word_None(self):
        pattern = GUIDE_BLOCKLIST[4]
        self.assertTrue(self._matches(pattern, 'Wert ist None'))

    def test_none_artifact_pattern_word_boundary(self):
        pattern = GUIDE_BLOCKLIST[4]
        # "None" as a substring inside a word should not match
        self.assertFalse(self._matches(pattern, 'someone'))

    def test_none_artifact_pattern_does_not_match_clean_text(self):
        pattern = GUIDE_BLOCKLIST[4]
        self.assertFalse(self._matches(pattern, 'git push origin main'))


class TestRequiredHtml(unittest.TestCase):
    """REQUIRED_HTML needles must be present in a valid HTML string."""

    VALID_HTML_SNIPPETS = {
        'id="access"': '<section id="access">',
        'class="skip-link"': '<a class="skip-link" href="#main">',
        'aria-pressed="true"': '<button aria-pressed="true">',
        'id="safety"': '<section id="safety">',
        'id="requests"': '<section id="requests">',
        'id="requestOutput"': '<code id="requestOutput">',
        'id="main"': '<main id="main">',
    }

    def test_all_required_html_needles_defined(self):
        self.assertEqual(len(REQUIRED_HTML), 7)

    def test_each_required_needle_in_valid_snippet(self):
        for needle in REQUIRED_HTML:
            with self.subTest(needle=needle):
                self.assertIn(needle, self.VALID_HTML_SNIPPETS[needle])

    def test_missing_needle_detected(self):
        html = '<html><body><p>nothing here</p></body></html>'
        for needle in REQUIRED_HTML:
            self.assertNotIn(needle, html)


class TestHeadingValidation(unittest.TestCase):
    """Replicate the guide heading check from main()."""

    def _extract_headings(self, text):
        return [int(v) for v in re.findall(r'^## (\d+)\. ', text, flags=re.M)]

    def test_sequential_headings_pass(self):
        text = '\n'.join(f'## {i}. Section {i}' for i in range(1, 21)) + '\n'
        headings = self._extract_headings(text)
        expected = list(range(1, len(headings) + 1))
        self.assertEqual(headings, expected)
        self.assertGreaterEqual(len(headings), 20)

    def test_non_sequential_headings_fail(self):
        text = '## 1. One\n## 3. Three\n'
        headings = self._extract_headings(text)
        expected = list(range(1, len(headings) + 1))
        self.assertNotEqual(headings, expected)

    def test_fewer_than_20_headings_fail(self):
        text = '\n'.join(f'## {i}. Section {i}' for i in range(1, 10)) + '\n'
        headings = self._extract_headings(text)
        self.assertLess(len(headings), 20)

    def test_empty_text_yields_no_headings(self):
        headings = self._extract_headings('')
        self.assertEqual(headings, [])

    def test_non_numbered_headings_not_counted(self):
        text = '## Introduction\n## Setup\n'
        headings = self._extract_headings(text)
        self.assertEqual(headings, [])

    def test_heading_starting_at_2_fails_sequence(self):
        text = '\n'.join(f'## {i}. Section {i}' for i in range(2, 22)) + '\n'
        headings = self._extract_headings(text)
        expected = list(range(1, len(headings) + 1))
        self.assertNotEqual(headings, expected)


class TestFileChecks(unittest.TestCase):
    """Replicate per-file validation rules from main()."""

    def test_missing_final_newline_detected(self):
        text = 'hello world'
        self.assertFalse(text.endswith('\n'))

    def test_present_final_newline_passes(self):
        text = 'hello world\n'
        self.assertTrue(text.endswith('\n'))

    def test_tab_character_detected(self):
        text = 'key\tvalue\n'
        self.assertIn('\t', text)

    def test_no_tab_passes(self):
        text = 'key  value\n'
        self.assertNotIn('\t', text)


class TestManifestValidation(unittest.TestCase):
    """manifest.webmanifest must be valid JSON with required fields."""

    def test_valid_manifest_parses(self):
        data = json.loads('{"name": "iPhone Dev Platform", "short_name": "iPhoneDev", "start_url": "./index.html", "display": "standalone", "background_color": "#0f172a", "theme_color": "#0f172a", "icons": []}\n')
        self.assertEqual(data['name'], 'iPhone Dev Platform')
        self.assertEqual(data['display'], 'standalone')

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            json.loads('{broken json')

    def test_empty_icons_array_valid(self):
        data = json.loads('{"name": "X", "icons": []}\n')
        self.assertIsInstance(data['icons'], list)
        self.assertEqual(len(data['icons']), 0)


class TestMainWithRealFiles(unittest.TestCase):
    """Integration: run main() against the real project files; they must pass."""

    def test_main_passes_with_real_project_files(self):
        """main() should not raise SystemExit when project files are valid."""
        with patch('builtins.print'):
            try:
                _validate.main()
            except SystemExit as exc:
                self.fail(f'validate.main() failed unexpectedly: {exc}')


class TestTextFilesList(unittest.TestCase):
    def test_text_files_contains_expected_entries(self):
        self.assertIn('README.md', TEXT_FILES)
        self.assertIn('docs/iphone-local-dev-setup.md', TEXT_FILES)
        self.assertIn('index.html', TEXT_FILES)
        self.assertIn('styles.css', TEXT_FILES)
        self.assertIn('app.js', TEXT_FILES)
        self.assertIn('manifest.webmanifest', TEXT_FILES)
        self.assertIn('service-worker.js', TEXT_FILES)

    def test_text_files_has_seven_entries(self):
        self.assertEqual(len(TEXT_FILES), 7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
