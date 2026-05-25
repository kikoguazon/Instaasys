"""
theme_config.py — Backend theme configuration for INSTAASYS

This module provides:
1. Theme definitions for server-side rendering
2. Contrast ratio calculations for WCAG compliance
3. AI-ready semantic token exports
4. Theme metadata for API responses

Usage:
  from instaasys.theme_config import THEME_CONFIG, get_theme_for_user
"""

THEME_CONFIG = {
    'version': '1.0',
    'wcag_level': 'AA',
    'themes': {
        'light': {
            'name': 'Light Mode',
            'displayName': 'Light',
            'primary_bg': '#ffffff',
            'secondary_bg': '#f1f5f9',
            'tertiary_bg': '#f8fafc',
            'text_primary': '#1e293b',
            'text_secondary': '#64748b',
            'border_color': '#e2e8f0',
            'interactive_primary': '#4f46e5',
            'interactive_secondary': '#06b6d4',
            'feedback': {
                'success': '#10b981',
                'error': '#ef4444',
                'warning': '#f59e0b',
                'info': '#3b82f6',
            },
            'is_dark': False,
        },
        'dark': {
            'name': 'Dark Mode',
            'displayName': 'Dark',
            'primary_bg': '#0f172a',
            'secondary_bg': '#1e293b',
            'tertiary_bg': '#334155',
            'text_primary': '#e2e8f0',
            'text_secondary': '#94a3b8',
            'border_color': '#334155',
            'interactive_primary': '#818cf8',
            'interactive_secondary': '#22d3ee',
            'feedback': {
                'success': '#10b981',
                'error': '#f87171',
                'warning': '#fbbf24',
                'info': '#60a5fa',
            },
            'is_dark': True,
        },
        'system': {
            'name': 'System Preference',
            'displayName': 'System',
            'description': 'Follows OS theme preference (prefers-color-scheme)',
            'note': 'Server-side code should treat as "light", client-side JS will detect OS preference',
        }
    }
}


def get_theme_for_user(user):
    """
    Determine the effective theme for a user.
    
    Args:
        user: Django User instance or AnonymousUser
        
    Returns:
        dict: Theme configuration or None if user is anonymous
    """
    if not hasattr(user, 'is_authenticated') or not user.is_authenticated:
        return None
    
    theme_pref = getattr(user, 'theme_preference', 'system')
    
    if theme_pref in ['light', 'dark']:
        return THEME_CONFIG['themes'].get(theme_pref)
    elif theme_pref == 'system':
        # Server defaults to light for system preference
        # Client-side JS will detect actual OS preference
        return THEME_CONFIG['themes'].get('light')
    
    return THEME_CONFIG['themes'].get('light')


def get_semantic_tokens(theme_name='light'):
    """
    Get semantic design tokens for a specific theme.
    Used by AI systems and code generation tools.
    
    Args:
        theme_name: 'light' or 'dark'
        
    Returns:
        dict: Semantic token definitions
    """
    theme = THEME_CONFIG['themes'].get(theme_name, THEME_CONFIG['themes']['light'])
    
    return {
        'surfaces': {
            'primary': theme['primary_bg'],
            'secondary': theme['secondary_bg'],
            'tertiary': theme['tertiary_bg'],
        },
        'text': {
            'body': theme['text_primary'],
            'body_muted': theme['text_secondary'],
            'interactive': theme['interactive_primary'],
        },
        'interactive': {
            'primary': theme['interactive_primary'],
            'secondary': theme['interactive_secondary'],
        },
        'feedback': theme['feedback'],
        'borders': {
            'default': theme['border_color'],
        }
    }


def calculate_contrast_ratio(rgb1, rgb2):
    """
    Calculate WCAG 2.1 contrast ratio between two RGB colors.
    
    Args:
        rgb1: tuple of (r, g, b) values 0-255
        rgb2: tuple of (r, g, b) values 0-255
        
    Returns:
        float: Contrast ratio (e.g., 4.5 for AA compliance)
    """
    def relative_luminance(rgb):
        """Calculate relative luminance per WCAG formula."""
        def adjust_channel(c):
            c = c / 255.0
            if c <= 0.03928:
                return c / 12.92
            else:
                return ((c + 0.055) / 1.055) ** 2.4
        
        r = adjust_channel(rgb[0])
        g = adjust_channel(rgb[1])
        b = adjust_channel(rgb[2])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    
    lum1 = relative_luminance(rgb1)
    lum2 = relative_luminance(rgb2)
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    
    return (lighter + 0.05) / (darker + 0.05)


