"""
Palette System Tests — validates the AI-generated palette pipeline.

Tests that:
- _parse_hex correctly validates and normalises hex strings
- _palette_to_theme converts hex palette to RGBColor theme dict
- _build_palette_css generates valid CSS custom property declarations
- All required CSS variables are present in generated palette CSS
- Invalid/missing palette values fall back to safe defaults
"""

from hypothesis.extra.django import TestCase
from hypothesis import given, strategies as st, settings
from hypothesis import Phase

from presentations.pptx_builder import _parse_hex, _palette_to_theme, _DEFAULT_THEME
from presentations.views import _build_palette_css, _sanitize_hex
from pptx.dml.color import RGBColor


REQUIRED_CSS_VARS = [
    '--s-bg', '--s-bg-light', '--s-bg-card',
    '--s-accent', '--s-accent-soft', '--s-accent-dark',
    '--s-text', '--s-text-dark', '--s-text-muted',
    '--s-border', '--s-gradient-start', '--s-gradient-end',
    '--s-obj-color', '--s-mid',
    '--s-content-accent-1', '--s-content-accent-2', '--s-content-accent-3',
    '--s-content-accent-4', '--s-content-accent-5', '--s-content-accent-6',
]

SAMPLE_PALETTE = {
    'dark': '#0f172a',
    'mid': '#1e293b',
    'primary': '#1e40af',
    'accent': '#3b82f6',
    'light': '#dbeafe',
    'bg': '#f1f5f9',
    'muted': '#94a3b8',
    'text': '#1e293b',
    'text_light': '#f8fafc',
    'gradient_start': '#1e293b',
    'gradient_end': '#0f172a',
    'content_accents': ['#3b82f6', '#0d9488', '#4338ca', '#d97706', '#7c3aed', '#1e40af'],
}


class ParseHexTest(TestCase):
    def test_valid_lowercase(self):
        self.assertEqual(_parse_hex('#3b82f6', '#000000'), '#3B82F6')

    def test_valid_without_hash(self):
        self.assertEqual(_parse_hex('3b82f6', '#000000'), '#3B82F6')

    def test_invalid_returns_fallback(self):
        self.assertEqual(_parse_hex('nothex', '#FFFFFF'), '#FFFFFF')

    def test_empty_returns_fallback(self):
        self.assertEqual(_parse_hex('', '#AABBCC'), '#AABBCC')

    def test_none_returns_fallback(self):
        self.assertEqual(_parse_hex(None, '#112233'), '#112233')

    def test_too_short_returns_fallback(self):
        self.assertEqual(_parse_hex('#abc', '#112233'), '#112233')


class PaletteToThemeTest(TestCase):
    def test_full_palette_produces_rgb_colors(self):
        theme = _palette_to_theme(SAMPLE_PALETTE)
        for key in ('dark', 'mid', 'primary', 'accent', 'light', 'bg', 'footer', 'muted', 'text'):
            self.assertIsInstance(theme[key], RGBColor, f"'{key}' should be RGBColor")

    def test_content_accents_has_six_entries(self):
        theme = _palette_to_theme(SAMPLE_PALETTE)
        self.assertEqual(len(theme['content_accents']), 6)
        for color in theme['content_accents']:
            self.assertIsInstance(color, RGBColor)

    def test_empty_palette_falls_back_to_defaults(self):
        theme = _palette_to_theme({})
        self.assertIsInstance(theme['dark'], RGBColor)
        self.assertEqual(len(theme['content_accents']), 6)

    def test_partial_palette_fills_missing_with_defaults(self):
        theme = _palette_to_theme({'dark': '#ff0000'})
        self.assertEqual(theme['dark'], RGBColor(0xff, 0x00, 0x00))
        self.assertIsInstance(theme['mid'], RGBColor)

    def test_invalid_hex_falls_back(self):
        theme = _palette_to_theme({'dark': 'not-a-color'})
        self.assertIsInstance(theme['dark'], RGBColor)

    def test_accent_count_below_six_fills_remainder(self):
        palette = {**SAMPLE_PALETTE, 'content_accents': ['#ff0000', '#00ff00']}
        theme = _palette_to_theme(palette)
        self.assertEqual(len(theme['content_accents']), 6)


class BuildPaletteCssTest(TestCase):
    def test_all_required_vars_present(self):
        css = _build_palette_css(SAMPLE_PALETTE)
        for var in REQUIRED_CSS_VARS:
            self.assertIn(var, css, f"CSS var '{var}' missing from generated palette CSS")

    def test_empty_palette_produces_fallback_css(self):
        css = _build_palette_css({})
        for var in REQUIRED_CSS_VARS:
            self.assertIn(var, css, f"CSS var '{var}' missing from fallback palette CSS")

    def test_css_values_are_valid_hex(self):
        import re
        css = _build_palette_css(SAMPLE_PALETTE)
        values = re.findall(r'#[0-9a-fA-F]{6}', css)
        self.assertGreater(len(values), 10, "Should contain many hex color values")

    def test_no_unescaped_user_content(self):
        malicious = {**SAMPLE_PALETTE, 'dark': '</style><script>alert(1)</script>'}
        css = _build_palette_css(malicious)
        self.assertNotIn('<script>', css, "Malicious input should not appear in CSS output")
        self.assertIn('--s-bg:', css)


class DefaultThemeTest(TestCase):
    def test_default_theme_has_all_keys(self):
        for key in ('dark', 'mid', 'primary', 'accent', 'light', 'bg', 'footer', 'muted', 'text'):
            self.assertIn(key, _DEFAULT_THEME)
            self.assertIsInstance(_DEFAULT_THEME[key], RGBColor)

    def test_default_theme_has_six_content_accents(self):
        self.assertEqual(len(_DEFAULT_THEME['content_accents']), 6)
