from django.shortcuts import redirect
from django.contrib import messages


class RoleBasedAccessMiddleware:
    """
    Enforces role-based access control.

    Rules:
    - Superusers (Django admin) may access everything — no restrictions.
    - Instructors cannot access student-only paths.
    - Students cannot access instructor-only paths.
    - The public registration endpoint is blocked for all authenticated users;
      unauthenticated requests are allowed through so Django's login view can
      explain why the page is disabled (or redirect to login).
    """

    INSTRUCTOR_ONLY = [
        '/accounts/instructor/',
        '/accounts/courses/',
        '/accounts/students/',
        '/grading/eclass/',
        '/grading/export/',
        '/attendance/course/',
    ]

    STUDENT_ONLY = [
        '/accounts/student/',
        '/attendance/my-attendance/',
    ]

    # Portal is superuser-only — block instructors and students
    ADMIN_ONLY = ['/accounts/portal/']

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # ── Superusers bypass all role checks ───────────────────────
            if request.user.is_superuser:
                return self.get_response(request)

            path = request.path

            # ── Non-admins cannot access the admin portal ────────────────
            if not request.user.is_superuser and any(
                path.startswith(p) for p in self.ADMIN_ONLY
            ):
                messages.error(request, 'Administrator access required.')
                return redirect('accounts:dashboard')

            # ── Students cannot enter instructor-only areas ──────────────
            if request.user.is_student and any(
                path.startswith(p) for p in self.INSTRUCTOR_ONLY
            ):
                messages.warning(
                    request,
                    'Access denied — that area is for instructors only.'
                )
                return redirect('accounts:student_dashboard')

            # ── Instructors cannot enter student-only areas ──────────────
            if request.user.is_instructor and any(
                path.startswith(p) for p in self.STUDENT_ONLY
            ):
                messages.warning(
                    request,
                    'Access denied — that area is for students only.'
                )
                return redirect('accounts:instructor_dashboard')

        return self.get_response(request)
