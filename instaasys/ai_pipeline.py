"""
instaasys/ai_pipeline.py

Multi-AI Presentation Pipeline (3 stages, one provider per strength):

  STAGE 1 — RESEARCH     (Gemini → OpenAI)   factual depth, concrete examples
  STAGE 2 — ORGANIZE     (OpenAI → Gemini)   structure, slide layout, bullets
  STAGE 3 — POLISH       (Groq   → Sambanova) fast text refinement

  IMAGES — Pexels → Unsplash (reuses fetch_image_url_for_web from pptx_builder)

Output is the same slide JSON shape used by build_pptx() and the web slideshow,
so the existing renderers keep working without modification.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


PIPELINE_CONFIG = {
    'research': {'primary': 'gemini',     'fallback': 'openai'},
    'organize': {'primary': 'openai',     'fallback': 'gemini'},
    'polish':   {'primary': 'groq',       'fallback': 'sambanova'},
}


# ─── Prompts ──────────────────────────────────────────────────────────────────

RESEARCH_PROMPT = """You are an expert academic researcher preparing lecture content for a college course.

COURSE: {course_title}
WEEK: {week_number}
TOPIC: {topic}
LEARNING OUTCOMES (CILOs):
{cilos}

CONTENT DEPTH: {content_depth}

Research this topic thoroughly and produce DETAILED educational content. For each subtopic, provide:
- Clear definitions with proper terminology
- Specific examples (real companies, tools, frameworks — name them)
- Key facts, statistics, or comparisons where relevant
- Practical applications students should know

IMPORTANT RULES:
- Write for college-level students
- Be SPECIFIC — don't say "various platforms", name them (Android, iOS, Windows, Web, etc.)
- Include concrete comparisons when useful
- Each subtopic should have 3–5 substantive points
- Do NOT write paragraphs — use structured points

DEPTH REQUIREMENT:
- For each key point, include: a definition, a real-world example (name the company/law/event), and why it matters
- Include specific statistics or figures where available
- Name actual legislation, organizations, frameworks (ACM, IEEE, GDPR, etc.)
- Do NOT write vague points — every point should be specific enough that a student could cite it in a report

KEY_POINTS FORMAT (CRITICAL):
Each key_points entry must be a SHORT PHRASE of max 25 words that begins with a
TERM or CONCEPT name followed by " — " and then a brief explanation. This format
feeds directly into presentation bullets.

Example:
  ✗ "The sensors in IoT devices are used to collect data from the environment"
  ✓ "Sensors — collect environmental data (temperature, motion, light) and
     transmit it to connected systems for processing"

Respond ONLY in this JSON format:
{{
  "main_topic": "The main topic title",
  "subtopics": [
    {{
      "title": "Subtopic title",
      "key_points": ["Point 1 with specifics", "Point 2 with examples", "Point 3 with facts"],
      "definitions": ["Term: Definition"],
      "examples": ["Real-world example"],
      "image_keywords": ["keyword1 keyword2 for image search"]
    }}
  ],
  "learning_summary": ["Key takeaway 1", "Key takeaway 2", "Key takeaway 3"]
}}
"""


ORGANIZE_PROMPT = """═══════════ ABSOLUTE FORMAT RULES — VIOLATIONS BREAK THE SYSTEM ═══════════

RULE 1 — content IS ALWAYS AN ARRAY OF STRINGS. Never a single long string.
  ✗ WRONG: "content": ["The IoT refers to physical devices that are embedded..."]
  ✓ RIGHT:  "content": ["IoT Definition — network of physical devices embedded
             with sensors allowing them to collect and exchange data",
             "Scale — over 15 billion connected devices worldwide by 2023",
             "Applications — smart homes, industrial automation, healthcare monitoring"]

RULE 2 — EACH STRING IN content IS ONE BULLET. Max 25 words per bullet.
  ✗ WRONG: "The IoT has sensors, actuators, connectivity technologies such as
            Wi-Fi, Bluetooth, and cellular networks and has numerous applications
            including industrial automation and transportation systems."
  ✓ RIGHT: "Sensors & Actuators — physical hardware that detects and responds
            to real-world conditions like temperature, motion, light"

RULE 3 — content arrays must have 3–6 items for "bullets" layout.
  Never 1 item. Never more than 6. If you have more than 6 points, create
  a second slide for the same topic.

