from django.db import models


class GradeRecord(models.Model):
    enrollment        = models.OneToOneField(
        'accounts.Enrollment', on_delete=models.CASCADE,
        related_name='grade_record'
    )
    # Written Work (25%) — up to 10 items
    quiz_scores            = models.JSONField(default=list, blank=True)
    quiz_column_names      = models.JSONField(default=list, blank=True)

    # Performance Tasks (45%) — up to 10 items
    performance_task_scores = models.JSONField(default=list, blank=True)
    pt_column_names         = models.JSONField(default=list, blank=True)

    # Activity Output (20%) — up to 10 items
    activity_scores    = models.JSONField(default=list, blank=True)
    activity_column_names = models.JSONField(default=list, blank=True)

    # Quarterly Assessment (30%) — single score
    requirement_score = models.FloatField(null=True, blank=True)

    # Final term — full spreadsheet data (CS 20%, PT 20%, AO 20%, Major Exam 40%)
    final_cs_scores         = models.JSONField(default=list, blank=True)
    final_cs_column_names   = models.JSONField(default=list, blank=True)
    final_pt_scores         = models.JSONField(default=list, blank=True)
    final_pt_column_names   = models.JSONField(default=list, blank=True)
    final_activity_scores   = models.JSONField(default=list, blank=True)
    final_activity_column_names = models.JSONField(default=list, blank=True)
    final_exam_score        = models.FloatField(null=True, blank=True)

    # Legacy exam fields (kept for backwards-compat)
    midterm_score     = models.FloatField(null=True, blank=True)
    final_score       = models.FloatField(null=True, blank=True)

    remarks           = models.CharField(max_length=50, blank=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['enrollment__student__last_name']

    # ── DepEd e-Class Record computed properties ──────────────────────────────

    def _scores_total(self, scores):
        if not scores:
            return None
        valid = [s for s in scores if s is not None]
        return round(sum(valid), 2) if valid else None

    def _hps_total(self, max_scores_list, num_cols):
        total = sum(
            (max_scores_list[i] if i < len(max_scores_list) and max_scores_list[i] else 10)
            for i in range(num_cols)
        )
        return total or None

    @property
    def ww_total(self):
        return self._scores_total(self.quiz_scores)

    @property
    def ww_hps_total(self):
        course = self.enrollment.course
        return self._hps_total(course.quiz_max_scores or [], len(self.quiz_scores or []))

    @property
    def ww_ps(self):
        t, h = self.ww_total, self.ww_hps_total
        if t is None or not h:
            return None
        return round(t / h * 100, 2)

    @property
    def ww_ws(self):
        ps = self.ww_ps
        return round(ps * 0.25, 2) if ps is not None else None

    @property
    def pt_total(self):
        return self._scores_total(self.performance_task_scores)

    @property
    def pt_hps_total(self):
        course = self.enrollment.course
        return self._hps_total(course.pt_max_scores or [], len(self.performance_task_scores or []))

    @property
    def pt_ps(self):
        t, h = self.pt_total, self.pt_hps_total
        if t is None or not h:
            return None
        return round(t / h * 100, 2)

    @property
    def pt_ws(self):
        ps = self.pt_ps
        return round(ps * 0.45, 2) if ps is not None else None

    @property
    def qa_ps(self):
        if self.requirement_score is None:
            return None
        course = self.enrollment.course
        hps = course.requirement_max or 10
        return round(self.requirement_score / hps * 100, 2)

    @property
    def qa_ws(self):
        ps = self.qa_ps
        return round(ps * 0.30, 2) if ps is not None else None

    @property
    def initial_grade(self):
        ww, pt, qa = self.ww_ws, self.pt_ws, self.qa_ws
        if None in (ww, pt, qa):
            return None
        return round(ww + pt + qa, 2)

    @property
    def quarterly_grade(self):
        """Transmuted quarterly grade (DepEd K-12 formula: 60 + IG*0.4)."""
        ig = self.initial_grade
        if ig is None:
            return None
        return round(60 + ig * 0.4, 2)

    @property
    def passed(self):
        ig = self.initial_grade
        return ig is not None and ig >= 75

    # ── Midterm term grade (from eclass record: CS+PT+AO+QA) ─────────────────

    @property
    def midterm_initial_grade(self):
        """Initial grade for midterm term using eclass record scores."""
        ww, pt, qa = self.ww_ws, self.pt_ws, self.qa_ws
        if None in (ww, pt, qa):
            return None
        return round(ww + pt + qa, 2)

    @property
    def midterm_term_grade(self):
        """Transmuted midterm term grade: 60 + (IG × 0.4)."""
        ig = self.midterm_initial_grade
        if ig is None:
            return None
        return round(60 + ig * 0.4, 2)

    # ── Final term grade (from final eclass record: FCS+FPT+FAO+FExam) ───────

    @property
    def fcs_total(self):
        return self._scores_total(self.final_cs_scores)

    @property
    def fcs_hps_total(self):
        course = self.enrollment.course
        return self._hps_total(course.final_cs_max_scores or [], len(self.final_cs_scores or []))

    @property
    def fcs_ps(self):
        t, h = self.fcs_total, self.fcs_hps_total
        if t is None or not h:
            return None
        return round(t / h * 100, 2)

    @property
    def fcs_ws(self):
        ps = self.fcs_ps
        course = self.enrollment.course
        w = (course.cs_weight or 20) / 100
        return round(ps * w, 2) if ps is not None else None

    @property
    def fpt_total(self):
        return self._scores_total(self.final_pt_scores)

    @property
    def fpt_hps_total(self):
        course = self.enrollment.course
        return self._hps_total(course.final_pt_max_scores or [], len(self.final_pt_scores or []))

    @property
    def fpt_ps(self):
        t, h = self.fpt_total, self.fpt_hps_total
        if t is None or not h:
            return None
        return round(t / h * 100, 2)

    @property
    def fpt_ws(self):
        ps = self.fpt_ps
        course = self.enrollment.course
        w = (course.req_weight or 20) / 100
        return round(ps * w, 2) if ps is not None else None

    @property
    def fao_total(self):
        return self._scores_total(self.final_activity_scores)

    @property
    def fao_hps_total(self):
        course = self.enrollment.course
        return self._hps_total(course.final_activity_max_scores or [], len(self.final_activity_scores or []))

    @property
    def fao_ps(self):
        t, h = self.fao_total, self.fao_hps_total
        if t is None or not h:
            return None
        return round(t / h * 100, 2)

    @property
    def fao_ws(self):
        ps = self.fao_ps
        course = self.enrollment.course
        w = (course.ao_weight or 20) / 100
        return round(ps * w, 2) if ps is not None else None

    @property
    def fexam_ps(self):
        if self.final_exam_score is None:
            return None
        course = self.enrollment.course
        hps = course.final_exam_max or 100
        return round(self.final_exam_score / hps * 100, 2)

    @property
    def fexam_ws(self):
        ps = self.fexam_ps
        course = self.enrollment.course
        w = (course.exam_weight or 40) / 100
        return round(ps * w, 2) if ps is not None else None

    @property
    def final_initial_grade(self):
        """Initial grade for final term using final eclass record scores."""
        fcs, fpt, fao, fexam = self.fcs_ws, self.fpt_ws, self.fao_ws, self.fexam_ws
        if None in (fcs, fpt, fao, fexam):
            return None
        return round(fcs + fpt + fao + fexam, 2)

    @property
    def final_term_grade(self):
        """Transmuted final term grade: 60 + (IG × 0.4)."""
        ig = self.final_initial_grade
        if ig is None:
            return None
        return round(60 + ig * 0.4, 2)

    @property
    def final_semestral_grade(self):
        """Average of midterm and final term grades."""
        mid = self.midterm_term_grade
        fin = self.final_term_grade
        if mid is None and fin is None:
            return None
        if mid is None:
            return fin
        if fin is None:
            return mid
        return round((mid + fin) / 2, 2)

    # ── Legacy computed properties (kept for student view / export) ────────────

    @property
    def class_standing(self):
        """Average of quiz scores normalized by each column's max score."""
        course = self.enrollment.course
        max_scores = course.quiz_max_scores or []
        normalized = []
        for i, s in enumerate(self.quiz_scores):
            if s is None:
                continue
            mx = max_scores[i] if i < len(max_scores) and max_scores[i] else 100
            normalized.append(s / mx * 100)
        if not normalized:
            return None
        return round(sum(normalized) / len(normalized), 2)

    @property
    def examination_average(self):
        """Average of midterm and final scores normalized by their respective maxes."""
        course = self.enrollment.course
        parts = []
        if self.midterm_score is not None:
            mx = course.midterm_max or 100
            parts.append(self.midterm_score / mx * 100)
        if self.final_score is not None:
            mx = course.final_max or 100
            parts.append(self.final_score / mx * 100)
        if not parts:
            return None
        return round(sum(parts) / len(parts), 2)

    @property
    def final_grade(self):
        """
        Final grade — uses the eclass record system (CS+PT+AO+QA) when available,
        falls back to legacy fields for backwards compatibility.
        """
        # Prefer the proper eclass record computation
        fsg = self.final_semestral_grade
        if fsg is not None:
            return fsg
        # Fall back to midterm-only if final term not yet entered
        mid = self.midterm_term_grade
        if mid is not None:
            return mid
        # Legacy fallback
        cs   = self.class_standing
        req  = self.requirement_score
        exam = self.examination_average
        if None in (cs, req, exam):
            return None
        course  = self.enrollment.course
        req_mx  = course.requirement_max or 100
        req_pct = req / req_mx * 100
        cs_w    = (course.cs_weight   or 20) / 100
        req_w   = (course.req_weight  or 40) / 100
        exam_w  = (course.exam_weight or 40) / 100
        return round((cs * cs_w) + (req_pct * req_w) + (exam * exam_w), 2)

    @property
    def equivalent_grade(self):
        """Convert numerical grade to 5-point scale (CHED standard)."""
        fg = self.final_grade
        if fg is None:
            return '—'
        if fg >= 97: return '1.00'
        if fg >= 94: return '1.25'
        if fg >= 91: return '1.50'
        if fg >= 88: return '1.75'
        if fg >= 85: return '2.00'
        if fg >= 82: return '2.25'
        if fg >= 79: return '2.50'
        if fg >= 76: return '2.75'
        if fg >= 75: return '3.00'
        return '5.00 (Failed)'

    def __str__(self):
        return f"Grades — {self.enrollment}"