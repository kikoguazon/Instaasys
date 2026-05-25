from django.db import migrations, models


def remove_duplicates_sql(apps, schema_editor):
    """Remove duplicate courses, preserving the oldest per unique group.

    Strategy:
      1. Collect (loser_id, winner_id) pairs using DISTINCT ON.
      2. Reassign enrollments from losers to winners (drop conflicts).
      3. Delete rows in every other table that FK-references accounts_course
         for the loser ids (discovered dynamically via information_schema).
      4. Delete the loser course rows.
    """
    conn = schema_editor.connection

    # ── Step 1: find duplicates ───────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ac.id AS loser_id, w.id AS winner_id
            FROM accounts_course ac
            JOIN (
                SELECT DISTINCT ON (instructor_id, code, semester, school_year)
                       id, instructor_id, code, semester, school_year
                FROM accounts_course
                WHERE code != ''
                ORDER BY instructor_id, code, semester, school_year, id ASC
            ) w ON (
                ac.instructor_id = w.instructor_id AND
                ac.code          = w.code          AND
                ac.semester      = w.semester      AND
                ac.school_year   = w.school_year   AND
                ac.id           != w.id
            )
            WHERE ac.code != ''
        """)
        pairs = cur.fetchall()

    if not pairs:
        return

    loser_ids  = [p[0] for p in pairs]
    winner_map = {p[0]: p[1] for p in pairs}
    in_clause  = ','.join(str(i) for i in loser_ids)
    val_pairs  = ','.join(f'({lo},{wi})' for lo, wi in winner_map.items())

    # ── Step 2: handle enrollments ───────────────────────────────────────────
    # Drop conflict rows first (student already enrolled in winner).
    with conn.cursor() as cur:
        cur.execute(f"""
            DELETE FROM accounts_enrollment e
            USING (VALUES {val_pairs}) AS lw(loser_id, winner_id)
            WHERE e.course_id = lw.loser_id
              AND EXISTS (
                  SELECT 1 FROM accounts_enrollment e2
                  WHERE e2.student_id = e.student_id
                    AND e2.course_id  = lw.winner_id
              )
        """)
        # Reassign remaining enrollments loser → winner.
        cur.execute(f"""
            UPDATE accounts_enrollment e
            SET course_id = lw.winner_id
            FROM (VALUES {val_pairs}) AS lw(loser_id, winner_id)
            WHERE e.course_id = lw.loser_id
        """)

    # ── Step 3: delete FK-referencing rows in all other tables ───────────────
    # Discover every FK that points at accounts_course, excluding enrollment
    # (already handled) and the course table itself.
    with conn.cursor() as cur:
        cur.execute("""
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints       tc
            JOIN information_schema.key_column_usage        kcu
                 ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema    = kcu.table_schema
            JOIN information_schema.referential_constraints rc
                 ON tc.constraint_name = rc.constraint_name
                AND tc.table_schema    = rc.constraint_schema
            JOIN information_schema.table_constraints       ccu
                 ON rc.unique_constraint_name = ccu.constraint_name
                AND rc.unique_constraint_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name     = 'accounts_course'
              AND kcu.table_name    != 'accounts_enrollment'
              AND kcu.table_name    != 'accounts_course'
        """)
        fk_tables = cur.fetchall()  # [(table_name, column_name), ...]

    with conn.cursor() as cur:
        for table_name, column_name in fk_tables:
            cur.execute(
                f"DELETE FROM {table_name} WHERE {column_name} IN ({in_clause})"
            )

    # ── Step 4: delete the loser courses ─────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM accounts_course WHERE id IN ({in_clause})")


class Migration(migrations.Migration):
    """
    Adds a partial unique constraint: (instructor, code, semester, school_year)
    where code is non-blank. First removes any existing duplicates.

    atomic = False: Django's deferred FK triggers remain queued for the entire
    transaction when atomic=True, which blocks CREATE INDEX with "pending trigger
    events". Running non-atomically lets each step auto-commit and fire triggers
    immediately, so the index creation succeeds.
    """

    atomic = False

    dependencies = [
        ('accounts', '0019_alter_enrollment_options'),
    ]

    operations = [
        migrations.RunPython(remove_duplicates_sql),
        migrations.AddConstraint(
            model_name='course',
            constraint=models.UniqueConstraint(
                fields=['instructor', 'code', 'semester', 'school_year'],
                condition=models.Q(code__gt=''),
                name='unique_course_per_instructor_semester',
            ),
        ),
    ]
