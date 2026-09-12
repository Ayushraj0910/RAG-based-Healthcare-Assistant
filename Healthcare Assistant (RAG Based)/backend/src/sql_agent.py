import re

from .access_control import (
    Role, columns_for_role, filter_columns_for_role, validate_sql,
    SQLValidationError,
)


class SQLAgent:
    """
    Patient-records agent. All SQL - whether hand-written by the fallback
    generator or produced by the LLM - is passed through `validate_sql`
    before it ever touches SQLite, and result rows are redacted to the
    columns the caller's role is permitted to see (defense in depth: even
    if a query somehow selected a disallowed column, the row-level filter
    below removes it before it reaches the LLM summarizer or the client).
    """

    def __init__(self, db, llm=None):
        self.db, self.llm = db, llm

    def _fallback_sql(self, q, role_columns):
        x = q.lower()
        filters = []
        for c in ['Cancer', 'Obesity', 'Diabetes', 'Asthma', 'Hypertension', 'Arthritis']:
            if c.lower() in x and 'medical_condition' in role_columns:
                filters.append(f"medical_condition = '{c}'")
        for m in ['Paracetamol', 'Ibuprofen', 'Aspirin', 'Penicillin', 'Lipitor']:
            if m.lower() in x and 'medication' in role_columns:
                filters.append(f"medication = '{m}'")
        for a in ['Emergency', 'Urgent', 'Elective']:
            if a.lower() in x and 'admission_type' in role_columns:
                filters.append(f"admission_type = '{a}'")
        for i in ['Blue Cross', 'Medicare', 'Aetna', 'UnitedHealthcare', 'Cigna']:
            if i.lower() in x and 'insurance_provider' in role_columns:
                filters.append(f"insurance_provider = '{i}'")
        _NAME_STOPWORDS = {
            'patients', 'patient', 'cancer', 'diabetes', 'obesity', 'asthma',
            'hypertension', 'arthritis', 'with', 'insurance', 'having',
            'diagnosed', 'admitted', 'the', 'a', 'an',
        }
        nm = re.search(r'(?:patient|for|about|of)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)', q, re.I)
        first_word_ok = nm and nm.group(1).split()[0].lower() not in _NAME_STOPWORDS
        if nm and first_word_ok and nm.group(1).lower() not in _NAME_STOPWORDS and 'name' in role_columns:
            filters.append(f"name LIKE '%{nm.group(1).strip()}%'")
        where = (' WHERE ' + ' AND '.join(filters)) if filters else ''
        select_cols = ', '.join(sorted(role_columns)) if role_columns else 'name'
        if any(k in x for k in ['how many', 'count', 'number of', 'total']) and 'medical_condition' in role_columns:
            return f'SELECT medical_condition, COUNT(*) AS patient_count FROM patients{where} GROUP BY medical_condition LIMIT 50'
        if any(k in x for k in ['how many', 'count', 'number of', 'total']):
            return f'SELECT COUNT(*) AS patient_count FROM patients{where} LIMIT 50'
        return f'SELECT {select_cols} FROM patients{where} LIMIT 50'

    def run(self, q, role: str = Role.DEFAULT):
        """
        Returns dict with keys: sql, rows, warnings, error, validation_error.
        `role` scopes both the columns the LLM is told it may select and the
        row-level redaction applied to whatever comes back.
        """
        role_columns = columns_for_role(role)
        sql = None
        warnings = []
        validation_error = None

        if self.llm and self.llm.available:
            allowed_cols_str = ', '.join(sorted(role_columns))
            p = (
                f"Translate the question into safe SQLite. Table patients has columns "
                f"{allowed_cols_str}. You may ONLY reference these exact columns - the "
                f"table has other columns but the current user's role is not permitted to "
                f"see them, so never select or filter on any column outside this list. "
                f"SELECT only, LIKE for text, LIMIT 50. Return only SQL. Question: {q}"
            )
            raw = self.llm.chat([{'role': 'system', 'content': p}], 0, 500)
            if raw:
                sql = raw.replace('```sql', '').replace('```', '').strip().rstrip(';')

        if not sql:
            sql = self._fallback_sql(q, role_columns)

        try:
            result = validate_sql(sql, allowed_columns=role_columns)
            warnings.extend(result.warnings)
            rows = self.db.execute(result.sql)
            final_sql = result.sql
        except SQLValidationError as e:
            # LLM-generated SQL failed validation (out-of-scope column,
            # injection pattern, non-SELECT, etc). Never execute it - fall
            # back to the safe, template-generated query instead.
            validation_error = str(e)
            sql = self._fallback_sql(q, role_columns)
            try:
                result = validate_sql(sql, allowed_columns=role_columns)
                rows = self.db.execute(result.sql)
                final_sql = result.sql
            except Exception:
                rows, final_sql = [], sql
        except Exception as e:
            validation_error = f"Execution error: {e}"
            sql = self._fallback_sql(q, role_columns)
            try:
                result = validate_sql(sql, allowed_columns=role_columns)
                rows = self.db.execute(result.sql)
                final_sql = result.sql
            except Exception:
                rows, final_sql = [], sql

        rows = filter_columns_for_role(rows, role)
        return {
            'sql': final_sql,
            'rows': rows,
            'warnings': warnings,
            'validation_error': validation_error,
            'role': role,
        }

    def summarize(self, q, rows):
        if not rows:
            return 'No matching patient records were found.'
        if not self.llm or not self.llm.available:
            return f'Found {len(rows)} matching record(s).'
        p = (
            f'Summarize these synthetic hospital database results for staff. Do not '
            f'invent facts, do not mention columns not present in the data, and do not '
            f'expose internal IDs. Question: {q}\nResults: {rows[:20]}'
        )
        return self.llm.chat([{'role': 'system', 'content': p}], .1, 700) or f'Found {len(rows)} matching record(s).'
