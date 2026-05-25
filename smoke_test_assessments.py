"""One-shot smoke test for the new assessment endpoints. Run via:
    python manage.py shell < smoke_test_assessments.py
or directly:
    python smoke_test_assessments.py
Then delete this file.
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'instaasys.settings')
django.setup()

from django.conf import settings
if 'testserver' not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import Course, User
from assessments.models import QuestionSet, Question
from django.test import Client

# accounts.User uses .role, not is_instructor field
inst = User.objects.filter(role='instructor').first()
print(f"Instructor: {inst}  is_instructor={getattr(inst, 'is_instructor', None)}")

if not inst:
    print("No instructor user in DB — cannot smoke-test endpoints.")
    sys.exit(0)

course = Course.objects.filter(instructor=inst).first()
print(f"Course: {course}")
if not course:
    print("No course owned by this instructor — skipping endpoint tests.")
    sys.exit(0)

q = Question.objects.filter(course=course).first()
if not q or not q.question_set:
    print("No questions in any QuestionSet — skipping endpoint tests.")
    sys.exit(0)

print(f"Sample question pk={q.pk} type={q.question_type}")
print(f"  content[:50]={q.content[:50]!r}")
qs = q.question_set
print(f"  in QuestionSet pk={qs.pk}: {qs}")

c = Client()
c.force_login(inst)

print("\n---Preview routes (mode/theme variants) ---")
for url in [
    f"/assessments/course/{course.pk}/assessments/{qs.pk}/preview/",
    f"/assessments/course/{course.pk}/assessments/{qs.pk}/preview/?mode=minimalist",
    f"/assessments/course/{course.pk}/assessments/{qs.pk}/preview/?mode=minimalist&theme=dark",
    f"/assessments/course/{course.pk}/assessments/{qs.pk}/preview/?header=false&instructions=false",
]:
    r = c.get(url)
    has_toggle = b'editModeToggle' in r.content
    has_tools  = b'q-tools' in r.content
    has_minimalist = b'mode-minimalist' in r.content
    has_dark = b'theme-dark' in r.content
    print(f"  {r.status_code}  {url}")
    print(f"        editModeToggle={has_toggle}  q-tools={has_tools}  "
          f"mode-minimalist={has_minimalist}  theme-dark={has_dark}")

print("\n---Markdown export ---")
r = c.get(f"/assessments/course/{course.pk}/assessments/{qs.pk}/export-md/")
print(f"  Status: {r.status_code}, len={len(r.content)}, type={r.get('Content-Type')}")
print("  ──---first 500 chars ---──")
print(r.content[:500].decode('utf-8', errors='replace'))
print("  ---──")

print("\n---Inline update: content (whitelisted) ---")
original = q.content
r = c.post(
    f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
    {'field': 'content', 'value': original + ' [TEST]'},
)
print(f"  Status: {r.status_code}, body: {r.json()}")
q.refresh_from_db()
print(f"  DB content tail: ...{q.content[-15:]!r}")

print("\n---Inline update: rubric (must reject) ---")
r = c.post(
    f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
    {'field': 'rubric', 'value': 'sneaky'},
)
print(f"  Status: {r.status_code}, body: {r.json()}")

print("\n---Inline update: choices (must reject) ---")
r = c.post(
    f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
    {'field': 'choices', 'value': '{}'},
)
print(f"  Status: {r.status_code}, body: {r.json()}")

print("\n---Inline update: answer_key (whitelisted) ---")
original_ak = q.answer_key
r = c.post(
    f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
    {'field': 'answer_key', 'value': 'B'},
)
print(f"  Status: {r.status_code}, body: {r.json()}")

# Reset
c.post(f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
       {'field': 'content', 'value': original})
c.post(f"/assessments/course/{course.pk}/questions/{q.pk}/inline-update/",
       {'field': 'answer_key', 'value': original_ak})
print("\n---Reset to originals: done ---")
