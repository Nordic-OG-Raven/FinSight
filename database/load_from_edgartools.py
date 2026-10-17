"""
Slim loader: edgartools ExtractionResult -> FinSight star schema.

Phase 1 of the re-architecture (see docs/REARCHITECTURE.md). Deliberately tiny compared to
the retired loader: no gap-fill, no statement reconstruction, no period heuristics.
edgartools hands us clean, correctly-periodized facts, so the loader just upserts
dimensions/concepts/periods and batch-inserts the facts.

Performance: resolve ALL unique concepts and dimensions per company in BULK (a handful of
queries), not per-fact — so a 6k-dimension filer like JPM is a few round-trips, not tens of
thousands. Gentle on a local dev Postgres.

Correctness: periods are keyed by (period_type, start, end, instant) — EXACT dates — so two
companies with different fiscal calendars can never share a period_id. The cross-company
collision that plagued the old pipeline is structurally impossible here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATABASE_URL  # noqa: E402
from src.extraction.edgartools_adapter import EdgarToolsExtractor, ExtractionResult  # noqa: E402
from src.extraction.canonical_labels import canonical, canonical_label  # noqa: E402
from src.validation.quality import QualityReport, validate, write_report  # noqa: E402

try:
    from src.utils.taxonomy_mappings import get_normalized_label
except Exception:
    def get_normalized_label(_c):
        return None


def _snake(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return re.sub(r"[^a-z0-9_]+", "_", s).strip("_")


def _concept_parts(concept: str):
    return tuple(concept.split(":", 1)) if ":" in concept else ("unknown", concept)


def _norm_label(local: str) -> str:
    return get_normalized_label(local) or _snake(local)


def _dim_hash(dims: dict) -> tuple[str, str]:
    js = json.dumps(dims, sort_keys=True, default=str)
    return hashlib.sha1(js.encode()).hexdigest(), js


class StarSchemaLoader:
    def __init__(self, dsn: str):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = False
        self.cur = self.conn.cursor()
        self._concept_cache: dict[tuple, int] = {}   # (taxonomy, localname) -> id
        self._period_cache: dict[tuple, int] = {}
        self._dim_cache: dict[str, int] = {}          # hash -> id

    # ---- bulk concept resolution -------------------------------------------
    def _ensure_concepts(self, specs: dict[tuple, tuple]):
        """specs: {(tax, local): (normalized_label, preferred_label)}"""
        need = [k for k in specs if k not in self._concept_cache]
        if need:
            self.cur.execute(
                "SELECT taxonomy, concept_name, concept_id FROM dim_concepts WHERE (taxonomy, concept_name) IN %s",
                (tuple(need),),
            )
            for tax, name, cid in self.cur.fetchall():
                self._concept_cache[(tax, name)] = cid
            # Refresh normalized_label / statement_type on concepts that already exist, so a
            # reload reflects the current (e.g. canonical) labels instead of whatever an earlier
            # load wrote. Without this, dim_concepts.normalized_label drifts from the fact-level
            # labels after the canonical-label change.
            existing = [k for k in need if k in self._concept_cache]
            if existing:
                upd = [(specs[k][0], specs[k][2], self._concept_cache[k]) for k in existing]
                execute_values(
                    self.cur,
                    "UPDATE dim_concepts AS d SET normalized_label = v.nl, "
                    "statement_type = COALESCE(v.st, d.statement_type) "
                    "FROM (VALUES %s) AS v(nl, st, cid) WHERE d.concept_id = v.cid::int",
                    upd,
                )
            missing = [k for k in need if k not in self._concept_cache]
            if missing:
                rows = [(local, tax, specs[(tax, local)][0], specs[(tax, local)][1], specs[(tax, local)][2])
                        for (tax, local) in missing]
                for name, tax, cid in execute_values(
                    self.cur,
                    "INSERT INTO dim_concepts (concept_name, taxonomy, normalized_label, preferred_label, statement_type) "
                    "VALUES %s RETURNING concept_name, taxonomy, concept_id",
                    rows, fetch=True,
                ):
                    self._concept_cache[(tax, name)] = cid

    # ---- bulk dimension resolution -----------------------------------------
    def _ensure_dims(self, specs: dict[str, str]):
        """specs: {hash: json}"""
        need = [h for h in specs if h not in self._dim_cache]
        if need:
            self.cur.execute(
                "SELECT dimension_hash, dimension_id FROM dim_xbrl_dimensions WHERE dimension_hash IN %s",
                (tuple(need),),
            )
            for h, did in self.cur.fetchall():
                self._dim_cache[h] = did
            missing = [h for h in need if h not in self._dim_cache]
            if missing:
                # Also populate axis_name / member_name (human-readable, used by the data
                # viewer) from the dimension JSON: the axis keys and member values, comma-joined
                # for multi-axis dimensions.
                rows = []
                for h in missing:
                    d = json.loads(specs[h])
                    axis = ", ".join(d.keys())
                    member = ", ".join(str(v) for v in d.values())
                    rows.append((specs[h], h, axis, member))
                for h, did in execute_values(
                    self.cur,
                    "INSERT INTO dim_xbrl_dimensions (dimension_json, dimension_hash, axis_name, member_name) "
                    "VALUES %s RETURNING dimension_hash, dimension_id",
                    rows, fetch=True,
                ):
                    self._dim_cache[h] = did

    # ---- period (few per filing; exact-date keyed) -------------------------
    def _period_id(self, period_type, start, end, instant, fiscal_year):
        key = (period_type, start, end, instant)
        if key in self._period_cache:
            return self._period_cache[key]
        self.cur.execute(
            """SELECT period_id FROM dim_time_periods
               WHERE period_type=%s AND start_date IS NOT DISTINCT FROM %s
                 AND end_date IS NOT DISTINCT FROM %s AND instant_date IS NOT DISTINCT FROM %s""",
            (period_type, start, end, instant),
        )
        row = self.cur.fetchone()
        if row:
            pid = row[0]
        else:
            self.cur.execute(
                "INSERT INTO dim_time_periods (period_type, start_date, end_date, instant_date, fiscal_year) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING period_id",
                (period_type, start, end, instant, fiscal_year),
            )
            pid = self.cur.fetchone()[0]
        self._period_cache[key] = pid
        return pid

    # ---- company + filing ---------------------------------------------------
    def _company_id(self, r: ExtractionResult):
        m = r.company
        self.cur.execute("SELECT company_id FROM dim_companies WHERE ticker=%s", (m.ticker,))
        row = self.cur.fetchone()
        if row:
            self.cur.execute("UPDATE dim_companies SET company_name=%s, cik=%s WHERE company_id=%s",
                             (m.name, m.cik or None, row[0]))
            return row[0]
        self.cur.execute("INSERT INTO dim_companies (ticker, company_name, cik) VALUES (%s,%s,%s) RETURNING company_id",
                         (m.ticker, m.name, m.cik or None))
        return self.cur.fetchone()[0]

    def _filing_id(self, company_id: int, r: ExtractionResult):
        # Idempotent on the (company_id, filing_type, fiscal_year_end) unique key: reloading the
        # same filing reuses its row (and refreshes accession/date) instead of aborting the load.
        f = r.filing
        self.cur.execute(
            "SELECT filing_id FROM dim_filings WHERE company_id=%s AND filing_type=%s "
            "AND fiscal_year_end IS NOT DISTINCT FROM %s",
            (company_id, f.form, f.period_end),
        )
        row = self.cur.fetchone()
        if row:
            self.cur.execute(
                "UPDATE dim_filings SET accession_number=%s, filing_date=%s WHERE filing_id=%s",
                (f.accession or None, f.filing_date, row[0]),
            )
            return row[0]
        self.cur.execute(
            "INSERT INTO dim_filings (company_id, filing_type, fiscal_year_end, accession_number, filing_date) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING filing_id",
            (company_id, f.form, f.period_end, f.accession or None, f.filing_date),
        )
        return self.cur.fetchone()[0]

    # ---- load one result (batched, integrity-gated) ------------------------
    def load(self, r: ExtractionResult) -> tuple[int, QualityReport]:
        # Validate BEFORE persisting: the facts we're about to load ARE the load (edgartools is
        # the single source, no lossy transform between here and the DB), so validating them is
        # validating the load. Hard-gate failures short-circuit — nothing is written — which is
        # how "validation runs automatically on load and hard-fails on critical issues" (PRD
        # §2.4) stays an actual integrity gate rather than an after-the-fact report.
        report = validate(r)
        if not report.passed:
            return 0, report

        cid = self._company_id(r)
        fid = self._filing_id(cid, r)
        facts = [f for f in r.facts if f.fiscal_year is not None and f.period_type is not None]

        # Precompute parts once per fact. A fact's per-concept label is its canonical label
        # (cross-taxonomy, context-free) when it's a core line, else the snake-case fallback.
        parsed = []
        concept_specs: dict[tuple, tuple] = {}
        dim_specs: dict[str, str] = {}
        # winner of each canonical line within this filing, keyed by (canon_label, fy, pt, dim):
        # the lowest priority index present. A fact earns the canonical label only if it is that
        # winner; co-occurring synonyms (e.g. a bank's Revenues vs RevenuesNetOfInterestExpense)
        # fall back to their own label instead of colliding and being dropped.
        winner: dict[tuple, int] = {}
        for f in facts:
            tax, local = _concept_parts(f.concept)
            concept_label = canonical_label(f.concept) or _norm_label(local)
            prev = concept_specs.get((tax, local))
            prev_st = prev[2] if prev else None
            # keep the first meaningful statement_type seen for a concept
            best_st = prev_st if (prev_st and prev_st != "other") else f.statement_type
            concept_specs[(tax, local)] = (concept_label, f.label or local, best_st)
            dh = None
            if f.dimensions:
                dh, js = _dim_hash(f.dimensions)
                dim_specs[dh] = js
            pend = f.period_end or f.instant_date
            fy = pend.year if pend else f.fiscal_year
            canon = canonical(f.concept)
            if canon:
                key = (canon[0], fy, f.period_type, dh)
                if key not in winner or canon[1] < winner[key]:
                    winner[key] = canon[1]
            parsed.append((f, tax, local, dh, fy, canon))

        self._ensure_concepts(concept_specs)
        self._ensure_dims(dim_specs)

        rows, seen = [], set()
        for f, tax, local, dh, fy, canon in parsed:
            concept_id = self._concept_cache[(tax, local)]
            # Derive fiscal_year from the period's OWN end/instant date, not edgartools'
            # fiscal_year field (which tagged, e.g., Apple's FY2023 revenue as 2024). A
            # fiscal year is named for the calendar year it ends in across every calendar
            # here (Sep/Nov/Dec/Jun/Jan year-ends).
            period_id = self._period_id(f.period_type, f.period_start, f.period_end, f.instant_date, fy)
            dim_id = self._dim_cache[dh] if dh else None
            # Label resolution:
            #  - canonical winner of its line in this filing  -> the canonical label
            #  - canonical LOSER (a synonym the winner outranks) -> its own snake-cased concept
            #    name, NOT _norm_label: the legacy mapping would re-map the synonym to the same
            #    canonical label, re-colliding and letting ON CONFLICT drop the winner.
            #  - non-core concept -> legacy/snake as before
            if canon and winner.get((canon[0], fy, f.period_type, dh)) == canon[1]:
                nl = canon[0]
            elif canon:
                nl = _snake(local)
            else:
                nl = _norm_label(local)
            dedup = (concept_id, period_id, dim_id)
            if dedup in seen:
                continue
            seen.add(dedup)
            rows.append((cid, concept_id, period_id, fid, dim_id, nl, fy, f.period_type,
                         f.value_numeric, f.value_text, f.unit, (not f.is_dimensioned), "edgartools"))

        # ON CONFLICT DO NOTHING: the schema's uniqueness is on
        # (filing_id, normalized_label, fiscal_year, period_type, dimension_id), so when two
        # distinct XBRL concepts normalise to the same label for the same year/period (exactly
        # what normalisation is for), the second is skipped rather than aborting the load.
        # Precise handling of such collisions is normalization-dictionary work (roadmap), not a
        # loader concern.
        execute_values(
            self.cur,
            "INSERT INTO fact_financial_metrics "
            "(company_id, concept_id, period_id, filing_id, dimension_id, normalized_label, fiscal_year, "
            " period_type, value_numeric, value_text, unit_measure, is_primary, source) VALUES %s "
            "ON CONFLICT DO NOTHING",
            rows, page_size=1000,
        )
        self.conn.commit()
        return len(rows), report

    def close(self):
        self.cur.close()
        self.conn.close()


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL", "AVGO", "JPM", "NVO", "GOOGL", "MSFT", "AMZN", "NVDA"]
    report_dir = Path(__file__).resolve().parent.parent / "data" / "quality_reports"
    ex = EdgarToolsExtractor()
    loader = StarSchemaLoader(DATABASE_URL)
    print(f"{'TICKER':6} {'FACTS':>8} {'GATE':5} {'QUAL':>5}  DETAIL")
    failures = 0
    for tk in tickers:
        try:
            r = ex.extract(tk)
            n, rep = loader.load(r)
            write_report(rep, report_dir)
            gate = "PASS" if rep.passed else "FAIL"
            if not rep.passed:
                failures += 1
            detail = (f"({r.company.currency}, {r.filing.form}, FI={r.company.is_financial_institution})"
                      if rep.passed
                      else "NOT LOADED — " + "; ".join(w for w in rep.warnings if "HARD-GATE" in w))
            print(f"{tk:6} {n:>8} {gate:5} {rep.scores.get('overall', 0):>5.2f}  {detail}")
            for w in rep.warnings:
                if "HARD-GATE" not in w:
                    print(f"{'':6} {'':8} {'':5} {'':5}  · {w}")
        except Exception as e:
            loader.conn.rollback()  # isolate failures so one company can't poison the rest
            failures += 1
            print(f"{tk:6}    ERROR: {type(e).__name__}: {str(e)[:80]}")
    loader.close()
    print(f"\nquality reports → {report_dir}")
    sys.exit(1 if failures else 0)
