# instaasys/ai_service.py

import json
import logging
import re
import time
import threading
from django.conf import settings
from openai import OpenAI, RateLimitError

logger = logging.getLogger(__name__)

# How long (seconds) a rate-limited provider is skipped before retrying
COOLDOWN_SECONDS = 60

# ─── Provider Registry ────────────────────────────────────────────────────────
#
# Priority order: Groq (fast/free) → OpenAI → Gemini
# A provider is only activated if its API key is present in settings.

_PROVIDER_CONFIGS = [
    {
        'name': 'groq',
        'base_url': 'https://api.groq.com/openai/v1',
        'key_setting': 'GROQ_API_KEY',
        'model': 'llama-3.3-70b-versatile',
    },
    {
        'name': 'sambanova',
        'base_url': 'https://api.sambanova.ai/v1',
        'key_setting': 'SAMBANOVA_API_KEY',
        'model': 'Meta-Llama-3.3-70B-Instruct',
    },
    {
        'name': 'openai',
        'base_url': None,  # uses the default OpenAI endpoint
        'key_setting': 'OPENAI_API_KEY',
        'model': 'gpt-4o-mini',
    },
    {
        'name': 'gemini',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'key_setting': 'GEMINI_API_KEY',
        'model': 'gemini-2.0-flash',
    },
]

_state_lock = threading.Lock()

# Per-provider runtime state: cooldown_until (epoch), calls, errors
_provider_state: dict = {}

# Ordered list of active providers built once at import time
_providers: list = []

# Rate-limit event log — keeps last 50 events in memory
_rate_limit_log: list = []
_MAX_RATE_LIMIT_LOG = 50


def _build_providers():
    """Initialise active providers from available API keys."""
    providers = []
    for cfg in _PROVIDER_CONFIGS:
        key = getattr(settings, cfg['key_setting'], None)
        if not key:
            logger.debug(f"AI provider '{cfg['name']}' skipped (no API key).")
            continue
        kwargs = {'api_key': key}
        if cfg['base_url']:
            kwargs['base_url'] = cfg['base_url']
        client = OpenAI(**kwargs)
        providers.append({'name': cfg['name'], 'client': client, 'model': cfg['model']})
        _provider_state[cfg['name']] = {'cooldown_until': 0.0, 'calls': 0, 'errors': 0}
        logger.info(f"AI provider '{cfg['name']}' registered.")
    if not providers:
        logger.error("No AI providers configured — add at least one API key to .env.")
    return providers


_providers = _build_providers()


# ─── Provider State Helpers ───────────────────────────────────────────────────

def _is_available(name: str) -> bool:
    with _state_lock:
        return time.time() >= _provider_state[name]['cooldown_until']


def _mark_rate_limited(name: str):
    with _state_lock:
        _provider_state[name]['cooldown_until'] = time.time() + COOLDOWN_SECONDS
        _provider_state[name]['errors'] += 1
        event = {
            'provider': name,
            'timestamp': time.time(),
            'cooldown_until': _provider_state[name]['cooldown_until'],
        }
        _rate_limit_log.append(event)
        if len(_rate_limit_log) > _MAX_RATE_LIMIT_LOG:
            _rate_limit_log.pop(0)
    logger.warning(
        f"Provider '{name}' hit rate limit. Cooling down for {COOLDOWN_SECONDS}s."
    )


def _mark_success(name: str):
    with _state_lock:
        _provider_state[name]['calls'] += 1


def get_provider_status() -> list:
    """Return a snapshot of each provider's state (for the admin dashboard)."""
    now = time.time()
    result = []
    with _state_lock:
        for p in _providers:
            name = p['name']
            state = _provider_state[name]
            cooldown_remaining = max(0.0, state['cooldown_until'] - now)
            result.append({
                'name': name,
                'model': p['model'],
                'available': cooldown_remaining == 0.0,
                'cooldown_remaining_seconds': round(cooldown_remaining),
                'total_calls': state['calls'],
                'total_errors': state['errors'],
            })
    return result


