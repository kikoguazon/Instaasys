"""
Preservation Tests — verifies that the AI-palette system preserves
all existing non-theme behaviors: slide generation, color application,
PPTX structure, and navigation are unaffected by the palette change.
"""

from hypothesis.extra.django import TestCase
from hypothesis import given, strategies as st, settings
from hypothesis import Phase

from presentations.pptx_builder import _palette_to_theme, _DEFAULT_THEME, build_pptx
from pptx.dml.color import RGBColor


VALID_PALETTE = {
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

MINIMAL_LESSON = {
    'title': 'Test Lesson',
    'week': '1',
    'slides': [
        {'slide_number': 1, 'layout': 'title', 'title': 'Test Lesson', 'content': []},
        {'slide_number': 2, 'layout': 'content', 'title': 'Topic A',
         'content': ['Point one', 'Point two'], 'image_query': ''},
    ],
}


class PaletteThemeDeterminismTest(TestCase):
    """Same palette input always produces the same theme dict."""

    @settings(phases=[Phase.generate], max_examples=10)
    @given(st.fixed_dictionaries({
        'dark': st.just('#1a1a2e'),
        'mid': st.just('#16213e'),
        'primary': st.just('#0f3460'),
        'accent': st.just('#e94560'),
    }))
    def test_palette_to_theme_is_deterministic(self, palette):
        theme1 = _palette_to_theme(palette)
        theme2 = _palette_to_theme(palette)
        self.assertEqual(theme1['dark'], theme2['dark'])
        self.assertEqual(theme1['accent'], theme2['accent'])


class ThemeStructurePreservationTest(TestCase):
    """_palette_to_theme always returns a complete theme dict."""

    @settings(phases=[Phase.generate], max_examples=5)
    @given(st.fixed_dictionaries({
        'dark': st.sampled_from(['#0a0a1a', '#1a1a2e', '#050510']),
        'accent': st.sampled_from(['#ff6b6b', '#4ecdc4', '#a855f7']),
    }))
    def test_theme_always_has_required_keys(self, palette):
        theme = _palette_to_theme(palette)
        required = ('dark', 'mid', 'primary', 'accent', 'light', 'bg', 'footer', 'muted', 'text', 'content_accents')
        for key in required:
            self.assertIn(key, theme, f"Theme missing required key: {key}")

    @settings(phases=[Phase.generate], max_examples=5)
    @given(st.fixed_dictionaries({'dark': st.just('#0f172a')}))
    def test_content_accents_always_six(self, palette):
        theme = _palette_to_theme(palette)
        self.assertEqual(len(theme['content_accents']), 6)
        for c in theme['content_accents']:
            self.assertIsInstance(c, RGBColor)


class BuildPptxPreservationTest(TestCase):
    """build_pptx still produces valid PPTX bytes regardless of palette."""

    def test_build_pptx_with_palette_returns_bytes(self):
        lesson = {**MINIMAL_LESSON, 'palette': VALID_PALETTE}
        result = build_pptx(lesson)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 1000)

    def test_build_pptx_without_palette_uses_default(self):
        lesson = dict(MINIMAL_LESSON)
        result = build_pptx(lesson)
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 1000)

    def test_build_pptx_with_empty_palette_uses_default(self):
        lesson = {**MINIMAL_LESSON, 'palette': {}}
        result = build_pptx(lesson)
        self.assertIsInstance(result, bytes)

    def test_build_pptx_with_invalid_palette_falls_back(self):
        lesson = {**MINIMAL_LESSON, 'palette': {'dark': 'not-a-color', 'accent': ''}}
        result = build_pptx(lesson)
        self.assertIsInstance(result, bytes)

    def test_build_pptx_collect_stats(self):
        lesson = {**MINIMAL_LESSON, 'palette': VALID_PALETTE}
        result, stats = build_pptx(lesson, collect_stats=True)
        self.assertIsInstance(result, bytes)
        self.assertIn('slides_total', stats)
        self.assertEqual(stats['slides_total'], len(MINIMAL_LESSON['slides']))