RULE 4 — "objectives" layout: content must have one string PER objective.
  Never combine multiple objectives into one string.
  ✗ WRONG: "content": ["Understand mission, vision, identify IoT components,
             apply course policies and institutional outcomes"]
  ✓ RIGHT: "content": [
              "Recite the Mission, Vision, and Core Values of NEMSU",
              "Explain the significance of the School Quality Policy",
              "Define the Internet of Things and its key components",
              "Identify real-world IoT applications and emerging trends"
            ]

RULE 5 — "summary" layout: content must have 4–6 SHORT takeaway strings.
  Each one is a complete thought in under 20 words. No "In conclusion..." filler.

RULE 6 — "cards" layout: content is an array of objects:
  [{{"heading": "Card Title", "body": "2–3 sentence explanation with specifics"}}]

══════════════════════════════════════════════════════════════════════════

You are an expert academic presentation designer for a college-level IT course.

COURSE: {course_title} (Code: {course_code})
WEEK: {week_number}
SLIDE COUNT TARGET: {slide_count}
CONTENT DEPTH: {content_depth}

RESEARCHED CONTENT:
{research_json}

═══════════════════════════════════════════════════
AVAILABLE SLIDE LAYOUTS — choose the best fit:
═══════════════════════════════════════════════════

1. "title" — Course title slide. Use ONLY for slide index 0.

2. "objectives" — Learning objectives. Use ONLY for slide index 1.
   content = list of objectives (each is a separate string, 1 per CILO)

3. "bullets" — Standard topic slide with bullet points.
   Use when listing 3-6 related points about one topic.
   Each bullet must be 1-2 sentences. Include real names, examples, numbers.
   content = list of bullet strings (NOT paragraphs)

4. "cards" — 2x2 or 2x3 card grid. Best for comparing 4-6 distinct concepts.
   Use when the topic has clearly named subtopics that benefit from visual separation.
   Each card has a title and a short body (2-3 sentences).
   content = list of card objects: [{{"heading": "Card Title", "body": "2-3 sentence explanation"}}]
   Example: Comparing platforms, listing types of cybercrime, ethical frameworks

5. "stats" — Large statistics or key numbers. Use when topic has 3-4 significant figures.
   content = list of stat objects: [{{"number": "85M", "label": "Jobs Displaced", "source": "WEF 2020"}}]
   Max 4 stats per slide. Use for impact data, market share, scale figures.

6. "section" — Dark divider between major topic groups. Title + optional 1-line subtitle only.
   content = [] (empty — no body text)

7. "quote" — Single prominent quote or principle. Use for ethical principles, laws, or key definitions.
   content = [{{"text": "The quote or principle text", "attribution": "Source or author"}}]

8. "comparison" — Side-by-side comparison of exactly 2 things.
   content = [{{"left_title": "Option A", "left_points": ["point1","point2"], "right_title": "Option B", "right_points": ["point1","point2"]}}]

9. "summary" — Key takeaways. Last slide only.
   content = list of takeaway strings (4-6 items)

═══════════════════════════════════════════════════
CRITICAL CONTENT RULES:
═══════════════════════════════════════════════════

1. BE SPECIFIC — name real things:
   - Real company names: Amazon, Google, Meta, Microsoft — not "a tech company"
   - Real laws: GDPR, CCPA, HIPAA, ACM Code of Ethics — not "regulations"
   - Real events: Cambridge Analytica, Amazon AI hiring scandal — not "an incident"
   - Real numbers: "$40,000–$150,000 development cost", "85M jobs displaced" — not "significant cost"

2. DEPTH — each point must actually explain, not just name:
   - BAD: "Privacy: freedom from unwanted attention"
   - GOOD: "Privacy by Design — embed data minimization into the architecture from day one, not as an afterthought. Example: collect only what the app needs, store it encrypted, delete it on request."

3. BULLETS are NOT one-liners:
   - Each bullet = 1-2 complete sentences with real substance
   - Maximum 6 bullets per slide — if you have more, create another slide

4. CARDS body text = 2-3 sentences minimum:
   - Must explain the concept, give an example, and state its significance
   - Never use a card body that is just a definition

5. NO FILLER PHRASES: Remove "It is important to note", "In conclusion", "As we can see"

6. IMAGES: Set image_query to null for ALL slides. This topic does not need images.
   Let the layout and content carry the slide, not stock photos.

7. SLIDE VARIETY: In a 10-slide deck, use at least 3 different layout types.
   Never use "bullets" for every content slide. If 4+ related subtopics exist, use "cards".

═══════════════════════════════════════════════════
SPEAKER NOTES — required for every non-section slide:
═══════════════════════════════════════════════════
- Write 2-4 sentences the instructor would actually say
- Expand on the slide content — don't repeat it
- Include additional context, examples, or questions to ask students
- Style: conversational, like talking to students

Respond ONLY in this JSON format:
{{
  "title": "Presentation title",
  "slides": [
    {{
      "title": "Slide title",
      "layout": "title|objectives|bullets|cards|stats|section|quote|comparison|summary",
      "content": [...],
      "notes": "Speaker notes",
      "image_query": null
    }}
  ]
}}
"""


POLISH_PROMPT = """You are an academic writing editor. Polish the following slide deck for a college presentation.

SLIDES JSON:
{slides_json}

RULES:
1. Fix grammar / spelling errors
2. Trim filler words from bullets
3. Consistent capitalisation and punctuation across bullets
4. No bullet over 25 words — split or shorten if needed
5. Make speaker notes natural and conversational
6. Objectives slide: each CILO stays a SEPARATE bullet
7. Summary slide: actually summarises the key points covered
8. Do NOT change slide structure, layout types, or count
9. Do NOT remove image_query fields

Return the corrected slides in the same JSON shape. JSON only — no other text.
"""


# ─── JSON helpers ─────────────────────────────────────────────────────────────

def _extract_json(raw: str):
    """Strip code fences, parse JSON robustly."""
    cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return json.loads(cleaned)


# ─── Image sourcing — reuse the existing utility ──────────────────────────────

def fetch_slide_images(slides: list) -> list:
    """Attach image_url to each content slide (Pexels → Unsplash via existing util)."""
    try:
        from presentations.pptx_builder import fetch_image_url_for_web
    except Exception:
        fetch_image_url_for_web = lambda q: None  # noqa: E731

    for slide in slides:
        layout = slide.get('layout', '')
        query  = slide.get('image_query') or slide.get('image_search_query') or ''
        if not query or layout in ('title', 'section', 'summary', 'objectives'):
            slide['image_url'] = None
            continue
        try:
            slide['image_url'] = fetch_image_url_for_web(query)
        except Exception as exc:
            logger.warning(f"Image fetch failed for '{query}': {exc}")
            slide['image_url'] = None
    return slides


# ─── Main pipeline ────────────────────────────────────────────────────────────

def generate_presentation(course, week_data: dict, slide_count: int = 10,
                          content_depth: str = 'overview') -> dict:
    """
    Run the full 3-stage AI pipeline.

    Args:
        course:        Course model instance (uses .title, .code).
        week_data:     dict with keys: week, topics (list), cilos (list).
        slide_count:   target number of slides (8/10/12/14).
        content_depth: 'overview' or 'detailed'.

    Returns:
        dict { title, slides[], objectives[], _pipeline_meta }.
        Each content slide includes image_url when an image was found.
    """
    from .ai_service import call_ai_provider

    topic = '; '.join(week_data.get('topics', [])) or 'Course topic'
    cilos = '\n'.join(f"- {c}" for c in week_data.get('cilos', [])) or '(none provided)'
    week_num = week_data.get('week', '')

    # ── STAGE 1: RESEARCH ─────────────────────────────────────────────────
    cfg = PIPELINE_CONFIG['research']
    logger.info(f"[Pipeline] Stage 1 (research) → {cfg['primary']}")
    research_raw = call_ai_provider(
        provider=cfg['primary'],
        fallback=cfg['fallback'],
        system_prompt="You are an expert academic researcher. Respond only in valid JSON.",
        user_prompt=RESEARCH_PROMPT.format(
            course_title=getattr(course, 'title', 'Course'),
            week_number=week_num,
            topic=topic,
            cilos=cilos,
            content_depth=content_depth,
        ),
        temperature=0.6,
    )
    # Validate the research stage parsed (we don't use the parsed value, but it
    # surfaces malformed JSON early instead of leaking into the next stage).
    _extract_json(research_raw)

    # ── STAGE 2: ORGANIZE ─────────────────────────────────────────────────
    cfg = PIPELINE_CONFIG['organize']
    logger.info(f"[Pipeline] Stage 2 (organize) → {cfg['primary']}")
    organized_raw = call_ai_provider(
        provider=cfg['primary'],
        fallback=cfg['fallback'],
        system_prompt="You are a presentation designer. Respond only in valid JSON.",
        user_prompt=ORGANIZE_PROMPT.format(
            course_title=getattr(course, 'title', 'Course'),
            course_code=getattr(course, 'code', ''),
            week_number=week_num,
            slide_count=slide_count,
            content_depth=content_depth,
            research_json=research_raw,
        ),
        temperature=0.5,
    )
    organized = _extract_json(organized_raw)

    # ── STAGE 3: POLISH ───────────────────────────────────────────────────
    cfg = PIPELINE_CONFIG['polish']
    logger.info(f"[Pipeline] Stage 3 (polish) → {cfg['primary']}")
    try:
        polished_raw = call_ai_provider(
            provider=cfg['primary'],
            fallback=cfg['fallback'],
            system_prompt="You are an academic writing editor. Respond only in valid JSON.",
            user_prompt=POLISH_PROMPT.format(slides_json=organized_raw),
            temperature=0.3,
        )
        result = _extract_json(polished_raw)
    except Exception as exc:
        # Polish is optional — fall back to the organized output if it fails
        logger.warning(f"[Pipeline] Polish stage failed ({exc}); using organized output.")
        result = organized

    # ── Image sourcing ────────────────────────────────────────────────────
    logger.info("[Pipeline] Fetching slide images")
    result['slides'] = fetch_slide_images(result.get('slides', []))

    # ── Extract objectives from the objectives slide for convenience ──────
    if 'objectives' not in result:
        for slide in result.get('slides', []):
            if slide.get('layout') == 'objectives':
                result['objectives'] = slide.get('content', [])
                break
        result.setdefault('objectives', [])

    result['week'] = week_num
    result['_pipeline_meta'] = {
        'pipeline_version': '1.0',
        'stages': {
            'research': PIPELINE_CONFIG['research']['primary'],
            'organize': PIPELINE_CONFIG['organize']['primary'],
            'polish':   PIPELINE_CONFIG['polish']['primary'],
        },
        'slide_count': slide_count,
        'content_depth': content_depth,
    }
    return result