def get_rate_limit_events(n: int = 10) -> list:
    """Return the last n rate-limit events as dicts with provider and timestamp."""
    import datetime
    with _state_lock:
        events = list(_rate_limit_log[-n:])
    for e in events:
        e['time_str'] = datetime.datetime.fromtimestamp(e['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        e['cooldown_until_str'] = datetime.datetime.fromtimestamp(
            e['cooldown_until']
        ).strftime('%H:%M:%S')
    return events


# ─── Core Fallback Call ───────────────────────────────────────────────────────

def _format_provider_error(name: str, error: Exception) -> str:
    """Format a user-friendly error message for a specific provider."""
    error_str = str(error)
    
    # Check for quota/rate limit errors
    if '429' in error_str or 'quota' in error_str.lower() or 'rate limit' in error_str.lower():
        if 'gemini' in name.lower():
            return f"Gemini: Rate limit exceeded (free tier quota used up)"
        elif 'openai' in name.lower():
            return f"OpenAI: Rate limit exceeded (quota used up)"
        elif 'groq' in name.lower():
            return f"Groq: Rate limit exceeded (too many requests)"
        else:
            return f"{name.title()}: Rate limit exceeded"
    
    # Check for authentication errors
    if '401' in error_str or 'unauthorized' in error_str.lower() or 'invalid' in error_str.lower():
        return f"{name.title()}: Invalid API key"
    
    # Check for network/connection errors
    if 'connection' in error_str.lower() or 'timeout' in error_str.lower():
        return f"{name.title()}: Connection failed (network issue)"
    
    # Generic error
    return f"{name.title()}: Service unavailable"


def call_ai_with_meta(
    messages: list,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    only_providers: list = None,  # restrict to these provider names; None = all
) -> tuple:
    """
    Like call_ai() but also returns which provider was used and any providers
    that were skipped due to rate limits.

    Returns: (content_str, meta_dict)
    meta_dict keys:
      provider_used   — name of the provider that succeeded
      model_used      — model name
      rate_limited    — list of provider names that were skipped (rate-limited)
      all_failed      — True if we exhausted all providers without success
    """
    last_error = None
    tried = []
    rate_limited_during = []
    provider_errors = {}  # Track errors per provider

    provider_pool = [
        p for p in _providers
        if only_providers is None or p['name'] in only_providers
    ]

    for provider in provider_pool:
        name = provider['name']

        if not _is_available(name):
            logger.info(f"Skipping provider '{name}' — in cooldown.")
            rate_limited_during.append(name)
            provider_errors[name] = "In cooldown (rate limited earlier)"
            continue

        tried.append(name)
        try:
            logger.info(f"Calling AI provider '{name}' (model={provider['model']})")
            response = provider['client'].chat.completions.create(
                model=provider['model'],
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            _mark_success(name)
            logger.info(f"Provider '{name}' responded successfully.")
            meta = {
                'provider_used': name,
                'model_used': provider['model'],
                'rate_limited': rate_limited_during,
                'all_failed': False,
            }
            return response.choices[0].message.content, meta

        except RateLimitError as e:
            _mark_rate_limited(name)
            rate_limited_during.append(name)
            provider_errors[name] = _format_provider_error(name, e)
            last_error = e

        except Exception as e:
            logger.exception(f"Provider '{name}' raised an unexpected error.")
            provider_errors[name] = _format_provider_error(name, e)
            last_error = e

    meta = {
        'provider_used': None,
        'model_used': None,
        'rate_limited': rate_limited_during,
        'all_failed': True,
    }
    
    # Build user-friendly error message
    if not tried:
        error_msg = "All AI providers are currently in cooldown. Please wait a moment and try again."
    else:
        error_lines = ["AI generation failed. Provider status:"]
        for p in _providers:
            name = p['name']
            if name in provider_errors:
                error_lines.append(f"  • {provider_errors[name]}")
            elif name not in [pr['name'] for pr in provider_pool]:
                error_lines.append(f"  • {name.title()}: Not configured")
        
        error_lines.append("\nSuggestions:")
        if any('quota' in err.lower() or 'rate limit' in err.lower() for err in provider_errors.values()):
            error_lines.append("  • Wait a few minutes for rate limits to reset")
            error_lines.append("  • Check your API quotas and billing")
        if any('invalid' in err.lower() for err in provider_errors.values()):
            error_lines.append("  • Verify your API keys in .env file")
        if any('connection' in err.lower() or 'unavailable' in err.lower() for err in provider_errors.values()):
            error_lines.append("  • Check your internet connection")
            error_lines.append("  • Try again in a few moments")
        
        error_msg = "\n".join(error_lines)
    
    raise RuntimeError(error_msg)


def call_ai(messages: list, temperature: float = 0.7, max_tokens: int = 4096,
            only_providers: list = None) -> str:
    """
    Try each active provider in priority order, skipping any that are in
    their rate-limit cooldown.  Returns the raw string content on success.
    Raises RuntimeError if every provider fails or all are in cooldown.
    """
    content, _ = call_ai_with_meta(messages, temperature, max_tokens,
                                   only_providers=only_providers)
    return content


def call_ai_provider(provider: str, fallback: str, system_prompt: str,
                     user_prompt: str, temperature: float = 0.7,
                     max_tokens: int = 4096) -> str:
    """
    Pipeline helper: call a specific provider, fall back to another, then to any.

    Used by ai_pipeline.py to assign each pipeline stage to the provider best
    suited for it (e.g. research → gemini, organize → openai, polish → groq).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    chain = []
    for name in (provider, fallback):
        if name and name not in chain:
            chain.append(name)
    last_error = None
    for name in chain:
        try:
            return call_ai(messages, temperature=temperature,
                           max_tokens=max_tokens, only_providers=[name])
        except Exception as e:
            last_error = e
            logger.warning(f"call_ai_provider: '{name}' failed ({e}); trying next.")
    # Final fallback — let any available provider try
    try:
        return call_ai(messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        raise RuntimeError(
            f"All providers failed for pipeline stage. Last error: {last_error or e}"
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_json(raw: str):
    """
    Parse JSON from raw AI output.
    Handles: bare JSON, markdown fenced blocks, and wrapper objects.
    """
    cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return json.loads(cleaned)


def _unwrap_list(data) -> list:
    """
    If the AI returned a dict wrapping a list (e.g. {"questions": [...]}),
    unwrap to the list.  If it's already a list, return as-is.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('questions', 'items', 'data', 'results', 'quiz', 'assessment'):
            if key in data and isinstance(data[key], list):
                return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
        if 'content' in data:
            return [data]
    raise ValueError(f"Cannot unwrap AI response to list. Got type: {type(data)}")


# ─── Lesson Blueprint ─────────────────────────────────────────────────────────

def generate_lesson_blueprint(
    topic: str,
    objectives: str,
    syllabus: str,
    week_number: int,
    topics_list: list = None,
    week_label: str = None,
    slide_count: int = 10,
    depth: str = 'overview',
) -> dict:
    """
    Generate blueprint data structure for teacher review.

    slide_count: target number of slides (8, 10, 12, or 14)
    depth: 'overview' (broad, concise) or 'detailed' (in-depth, more content slides)

    Returns a dict with title, objectives, week, and slides array.
    Each slide has: slide_number, layout_type, title, explanation, image_prompt, notes.
    """
    # Clamp slide_count to valid range
    slide_count = max(8, min(int(slide_count), 14))
    depth = depth.lower() if depth else 'overview'

    # 4 structural slides (title, outline, intro, objectives, conclusion) = 5 fixed
    # content_slides = total - 5
    content_slides = max(1, slide_count - 5)

    # Depth-specific instructions
    if depth == 'detailed':
        depth_label = "DETAILED"
        explanation_rule = (
            "Write 3–4 complete sentences (50–80 words) per slide explanation. "
            "Go deep: include definitions, examples, and real-world applications. "
            "Instructors should be able to speak for 2–3 minutes from each explanation."
        )
        content_instruction = (
            f"Generate exactly {content_slides} content slides (slides 5 to {slide_count - 1}). "
            "Dedicate separate slides to definitions, examples, and applications of each concept. "
            "Do NOT combine multiple concepts onto one slide."
        )
    else:
        depth_label = "OVERVIEW"
        explanation_rule = (
            "Write 2–3 complete sentences (30–50 words) per slide explanation. "
            "Stay concise: cover the core idea only, no deep dives. "
            "Instructors should be able to speak for 1 minute from each explanation."
        )
        content_instruction = (
            f"Generate exactly {content_slides} content slides (slides 5 to {slide_count - 1}). "
            "Each slide covers ONE key concept in broad strokes. "
            "Do NOT repeat similar ideas across slides — keep moving through the topic."
        )

    # Build coverage block
    if topics_list and len(topics_list) > 1:
        topics_block = "\n".join(f"  - {t}" for t in topics_list)
        coverage = (
            f"This presentation covers {len(topics_list)} topics for {week_label or f'Week {week_number}'}:\n"
            f"{topics_block}\n"
            f"Distribute the {content_slides} content slides proportionally across these topics."
        )
    else:
        coverage = f"Lesson topic: {topic}\nWeek: {week_label or week_number}"

    system_prompt = (
        f"You are an expert instructional designer creating a college-level PowerPoint presentation blueprint.\n"
        f"MODE: {depth_label} — {slide_count} slides total.\n\n"
        "REQUIRED JSON STRUCTURE — return ONLY valid JSON, no markdown, no extra text:\n"
        "{\n"
        '  "title": "Presentation title string",\n'
        '  "objectives": ["objective 1", "objective 2", ...],\n'
        '  "week": "Week X or Weeks X-Y",\n'
        '  "slides": [ <slide objects> ]\n'
        "}\n\n"
        "MANDATORY SLIDE ORDER (5 structural + content):\n"
        "  Slide 1:  layout_type: \"title_slide\"  — title slide\n"
        "  Slide 2:  layout_type: \"outline\"       — agenda of all main sections\n"
        "  Slide 3:  layout_type: \"intro\"         — Introduction / Background\n"
        "  Slide 4:  layout_type: \"objectives\"    — Learning Objectives\n"
        f"  Slides 5–{slide_count - 1}: content slides (see content rules)\n"
        f"  Slide {slide_count}: layout_type: \"conclusion\" — Summary / Key Takeaways\n\n"
        "EACH SLIDE OBJECT must have exactly these keys:\n"
        '  "slide_number": integer (1-based),\n'
        '  "layout_type": string (see layout rules),\n'
        '  "title": string — clear, concise heading for the slide,\n'
        '  "explanation": string — what this slide will say (see depth rules),\n'
        '  "image_prompt": string — detailed photo description (see image rules),\n'
        '  "notes": string — instructor speaking notes (2–3 sentences)\n\n'
        "LAYOUT RULES FOR CONTENT SLIDES:\n"
        "  Each content slide must use exactly ONE of these layout types.\n"
        "  Rotate so no two consecutive content slides share the same layout:\n"
        '    "text_left_image_right"  — paragraph left, photo right (concept explanations)\n'
        '    "image_left_text_right"  — photo left, paragraph right (real-world examples)\n'
        '    "hero_image_bottom"      — bold header, text, then full-width photo (impactful topics)\n'
        '    "text_only_centered"     — full dark background, centered text, no photo (key definitions)\n'
        "  Use a balanced mix — each layout must appear at least once.\n\n"
        f"DEPTH / EXPLANATION RULES ({depth_label}):\n"
        f"  {explanation_rule}\n"
        "  ALL slides — including structural — MUST have a non-empty explanation field.\n"
        "  Write as prose paragraphs. NO bullet points or bullet markers (•, –, *, -).\n\n"
        "IMAGE PROMPT RULES:\n"
        "  Write a detailed, scene-specific photo description for each non-text_only slide.\n"
        '  GOOD: "A university professor writing equations on a whiteboard in a bright lecture hall, students taking notes"\n'
        '  BAD:  "education" or "math" or "teacher"\n'
        '  Set image_prompt to "" for text_only_centered and structural slides (title, outline, objectives).\n\n'
        f"CONTENT SLIDE COUNT RULE: {content_instruction}\n\n"
        f"TOTAL SLIDES: Produce exactly {slide_count} slides. No more, no less."
    )

    user_prompt = (
        f"{coverage}\n\n"
        f"Learning objectives:\n{objectives}\n\n"
        f"Course syllabus excerpt:\n"
        f"{syllabus[:3000] if syllabus else 'Not provided — use standard academic content for this topic.'}\n\n"
        f"Generate the complete {slide_count}-slide {depth_label} blueprint JSON now.\n"
        "Every slide needs a non-empty explanation and a detailed image_prompt where applicable."
    )
    
    try:
        raw, ai_meta = call_ai_with_meta(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        data = _extract_json(raw)
        if "slides" not in data or "title" not in data:
            raise ValueError("Missing required keys in AI response")
        if week_label:
            data['week'] = week_label
        elif 'week' not in data:
            data['week'] = str(week_number)
        data['_ai_meta'] = ai_meta
        
        # ── Generate unique visual palette + assign icons ─────────────────
        try:
            _STYLE_SYSTEM = (
                "You are a visual presentation designer. Given a presentation topic and slide list, "
                "generate a UNIQUE color palette that perfectly fits the topic's mood and field, "
                "then assign Bootstrap Icons to slides.\n\n"
                "Every presentation must look visually distinct — no two topics should share the same palette.\n\n"
                "RETURN ONLY valid JSON — no markdown, no extra text:\n"
                "{\n"
                '  "palette": {\n'
                '    "dark": "#RRGGBB",\n'
                '    "mid": "#RRGGBB",\n'
                '    "primary": "#RRGGBB",\n'
                '    "accent": "#RRGGBB",\n'
                '    "light": "#RRGGBB",\n'
                '    "bg": "#RRGGBB",\n'
                '    "muted": "#RRGGBB",\n'
                '    "text": "#RRGGBB",\n'
                '    "text_light": "#RRGGBB",\n'
                '    "gradient_start": "#RRGGBB",\n'
                '    "gradient_end": "#RRGGBB",\n'
                '    "content_accents": ["#hex","#hex","#hex","#hex","#hex","#hex"]\n'
                '  },\n'
                '  "slides": [{"slide_number": 1, "icon": "bi-mortarboard"}, ...]\n'
                "}\n\n"
                "PALETTE RULES:\n"
                "  - dark: very dark background (#050510–#252540) for title/hero slides\n"
                "  - mid: slightly lighter than dark, for header bars\n"
                "  - primary: bold distinctive brand color matching the field\n"
                "  - accent: vibrant highlight, clearly visible on dark backgrounds\n"
                "  - light: soft pastel version of accent for card/tint areas\n"
                "  - bg: near-white with a subtle tint (#f0f0ff–#fffdf0) for content slides\n"
                "  - muted: subdued secondary text color\n"
                "  - text: very dark (#111–#333) for body text on light backgrounds\n"
                "  - text_light: near-white (#e8e8e8–#ffffff) for text on dark backgrounds\n"
                "  - gradient_start/end: create a subtle dark gradient\n"
                "  - content_accents: 6 harmonious but varied colors derived from primary/accent\n\n"
                "INSPIRATION EXAMPLES:\n"
                "  • Marine Biology → deep ocean navy, bioluminescent cyan/teal accents\n"
                "  • Organic Chemistry → forest greens, amber molecular accents\n"
                "  • Ancient History → rich imperial purples, burnished gold accents\n"
                "  • Machine Learning → dark slate, electric blue/violet accents\n"
                "  • Cardiac Surgery → deep navy, clinical crimson, medical white bg\n"
                "  • Renaissance Art → deep burgundy, warm gold, ivory background\n"
                "  • Environmental Law → deep teal-green, earthy amber accents\n\n"
                "ICON RULES — assign the most relevant Bootstrap Icon for each slide:\n"
                "  Structural: title→bi-mortarboard, outline→bi-list-check, intro→bi-info-circle,\n"
                "              objectives→bi-bullseye, conclusion→bi-trophy\n"
                "  Content: bi-cpu, bi-code-slash, bi-database, bi-cloud, bi-shield-check,\n"
                "    bi-globe, bi-diagram-3, bi-layers, bi-gear, bi-graph-up, bi-bar-chart,\n"
                "    bi-people, bi-book, bi-lightbulb, bi-stars, bi-rocket, bi-award,\n"
                "    bi-search, bi-puzzle, bi-file-text, bi-megaphone, bi-briefcase,\n"
                "    bi-heart-pulse, bi-activity, bi-flask, bi-atom, bi-dna, bi-microscope\n"
                "Assign a DIFFERENT icon to each content slide where possible."
            )

            slides_summary = json.dumps([
                {"slide_number": s.get("slide_number", i+1),
                 "layout_type":  s.get("layout_type", ""),
                 "title":        s.get("title", "")}
                for i, s in enumerate(data["slides"])
            ])

            style_raw = call_ai(
                messages=[
                    {"role": "system", "content": _STYLE_SYSTEM},
                    {"role": "user",   "content":
                     f"Topic: {data.get('title', topic)}\n"
                     f"Subject Area: {topic}\n"
                     f"Slides:\n{slides_summary}\n\n"
                     "Generate a unique color palette that visually represents this topic, "
                     "then assign icons to each slide. Return JSON only."},
                ],
                temperature=0.8,
                max_tokens=1024,
            )
            style = _extract_json(style_raw)
            if style.get('palette'):
                data['palette'] = style['palette']
            icon_map = {s['slide_number']: s.get('icon', '') for s in style.get('slides', [])}
            for i, slide in enumerate(data['slides']):
                num = slide.get('slide_number', i + 1)
                icon = icon_map.get(num, '')
                if icon:
                    slide['icon'] = icon
        except Exception as style_err:
            logger.warning(f"Palette generation failed (non-fatal): {style_err}")
            data.setdefault('palette', {})
        
        return data
    except Exception as e:
        logger.exception("Blueprint generation failed")
        raise RuntimeError(f"AI service error: {str(e)}")


# ─── Paste-and-Generate (Gamma-style) ────────────────────────────────────────

def generate_slides_from_text(
    text_content: str,
    mode: str = 'generate',
    week_number: int = 1,
    topic: str = '',
) -> dict:
    """
    Convert pasted text/notes into a structured slides array.

    mode:
      'generate'  — expand notes/bullets into full slide content
      'summarize' — condense long text into concise bullet slides
      'preserve'  — use text verbatim with minimal restructuring

    Returns dict: { title, week, slides[] }
    Each slide: { layout, title, content[], notes, icon }
    """
    mode = mode.lower() if mode else 'generate'

    if mode == 'generate':
        mode_instruction = (
            "MODE: GENERATE — Expand the notes/bullets into full, educational slide content. "
            "Add context, examples, and explanations. Each bullet point may become multiple slides."
        )
    elif mode == 'summarize':
        mode_instruction = (
            "MODE: SUMMARIZE — Condense the text into concise, punchy bullet points per slide. "
            "Extract only the key ideas. Keep each content item short (under 15 words)."
        )
    else:
        mode_instruction = (
            "MODE: PRESERVE — Use the text as-is with minimal rewording. "
            "Split into slides based on logical sections. Keep the author's exact phrasing where possible."
        )

    topic_hint = f"Presentation topic: {topic}" if topic else "Extract a suitable title from the text."

    system_prompt = (
        "You are an expert instructional designer converting raw instructor notes into a slide presentation.\n"
        f"{mode_instruction}\n\n"
        "REQUIRED JSON STRUCTURE — return ONLY valid JSON, no markdown:\n"
        "{\n"
        '  "title": "Presentation title",\n'
        '  "week": "Week N",\n'
        '  "slides": [\n'
        '    {\n'
        '      "layout": "title_slide|outline|objectives|content|section|summary",\n'
        '      "title": "Slide title",\n'
        '      "content": ["bullet 1", "bullet 2"],\n'
        '      "notes": "Speaker notes",\n'
        '      "icon": "bi-icon-name"\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "SLIDE STRUCTURE RULES:\n"
        "  - First slide: layout=title_slide, title=presentation title, content=[subtitle]\n"
        "  - Second slide: layout=outline, list all main sections as content bullets\n"
        "  - Middle slides: layout=content or section — one concept per slide\n"
        "  - Last slide: layout=summary, summarise key takeaways\n"
        "  - Aim for 6–12 slides total depending on content length\n\n"
        "ICON RULES — assign the most relevant Bootstrap Icon name (bi-xxx) for each slide:\n"
        "  title_slide→bi-mortarboard, outline→bi-list-check, objectives→bi-bullseye,\n"
        "  summary→bi-trophy, section headers→bi-bookmark\n"
        "  Content icons: bi-lightbulb, bi-graph-up, bi-people, bi-gear, bi-book,\n"
        "    bi-layers, bi-diagram-3, bi-shield-check, bi-globe, bi-rocket,\n"
        "    bi-flask, bi-atom, bi-cpu, bi-code-slash, bi-database, bi-bar-chart,\n"
        "    bi-heart-pulse, bi-activity, bi-puzzle, bi-megaphone, bi-briefcase\n"
        "  Assign a DIFFERENT icon to each slide where possible.\n\n"
        "SEPARATOR RULE: If the text contains '---' lines, treat each section as a separate slide group.\n"
        f"{topic_hint}\n"
        f"Week number: {week_number}"
    )

    user_prompt = (
        f"Convert the following content into a slide presentation:\n\n"
        f"{text_content[:6000]}\n\n"
        "Return the JSON now."
    )

    try:
        raw, _ = call_ai_with_meta(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=3000,
        )
        data = _extract_json(raw)
        if "slides" not in data:
            raise ValueError("Missing 'slides' key in AI response")
        if "title" not in data:
            data["title"] = topic or "Presentation"
        if "week" not in data:
            data["week"] = str(week_number)
        return data
    except Exception as e:
        logger.exception("generate_slides_from_text failed")
        raise RuntimeError(f"AI service error: {str(e)}")


# ─── Lesson Outline ───────────────────────────────────────────────────────────

def generate_lesson_outline(
    topic: str,
    objectives: str,
    syllabus: str,
    week_number: int,
    topics_list: list = None,
    week_label: str = None,
) -> dict:
    """
    Generate a structured PowerPoint-style lesson plan.

    When multiple weeks are combined, `topics_list` holds each individual topic
    and `week_label` is a human-readable range like "Weeks 2–4".
    Returns a dict compatible with pptx_builder.build_pptx.
    """

    # Build a clear description of what this presentation covers
    if topics_list and len(topics_list) > 1:
        topics_block = "\n".join(f"  - {t}" for t in topics_list)
        coverage = (
            f"This presentation covers {len(topics_list)} topics for {week_label or f'Week {week_number}'}:\n"
            f"{topics_block}\n"
            "Allocate 1–2 dedicated content slides per topic."
        )
    else:
        coverage = f"Lesson topic: {topic}\nWeek: {week_label or week_number}"

    system_prompt = (
        "You are an expert instructional designer creating a college-level PowerPoint presentation.\n\n"
        "REQUIRED JSON STRUCTURE — return ONLY valid JSON, no markdown, no extra text:\n"
        "{\n"
        '  "title": "Presentation title string",\n'
        '  "objectives": ["objective 1", "objective 2", ...],\n'
        '  "week": "Week X or Weeks X-Y",\n'
        '  "slides": [ <slide objects> ]\n'
        "}\n\n"
        "MANDATORY SLIDE ORDER:\n"
        "  1. layout_type: \"title_slide\"   — title slide (no content needed)\n"
        "  2. layout_type: \"outline\"        — agenda listing the main sections\n"
        "  3. layout_type: \"intro\"          — Introduction / Background paragraph\n"
        "  4. layout_type: \"objectives\"     — Learning Objectives list\n"
        "  5 to N. layout_type: one of the CONTENT layouts — ONE concept per slide\n"
        "  N+1. layout_type: \"conclusion\"  — Summary paragraph\n\n"
        "EACH SLIDE OBJECT must have exactly these keys:\n"
        '  "slide_number": integer (1-based),\n'
        '  "layout_type": string (see layout rules below),\n'
        '  "title": string,\n'
        '  "content": string or array (see content rules; omit for multi_block),\n'
        '  "blocks": array of {heading, content} objects (multi_block slides ONLY — omit for all other layouts),\n'
        '  "notes": string (full spoken explanation for the instructor),\n'
        '  "image_search_query": string (see image rules below)\n\n'
        "LAYOUT TYPE RULES:\n"
        "  Structural slides use fixed layout_type values:\n"
        '    "title_slide"  — slide 1 only\n'
        '    "outline"      — agenda slide (content = array of section names)\n'
        '    "intro"        — background/intro paragraph\n'
        '    "objectives"   — learning objectives (content = array of objectives)\n'
        '    "conclusion"   — summary paragraph\n'
        "  Content slides (slides 5 to N) must use ONE of these visual layouts,\n"
        "  rotating so NO two consecutive slides share the same layout_type:\n"
        '    "text_left_image_right" — paragraph left, photo right (best for concept explanations)\n'
        '    "image_left_text_right" — photo left, paragraph right (best for real-world examples)\n'
        '    "hero_image_bottom"     — title + paragraph on dark header, wide photo below (best for impactful topics)\n'
        '    "text_only_centered"    — dark full-slide background, centered paragraph, no photo (best for key definitions or principles)\n'
        '    "multi_block"           — slide title + 3–5 concept cards, each with a heading and 1–2 sentence explanation (best for defining multiple related terms, listing key principles, or comparing concepts side-by-side)\n'
        "  Aim for a balanced mix. For 8+ content slides, use multi_block at least once or twice.\n\n"
        "CONTENT RULES — strictly enforced:\n"
        '  • Content slides (text_left_image_right / image_left_text_right / hero_image_bottom / text_only_centered / intro / conclusion):\n'
        "    content MUST be a single STRING — a clear paragraph of exactly 2–3 sentences (40–60 words).\n"
        "    Write it as if explaining to a student for the first time. Simple, direct language.\n"
        '    CORRECT: "Web development involves creating applications that run in web browsers using HTML, CSS, and JavaScript. These technologies work together to build interactive, visually rich pages accessible on any device without installation."\n'
        '    WRONG:   ["Uses HTML/CSS", "Runs in browser", "Cross-platform"]\n'
        '  • multi_block slides: OMIT the "content" key entirely. Instead provide a "blocks" array:\n'
        '    "blocks": [{"heading": "Term or Concept Name", "content": "1–2 sentence definition or explanation."}, ...]\n'
        '    Include 3–5 blocks per slide. Each heading should be a short noun phrase. Each content should be 1–2 sentences.\n'
        '    EXAMPLE: {"layout_type": "multi_block", "title": "Core Laws", "blocks": [{"heading": "RA 10173", "content": "The Data Privacy Act protects personal data processed in the Philippines."}, ...]}\n'
        '  • outline slide: content MUST be an ARRAY of short section name strings.\n'
        '  • objectives slide: content MUST be an ARRAY of learning objective strings.\n'
        "  • Do NOT use bullet markers (•, -, *, ▸, –) anywhere in any string.\n"
        "  • Align each explanation with the provided learning objectives.\n\n"
        "IMAGE RULES:\n"
        "  • image_search_query: write a detailed, plain-English description of the ideal photo for this slide.\n"
        '    GOOD: "A software developer working on multiple monitors with code on screen in a modern office"\n'
        '    BAD:  "programming" or "code"\n'
        "  • For text_only_centered, multi_block, and structural slides (outline, objectives): set image_search_query to \"\".\n\n"
        "Total slides: 8–14."
    )

    user_prompt = (
        f"{coverage}\n\n"
        f"Learning objectives:\n{objectives}\n\n"
        f"Course syllabus excerpt:\n"
        f"{syllabus[:3000] if syllabus else 'Not provided — use standard academic content for this topic.'}\n\n"
        "Generate the complete presentation JSON now. Make sure every content bullet has a real short definition or explanation."
    )

    # ── Phase 2: Palette generation prompt ───────────────────────────────
    _STYLE_SYSTEM = (
        "You are a visual presentation designer. Given a presentation topic and slide list, "
        "generate a UNIQUE color palette that perfectly fits the topic's mood and field, "
        "then assign Bootstrap Icons to slides.\n\n"
        "Every presentation must look visually distinct — no two topics should share the same palette.\n\n"
        "RETURN ONLY valid JSON — no markdown, no extra text:\n"
        "{\n"
        '  "palette": {\n'
        '    "dark": "#RRGGBB",\n'
        '    "mid": "#RRGGBB",\n'
        '    "primary": "#RRGGBB",\n'
        '    "accent": "#RRGGBB",\n'
        '    "light": "#RRGGBB",\n'
        '    "bg": "#RRGGBB",\n'
        '    "muted": "#RRGGBB",\n'
        '    "text": "#RRGGBB",\n'
        '    "text_light": "#RRGGBB",\n'
        '    "gradient_start": "#RRGGBB",\n'
        '    "gradient_end": "#RRGGBB",\n'
        '    "content_accents": ["#hex","#hex","#hex","#hex","#hex","#hex"]\n'
        '  },\n'
        '  "slides": [{"slide_number": 1, "icon": "bi-mortarboard"}, ...]\n'
        "}\n\n"
        "PALETTE RULES:\n"
        "  - dark: very dark background (#050510–#252540) for title/hero slides\n"
        "  - mid: slightly lighter than dark, for header bars\n"
        "  - primary: bold distinctive brand color matching the field\n"
        "  - accent: vibrant highlight, clearly visible on dark backgrounds\n"
        "  - light: soft pastel version of accent for card/tint areas\n"
        "  - bg: near-white with a subtle tint (#f0f0ff–#fffdf0) for content slides\n"
        "  - muted: subdued secondary text color\n"
        "  - text: very dark (#111–#333) for body text on light backgrounds\n"
        "  - text_light: near-white (#e8e8e8–#ffffff) for text on dark backgrounds\n"
        "  - gradient_start/end: create a subtle dark gradient\n"
        "  - content_accents: 6 harmonious but varied colors derived from primary/accent\n\n"
        "INSPIRATION EXAMPLES:\n"
        "  • Marine Biology → deep ocean navy, bioluminescent cyan/teal accents\n"
        "  • Organic Chemistry → forest greens, amber molecular accents\n"
        "  • Ancient History → rich imperial purples, burnished gold accents\n"
        "  • Machine Learning → dark slate, electric blue/violet accents\n"
        "  • Cardiac Surgery → deep navy, clinical crimson, medical white bg\n"
        "  • Renaissance Art → deep burgundy, warm gold, ivory background\n"
        "  • Environmental Law → deep teal-green, earthy amber accents\n\n"
        "ICON RULES — assign the most relevant Bootstrap Icon for each slide:\n"
        "  Structural: title→bi-mortarboard, outline→bi-list-check, intro→bi-info-circle,\n"
        "              objectives→bi-bullseye, conclusion→bi-trophy\n"
        "  Content: bi-cpu, bi-code-slash, bi-database, bi-cloud, bi-shield-check,\n"
        "    bi-globe, bi-diagram-3, bi-layers, bi-gear, bi-graph-up, bi-bar-chart,\n"
        "    bi-people, bi-book, bi-lightbulb, bi-stars, bi-rocket, bi-award,\n"
        "    bi-search, bi-puzzle, bi-file-text, bi-megaphone, bi-briefcase,\n"
        "    bi-heart-pulse, bi-activity, bi-flask, bi-atom, bi-dna, bi-microscope\n"
        "Assign a DIFFERENT icon to each content slide where possible."
    )

    try:
        # ── Phase 1: Generate educational content ─────────────────────────
        raw, ai_meta = call_ai_with_meta(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
            only_providers=['openai', 'gemini'],
        )
        data = _extract_json(raw)
        if "slides" not in data or "title" not in data:
            raise ValueError("Missing required keys in AI response")
        if week_label:
            data['week'] = week_label
        elif 'week' not in data:
            data['week'] = str(week_number)
        data['_ai_meta'] = ai_meta

        # ── Phase 2: Generate unique palette + assign icons ───────────────
        try:
            slides_summary = json.dumps([
                {"slide_number": s.get("slide_number", i+1),
                 "layout_type":  s.get("layout_type", ""),
                 "title":        s.get("title", "")}
                for i, s in enumerate(data["slides"])
            ])
            style_raw = call_ai(
                messages=[
                    {"role": "system", "content": _STYLE_SYSTEM},
                    {"role": "user",   "content":
                     f"Topic: {data.get('title', topic)}\n"
                     f"Subject Area: {topic}\n"
                     f"Slides:\n{slides_summary}\n\n"
                     "Generate a unique color palette that visually represents this topic, "
                     "then assign icons to each slide. Return JSON only."},
                ],
                temperature=0.8,
                max_tokens=1024,
            )
            style = _extract_json(style_raw)
            if style.get('palette'):
                data['palette'] = style['palette']
            icon_map = {s['slide_number']: s.get('icon', '') for s in style.get('slides', [])}
            for i, slide in enumerate(data['slides']):
                num = slide.get('slide_number', i + 1)
                icon = icon_map.get(num, '')
                if icon:
                    slide['icon'] = icon
        except Exception as style_err:
            logger.warning(f"Palette generation failed (non-fatal): {style_err}")
            data.setdefault('palette', {})

        return data
    except Exception as e:
        logger.exception("Lesson generation failed")
        raise RuntimeError(f"AI service error: {str(e)}")


# ─── Table of Specifications ──────────────────────────────────────────────────

BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']


def generate_tos(topics: list, total_items: int, exam_type: str, course_title: str) -> dict:
    """
    Build a Table of Specifications following the NEMSU 7-step process:
      1. Instructor supplies topics covered on the exam.
      2. Each topic carries a teaching-hours weight.
      3. Items per topic = round(hours/total_hours * total_items), with
         largest-remainder rounding so row counts sum to total_items exactly.
      4. Each topic's items are split across Bloom levels at 60% easy
         (Remember/Understand), 30% average (Apply/Analyze), 10% difficult
         (Evaluate/Create).
      5. Each Bloom cell gets a concrete item-number placement range.

    Purely deterministic — no AI call. Returns the dict consumed by
    tos_builder.build_tos_xlsx.
    """
    if not topics:
        raise ValueError("TOS requires at least one topic")
    if total_items <= 0:
        raise ValueError("total_items must be positive")

    cleaned = []
    for t in topics:
        name = (t.get('name') or t.get('topic') or '').strip()
        hours = int(t.get('hours', 0) or 0)
        if not name:
            continue
        cleaned.append({'name': name, 'hours': max(hours, 0)})
    if not cleaned:
        raise ValueError("No valid topics provided")

    hours_list = [t['hours'] for t in cleaned]
    total_hours = sum(hours_list)
    if total_hours == 0:
        hours_list = [1] * len(cleaned)
        total_hours = len(cleaned)

    raw_items = [h / total_hours * total_items for h in hours_list]
    items_per_topic = _hamilton_round(raw_items, total_items)

    rows = []
    running = 1
    for topic, topic_hours, topic_items in zip(cleaned, hours_list, items_per_topic):
        bloom_counts = _distribute_bloom(topic_items)
        placement = {}
        for bloom in BLOOM_ORDER:
            count = bloom_counts[bloom]
            if count == 0:
                placement[bloom] = ''
            elif count == 1:
                placement[bloom] = str(running)
                running += 1
            else:
                placement[bloom] = f"{running}-{running + count - 1}"
                running += count

        pct_time = round((topic_hours / total_hours) * 100, 1) if total_hours else 0.0
        rows.append({
            'topic': topic['name'],
            'hours': topic_hours,
            'percent_time': pct_time,
            'num_items': topic_items,
            **bloom_counts,
            'total': topic_items,
            'placement': placement,
        })

    col_totals = {
        'hours': sum(hours_list),
        'percent_time': round(sum(r['percent_time'] for r in rows), 1),
        'num_items': total_items,
        'total': total_items,
    }
    for bloom in BLOOM_ORDER:
        col_totals[bloom] = sum(r[bloom] for r in rows)

    return {
        'course': course_title,
        'exam_type': exam_type,
        'total_items': total_items,
        'total_hours': total_hours,
        'bloom_distribution': {'easy_pct': 60, 'average_pct': 30, 'difficult_pct': 10},
        'rows': rows,
        'column_totals': col_totals,
    }


def _hamilton_round(raw: list, target: int) -> list:
    """Largest-remainder rounding so integer parts sum to target."""
    floors = [int(r) for r in raw]
    shortfall = target - sum(floors)
    if shortfall <= 0:
        return floors
    remainders = sorted(
        ((raw[i] - floors[i], i) for i in range(len(raw))),
        key=lambda x: (-x[0], x[1]),
    )
    for j in range(shortfall):
        floors[remainders[j % len(remainders)][1]] += 1
    return floors


def _distribute_bloom(n: int) -> dict:
    """Split n items into 60% easy / 30% average / 10% difficult, rounded to integers.
    Within each tier, the lower-order level (Remember, Apply, Evaluate) gets the
    extra item when the tier count is odd."""
    if n <= 0:
        return {k: 0 for k in BLOOM_ORDER}

    easy = round(n * 0.60)
    avg = round(n * 0.30)
    hard = n - easy - avg
    if hard < 0:
        avg = max(avg + hard, 0)
        hard = 0
        easy = n - avg

    remember = (easy + 1) // 2
    understand = easy - remember
    apply_ = (avg + 1) // 2
    analyze = avg - apply_
    evaluate = (hard + 1) // 2
    create = hard - evaluate

    return {
        'remember': remember,
        'understand': understand,
        'apply': apply_,
        'analyze': analyze,
        'evaluate': evaluate,
        'create': create,
    }


# ─── Assessment / Question Generation ────────────────────────────────────────

_QUESTION_TYPE_INSTRUCTIONS = {
    'multiple_choice': (
        "For EACH question, provide exactly 4 choices as a JSON object with keys A, B, C, D. "
        "Set answer_key to the letter of the correct answer (e.g. \"A\")."
    ),
    'true_false': (
        "For EACH question, write a statement that is either true or false. "
        "Set choices to {\"A\": \"True\", \"B\": \"False\"}. "
        "Set answer_key to \"A\" if true, or \"B\" if false."
    ),
    'identification': (
        "For EACH question, write a fill-in-the-blank or identification question. "
        "Set choices to null. "
        "Set answer_key to the correct word or short phrase. "
        "CRITICAL: Ensure grammatical agreement between the blank and the answer. "
        "If the answer is plural (e.g., 'Non-Functional Requirements'), the sentence structure must accommodate plurals (e.g., 'The ____ are...' not 'The ____ is...')."
    ),
    'essay': (
        "For EACH question, write an open-ended essay or short-answer prompt. "
        "Set choices to null. "
        "Set answer_key to a brief model answer. "
        "Include a grading rubric in the 'rubric' field. "
        "Include a full expected answer in the 'expected_answer' field."
    ),
    'oral': (
        "For EACH question, write a discussion/oral assessment question. "
        "Set choices to null. "
        "Set answer_key to key talking points. "
        "Include a grading rubric in the 'rubric' field. "
        "Include a sample ideal response in the 'expected_answer' field. "
        "Include a follow-up question in the 'follow_up' field."
    ),
}


def generate_questions(topic: str, bloom_level: str, q_type: str, count: int,
                        course_title: str, difficulty: str,
                        presentation_content: str = '',
                        assessment_type: str = 'quiz') -> list:
    """
    Generate assessment questions.
    Returns a list of dicts, each representing a question.
    """
    logger.info(
        f"Generating questions: topic='{topic}', bloom='{bloom_level}', "
        f"type='{q_type}', count={count}, difficulty='{difficulty}', "
        f"has_presentation_content={bool(presentation_content)}, "
        f"assessment_type='{assessment_type}'"
    )

    type_label = q_type.replace('_', ' ')
    type_instructions = _QUESTION_TYPE_INSTRUCTIONS.get(q_type, _QUESTION_TYPE_INSTRUCTIONS['essay'])

    reference_instruction = (
        " When presentation reference material is provided, generate questions strictly based on that content."
        if presentation_content else ""
    )

    assessment_context = ""
    if assessment_type == 'exam':
        assessment_context = "This is for a MAJOR EXAM. Make the questions highly comprehensive, integrative, and rigorous."
    else:
        assessment_context = "This is for a REGULAR QUIZ. Focus on clear, direct testing of the specific topic."

    system_prompt = (
        "You are an expert educator and assessment designer. "
        f"Generate exactly {count} {type_label} questions for the given topic. "
        f"Bloom's taxonomy level: {bloom_level}. Difficulty: {difficulty}.\n"
        f"{assessment_context}\n\n"
        "Output a JSON object with a single key \"questions\" containing an array of question objects.\n"
        "Each question object MUST have these keys:\n"
        "- content (string): the full question text\n"
        "- choices (object or null): answer choices if applicable\n"
        "- answer_key (string): the correct answer\n"
        "- explanation (string): brief explanation of the answer\n"
        "- rubric (string or \"\"): grading rubric (for essay/oral only)\n"
        "- expected_answer (string or \"\"): model answer (for essay/oral only)\n"
        "- follow_up (string or \"\"): follow-up question (for oral only)\n\n"
        f"TYPE-SPECIFIC INSTRUCTIONS:\n{type_instructions}\n\n"
        "IMPORTANT: Return valid JSON with the structure {\"questions\": [...]}. "
        f"Make questions clear, academically rigorous, and appropriate for college level.{reference_instruction}"
    )

    user_prompt = (
        f"Course: {course_title}\n"
        f"Topic: {topic}\n"
        f"Bloom's level: {bloom_level}\n"
        f"Difficulty: {difficulty}\n"
        f"Question type: {type_label}\n"
        f"Number of questions: {count}\n\n"
        f"Generate exactly {count} questions now."
    )

    if presentation_content:
        user_prompt += (
            f"\n\nREFERENCE MATERIAL (base your questions strictly on this content):\n"
            f"{presentation_content}"
        )

    try:
        raw = call_ai(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=4096,
        )
        logger.debug(f"Raw AI response (first 500 chars): {raw[:500]}")
        data = _extract_json(raw)
        questions = _unwrap_list(data)
        logger.info(f"Unwrapped {len(questions)} questions from AI response")

        validated = []
        for idx, q in enumerate(questions):
            if not isinstance(q, dict):
                logger.warning(f"Question {idx} is not a dict, skipping")
                continue
            if 'content' not in q or not q['content']:
                logger.warning(f"Question {idx} missing content, skipping")
                continue

            if q_type == 'true_false' and not q.get('choices'):
                q['choices'] = {"A": "True", "B": "False"}

            q.setdefault('choices', None)
            q.setdefault('answer_key', '')
            q.setdefault('explanation', '')
            q.setdefault('rubric', '')
            q.setdefault('expected_answer', '')
            q.setdefault('follow_up', '')

            validated.append(q)

        if not validated:
            logger.error("AI returned no valid questions after validation")
            raise ValueError("AI returned no valid questions")

        logger.info(f"Successfully generated {len(validated)} {type_label} questions")
        return validated

    except Exception as e:
        logger.exception("Question generation failed")
        err = RuntimeError(f"AI service error: {str(e)}")
        err.system_prompt = system_prompt
        err.user_prompt = user_prompt
        if 'raw' in locals():
            err.raw_ai_response = raw
        raise err from e