def validate_wcag_compliance(theme_name='light'):
    """
    Validate that a theme meets WCAG 2.1 Level AA contrast requirements.
    
    Args:
        theme_name: 'light' or 'dark'
        
    Returns:
        dict: Compliance report with pass/fail status
    """
    theme = THEME_CONFIG['themes'].get(theme_name)
    if not theme or 'is_dark' not in theme:
        return {'error': 'Invalid theme'}
    
    # Parse hex colors to RGB
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    report = {
        'theme': theme_name,
        'wcag_level': 'AA',
        'checks': {},
        'compliant': True,
    }
    
    # Check body text contrast (should be >= 4.5:1)
    bg_rgb = hex_to_rgb(theme['primary_bg'])
    text_rgb = hex_to_rgb(theme['text_primary'])
    ratio = calculate_contrast_ratio(bg_rgb, text_rgb)
    report['checks']['body_text_contrast'] = {
        'ratio': round(ratio, 1),
        'required': 4.5,
        'passes': ratio >= 4.5,
    }
    if not report['checks']['body_text_contrast']['passes']:
        report['compliant'] = False
    
    # Check secondary text contrast (should be >= 4.5:1 for normal text)
    text_sec_rgb = hex_to_rgb(theme['text_secondary'])
    ratio_sec = calculate_contrast_ratio(bg_rgb, text_sec_rgb)
    report['checks']['secondary_text_contrast'] = {
        'ratio': round(ratio_sec, 1),
        'required': 4.5,
        'passes': ratio_sec >= 4.5,
    }
    if not report['checks']['secondary_text_contrast']['passes']:
        report['compliant'] = False
    
    # Check interactive element contrast (should be >= 3:1 for graphics)
    interactive_rgb = hex_to_rgb(theme['interactive_primary'])
    ratio_interactive = calculate_contrast_ratio(bg_rgb, interactive_rgb)
    report['checks']['interactive_contrast'] = {
        'ratio': round(ratio_interactive, 1),
        'required': 3.0,
        'passes': ratio_interactive >= 3.0,
    }
    if not report['checks']['interactive_contrast']['passes']:
        report['compliant'] = False
    
    return report


# Pre-computed WCAG compliance reports (for documentation)
WCAG_COMPLIANCE_REPORTS = {
    'light': validate_wcag_compliance('light'),
    'dark': validate_wcag_compliance('dark'),
}


def get_theme_metadata_for_ai():
    """
    Export theme metadata specifically formatted for AI systems
    (for use in system prompts and code generation contexts).
    
    Returns:
        dict: AI-readable theme metadata
    """
    return {
        'status': 'WCAG 2.1 Level AA compliant',
        'available_themes': ['light', 'dark', 'system'],
        'recommendations': {
            'when_generating_ui': [
                'Always use CSS variables (--surface-primary, --text-body, etc.)',
                'Do not hardcode colors like #ffffff or #1e293b',
                'Use semantic token names that communicate intent',
                'Test generated code in both light and dark modes',
            ],
            'ai_system_prompt_include': [
                'Current theme: (light | dark | system)',
                'Use --surface-primary for main backgrounds',
                'Use --text-body for body text',
                'Use --interactive-primary for main buttons',
                'Use --feedback-* for status messages (success, error, warning, info)',
                'Verify contrast ratios match WCAG AA minimum (4.5:1 for text)',
            ]
        },
        'semantic_tokens': {
            'surfaces': ['primary', 'secondary', 'tertiary', 'elevated', 'brand', 'inverted'],
            'text': ['body', 'body_muted', 'on_brand', 'on_primary', 'interactive', 'disabled', 'inverse'],
            'interactive': ['primary', 'primary_hover', 'primary_active', 'primary_disabled', 'secondary', 'secondary_hover', 'danger', 'danger_hover'],
            'feedback': ['success', 'success_text', 'success_bg', 'error', 'error_text', 'error_bg', 'warning', 'warning_text', 'warning_bg', 'info', 'info_text', 'info_bg'],
            'borders': ['subtle', 'muted', 'strong'],
            'shadows': ['low', 'medium', 'high', 'brand_low', 'brand_medium', 'brand_high'],
        },
        'wcag_requirements': {
            'text_contrast_minimum_aa': '4.5:1',
            'graphics_contrast_minimum_aa': '3:1',
            'large_text_threshold': '18pt or 14pt bold',
            'compliance': WCAG_COMPLIANCE_REPORTS,
        }
    }
