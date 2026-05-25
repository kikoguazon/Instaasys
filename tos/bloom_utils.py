"""
tos/bloom_utils.py
Bloom's Taxonomy verb detection and TOS computation utilities.
Used by both the TOS form (JS mirrors this logic) and assessment generator.
"""

BLOOM_VERB_MAP = {
    'remember': [
        'define', 'identify', 'list', 'name', 'recall', 'recognize',
        'state', 'label', 'match', 'select', 'recite', 'memorize',
        'locate', 'outline', 'retrieve',
    ],
    'understand': [
        'explain', 'summarize', 'paraphrase', 'classify', 'compare',
        'discuss', 'distinguish', 'interpret', 'relate', 'translate',
        'illustrate', 'infer', 'predict', 'restate', 'describe',
        'differentiate',
    ],
    'apply': [
        'apply', 'demonstrate', 'solve', 'use', 'implement', 'execute',
        'operate', 'calculate', 'practice', 'employ', 'modify',
        'show', 'compute', 'construct', 'complete',
    ],
    'analyze': [
        'analyze', 'examine', 'investigate', 'categorize', 'deconstruct',
        'organize', 'attribute', 'contrast', 'test',
        'inspect', 'debate', 'diagram', 'question',
    ],
    'evaluate': [
        'evaluate', 'assess', 'judge', 'justify', 'critique', 'recommend',
        'defend', 'appraise', 'rate', 'validate', 'prioritize',
        'argue', 'support', 'value', 'determine',
    ],
    'create': [
        'create', 'design', 'develop', 'construct', 'produce', 'formulate',
        'compose', 'generate', 'plan', 'propose', 'integrate', 'devise',
        'invent', 'compile', 'assemble',
    ],
}

BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']

BLOOM_LABELS = {
    'remember':   'Remember',
    'understand': 'Understand',
    'apply':      'Apply',
    'analyze':    'Analyze',
    'evaluate':   'Evaluate',
    'create':     'Create',
}

BLOOM_COLORS = {
    'remember':   '#6b7280',
    'understand': '#3b82f6',
    'apply':      '#22c55e',
    'analyze':    '#f59e0b',
    'evaluate':   '#8b5cf6',
    'create':     '#ef4444',
}


def detect_bloom_level(cilo_text: str) -> str:
    """Detect Bloom's taxonomy level from CILO text using the leading verb."""
    if not cilo_text:
        return 'remember'
    words = cilo_text.strip().lower().split()
    if not words:
        return 'remember'
    first = words[0].rstrip('.,;:)')
    for level, verbs in BLOOM_VERB_MAP.items():
        if first in verbs:
            return level
    for word in words[:3]:
        clean = word.rstrip('.,;:)')
        for level, verbs in BLOOM_VERB_MAP.items():
            if clean in verbs:
                return level
    return 'remember'


def get_bloom_distribution(cilos: list) -> dict:
    """Count CILOs per Bloom's level. Returns {remember: N, understand: N, ...}."""
    dist = {level: 0 for level in BLOOM_ORDER}
    for cilo in cilos:
        dist[detect_bloom_level(cilo)] += 1
    return dist


def compute_tos(topics: list, total_items: int, hours_per_week: int = 5) -> list:
    """
    Auto-compute full TOS item distribution.

    Args:
        topics: list of dicts with: week, topic, cilos (list of strings).
                May include hours to override the default.
        total_items: total exam items.
        hours_per_week: default contact hours per week.

    Returns:
        Same list enriched with: hours, percentage, bloom_distribution,
        remember, understand, apply, analyze, evaluate, create, total, placement.
    """
    for t in topics:
        t['hours'] = t.get('hours', hours_per_week)

    total_hours = sum(t['hours'] for t in topics)
    if total_hours == 0:
        return topics

    remaining = total_items
    for i, t in enumerate(topics):
        t['percentage'] = round((t['hours'] / total_hours) * 100, 1)
        if i == len(topics) - 1:
            t['total'] = remaining
        else:
            t['total'] = round((t['hours'] / total_hours) * total_items)
            remaining -= t['total']

        cilos = t.get('cilos', [])
        bloom_dist = get_bloom_distribution(cilos)
        t['bloom_distribution'] = bloom_dist

        cilo_total = sum(bloom_dist.values()) or 1
        items_left = t['total']
        for j, level in enumerate(BLOOM_ORDER):
            if j == len(BLOOM_ORDER) - 1:
                t[level] = max(0, items_left)
            else:
                t[level] = round((bloom_dist[level] / cilo_total) * t['total'])
                items_left -= t[level]

    current = 1
    for t in topics:
        if t['total'] > 0:
            t['placement'] = f"{current}-{current + t['total'] - 1}"
            current += t['total']
        else:
            t['placement'] = '—'

    return topics


def build_tos_context_for_ai(tos_data: dict) -> str:
    """Build a TOS context string for inclusion in AI assessment prompts."""
    if not tos_data:
        return ''
    lines = [
        f"TOS Blueprint: {tos_data.get('exam_type', 'Examination')} "
        f"({tos_data.get('total_items', '?')} total items)",
        "Distribute questions matching this exact Bloom's level count per topic:",
    ]
    for row in tos_data.get('rows', []):
        parts = []
        for level in BLOOM_ORDER:
            count = row.get(level, 0)
            if count:
                parts.append(f"{count} {BLOOM_LABELS[level]}")
        if parts:
            lines.append(
                f"  • {row['topic']}: {', '.join(parts)} "
                f"= {row.get('total', 0)} items (items {row.get('placement', '?')})"
            )
    return '\n'.join(lines)
