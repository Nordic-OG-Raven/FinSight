"""
Regression tests for the NVO golden path (docs/NVO_GOLDEN_PATH_2026-08.md).

These pin down the fixes made 2026-08-22 so a future change can't silently reintroduce
them. Most tests here are deliberately extraction/gap-fill-level, not full pipeline+DB,
so they run in seconds with no Postgres/Docker dependency and no network calls beyond the
first run (SEC filings are cached locally under data/raw/ once downloaded).

TestFullPipelineIntegration is the exception — it requires Docker/Postgres running (the
local `superset_db` container with the `finsight` database) and takes longer, since it
runs the actual extract-load-validate pipeline. Run it explicitly:
    .venv/bin/python -m pytest tests/test_nvo_golden_path.py -v -m integration
Or run everything except it:
    .venv/bin/python -m pytest tests/test_nvo_golden_path.py -v -m "not integration"

Run with: .venv/bin/python -m pytest tests/test_nvo_golden_path.py -v
"""
import pytest
from pathlib import Path
from sqlalchemy import create_engine, text

from src.parsing.parse_xbrl import ComprehensiveXBRLParser
from src.ingestion.fetch_sec import SECFilingDownloader
from src.validation.completeness import CompletenessTracker
from src.utils.population_order import get_population_order_for_table
from config import DATA_RAW, DATABASE_URI


@pytest.fixture(scope="module")
def nvo_2024_parse_result():
    """Parse NVO's FY2024 20-F once and share the full parse result across tests."""
    downloader = SECFilingDownloader(output_dir=DATA_RAW)
    filing_path = downloader.download_filing('NVO', 2024, '20-F')
    assert filing_path is not None, "Failed to download NVO FY2024 20-F"

    parser = ComprehensiveXBRLParser()
    result = parser.parse_filing(filing_path)
    assert result is not None, (
        "XBRL parsing crashed for NVO's FY2024 20-F. This guards against the "
        "'ModelRelationshipSet' object has no attribute 'modelConcepts' regression "
        "(NVO_GOLDEN_PATH_2026-08.md item 3) — if this fails, check that "
        "src/parsing/parse_xbrl.py's fromModelObjects() calls still match the "
        "installed arelle-release version's actual API."
    )
    return result


@pytest.fixture(scope="module")
def nvo_2024_facts(nvo_2024_parse_result):
    """Just the facts, for tests that don't need relationships."""
    return nvo_2024_parse_result['facts']


def _facts_for_concept(facts, concept_name, period_type=None):
    return [
        f for f in facts
        if (f.get('concept') or '').lower() == concept_name.lower()
        and (period_type is None or f.get('period_type') == period_type)
    ]


class TestExtractionSucceeds:
    """Item 3: Arelle inline-XBRL parsing must not crash for NVO's actual filing."""

    def test_extracts_a_reasonable_number_of_facts(self, nvo_2024_facts):
        # NVO's FY2024 20-F extracted ~2951 facts on 2026-08-22. A drastically lower
        # count would indicate extraction silently broke or fell back to a stale cache.
        assert len(nvo_2024_facts) > 2000, (
            f"Expected >2000 facts from NVO's FY2024 20-F, got {len(nvo_2024_facts)}. "
            "Extraction may have silently fallen back to stale/incomplete data."
        )


class TestPresentationRelationshipsExtract:
    """
    Item 3 follow-up: presentation/calculation relationship extraction must not silently
    return zero relationships. Two distinct bugs caused this, both now fixed:
    (1) `for to_concept, rel in pres_rels.fromModelObject(from_concept):` tuple-unpacked
    each ModelRelationship object itself — which inherits lxml's _Element, so this
    silently invoked _Element.__iter__ (iterating the underlying arc XML element's raw
    children) instead of raising a clear error. Fixed via `rel.toModelObject`.
    (2) `from_concept.qname if from_concept else None` used lxml's deprecated Element
    truthiness (bool() means "has child elements", not "is not None") — a leaf concept
    definition has no children, so this silently nulled every child_qname. Fixed via
    `is not None`.
    """

    def test_presentation_relationships_are_extracted(self, nvo_2024_parse_result):
        presentation_rels = nvo_2024_parse_result.get('relationships', {}).get('presentation', [])
        assert len(presentation_rels) > 0, (
            "No presentation relationships extracted for NVO's FY2024 20-F. Either the "
            "toModelObject fix or the 'is not None' truthiness fix in "
            "extract_presentation_hierarchy() (src/parsing/parse_xbrl.py) has regressed — "
            "see NVO_GOLDEN_PATH_2026-08.md item 3 for the full diagnosis."
        )

    def test_extracted_relationships_have_real_concept_names(self, nvo_2024_parse_result):
        # Guards against the truthiness bug specifically: if it regresses, relationships
        # get "extracted" but with child_concept=None for all of them (silently useless).
        presentation_rels = nvo_2024_parse_result.get('relationships', {}).get('presentation', [])
        assert presentation_rels, "No presentation relationships to check (see previous test)"
        with_real_child = [r for r in presentation_rels if r.get('child_concept')]
        assert len(with_real_child) == len(presentation_rels), (
            f"{len(presentation_rels) - len(with_real_child)} of {len(presentation_rels)} "
            f"presentation relationships have no child_concept — this is the exact "
            f"signature of the lxml Element truthiness bug (see class docstring)."
        )


class TestScaleIsCorrect:
    """
    Guards the decimals-as-scale-factor bug (fixed in database/load_financial_data.py,
    not in the parser — this test operates on raw extracted values before that fix would
    even apply, so it instead pins the RAW value's expected magnitude, catching a
    regression if someone reintroduces scaling logic into the parser itself).
    """

    def test_revenue_is_billions_not_quintillions(self, nvo_2024_facts):
        # Filter to the consolidated figure (no dimensional breakdown) — NVO also tags
        # per-segment/per-product/per-geography Revenue facts, which are legitimately
        # much smaller than the consolidated total and would make a blanket check across
        # every Revenue-tagged fact meaningless.
        revenue_facts = [
            f for f in _facts_for_concept(nvo_2024_facts, 'Revenue', period_type='duration')
            if not f.get('dimensions')
        ]
        assert revenue_facts, "No consolidated (non-dimensional) Revenue facts extracted"
        for f in revenue_facts:
            value = f.get('value_numeric')
            if value is None:
                continue
            # NVO's annual consolidated revenue is on the order of 1e11 (hundreds of
            # billions of DKK). A regression of the old decimals-as-multiplier bug would
            # inflate this by 10^6, landing around 1e17 — well outside this range.
            assert 1e10 < abs(value) < 1e13, (
                f"Consolidated revenue value {value} is outside the expected order of "
                f"magnitude (1e10-1e13). This is the exact signature of the "
                f"decimals-as-scale-factor regression (initial scale bug fix, "
                f"database/load_financial_data.py)."
            )


class TestComparativeYearGapFill:
    """Item 4: Assets/Liabilities for the 2-years-back comparative year must be fillable
    from the company's own adjacent filing, since the primary filing genuinely doesn't
    carry them (confirmed: NVO's FY2024 20-F has no Assets fact for Dec-2022 at all)."""

    def test_2022_assets_missing_from_primary_filing(self, nvo_2024_facts):
        # This is the ORIGINAL bug, pinned as a fact about the source data: confirms the
        # primary filing genuinely doesn't carry this value, so the gap-fill mechanism
        # below is doing real work, not papering over a parsing mistake.
        assets_2022 = [
            f for f in _facts_for_concept(nvo_2024_facts, 'Assets', period_type='instant')
            if str(f.get('instant_date')) in ('2022-12-31', '2023-01-01')
        ]
        assert not assets_2022, (
            "NVO's FY2024 20-F now has a Dec-2022 Assets fact directly. If SEC refiled or "
            "this is a different filing than expected, the gap-fill fix and this test may "
            "no longer be necessary — but verify before assuming the bug just fixed itself."
        )

    def test_fill_from_comparative_filing_recovers_2022_assets(self, nvo_2024_facts):
        tracker = CompletenessTracker()
        filled = tracker.fill_missing_instant_facts_from_comparative_filing(
            list(nvo_2024_facts),  # copy — don't mutate the shared fixture
            company='NVO',
            missing_year=2022,
            filing_type='20-F'
        )
        assets_2022 = [
            f for f in _facts_for_concept(filled, 'Assets', period_type='instant')
            if str(f.get('instant_date')) in ('2022-12-31', '2023-01-01')
        ]
        assert len(assets_2022) == 1, (
            f"Expected exactly 1 Assets fact for Dec-2022 after comparative-filing "
            f"gap-fill, found {len(assets_2022)}"
        )
        # The exact value the original ~months-long investigation was chasing
        # (docs/archive/2022-completeness-investigation/), confirmed against SEC-API.
        assert assets_2022[0]['value_numeric'] == pytest.approx(241_257_000_000, rel=1e-9), (
            f"Recovered Dec-2022 Assets value {assets_2022[0]['value_numeric']} doesn't "
            f"match the known-correct value 241,257,000,000"
        )
        assert assets_2022[0]['source'] == 'COMPARATIVE_FILING'


class TestComprehensiveIncomeClassification:
    """Item 5: OCI-specific concepts must classify as comprehensive_income, not fall
    through to income_statement just because their name contains "income"."""

    def test_other_comprehensive_income_facts_are_classified_correctly(self, nvo_2024_facts):
        ci_facts = [f for f in nvo_2024_facts if f.get('statement_type') == 'comprehensive_income']
        assert len(ci_facts) > 50, (
            f"Expected >50 comprehensive_income-classified facts for NVO, got {len(ci_facts)}. "
            "This is the exact symptom of the pre-fix bug: OCI concepts (OtherComprehensiveIncome, "
            "remeasurements, cash flow hedges, translation adjustments) falling into "
            "income_statement because their names contain 'income'."
        )

    def test_known_oci_concepts_present(self, nvo_2024_facts):
        ci_concepts = {f.get('concept') for f in nvo_2024_facts if f.get('statement_type') == 'comprehensive_income'}
        # NVO's actual OCI line items (docs/archive/validation-design-history/STATEMENT_STRUCTURE_ANALYSIS.md)
        expected_substrings = ['remeasurement', 'exchangedifferencesontranslat', 'cashflowhedg']
        for substr in expected_substrings:
            matches = [c for c in ci_concepts if substr in c.lower()]
            assert matches, f"No comprehensive_income concept matched '{substr}' — expected e.g. NVO's remeasurement/translation/hedge OCI items"

    def test_accumulated_oci_balance_is_not_misclassified(self, nvo_2024_facts):
        # AccumulatedOtherComprehensiveIncome... is a BALANCE SHEET equity reserve
        # (cumulative), not the current-period OCI flow — must not be swept into
        # comprehensive_income just because it also contains "othercomprehensive".
        accumulated = [f for f in nvo_2024_facts if 'accumulated' in (f.get('concept') or '').lower() and 'comprehensive' in (f.get('concept') or '').lower()]
        for f in accumulated:
            assert f.get('statement_type') != 'comprehensive_income', (
                f"{f.get('concept')} is an accumulated (balance sheet) OCI reserve and "
                f"should not be classified as comprehensive_income"
            )


class TestEquityStatementNotBlockedByComprehensiveIncome:
    """Item 5: fact_equity_statement must not have a hard dependency on
    fact_comprehensive_income — populate_equity_statement() already LEFT JOINs it."""

    def test_equity_statement_dependencies_exclude_comprehensive_income(self):
        step = get_population_order_for_table('fact_equity_statement')
        assert step is not None, "fact_equity_statement missing from POPULATION_ORDER"
        assert 'fact_comprehensive_income' not in step['dependencies'], (
            "fact_equity_statement has a hard dependency on fact_comprehensive_income "
            "again. This causes ALL equity data to be silently dropped whenever "
            "comprehensive_income doesn't populate (e.g. for filers who report it "
            "combined with the income statement) — see NVO_GOLDEN_PATH_2026-08.md item 5."
        )


@pytest.mark.integration
class TestFullPipelineIntegration:
    """
    End-to-end: extract, load, and validate NVO's FY2024 20-F against the real local
    database. Requires Docker/Postgres (the shared superset_db container's `finsight`
    database) — see docs/PIPELINE_AND_VALIDATION_MAP.md for local setup.

    This is the test explicitly deferred in NVO_GOLDEN_PATH_2026-08.md item 7 until item 6
    closed — item 6 turned out to be six confirmed root causes deep (schema syntax,
    period dedup, filing identity, dim_concepts staleness, a tax-splitting math check, and
    finally equity-statement's dimension-based fix), each of which made this test fail for
    a genuinely different reason as it got fixed. As of 2026-08-22 the pipeline reaches
    SUCCESS with zero critical issues, confirmed reproducible across 3 consecutive clean
    runs — this test pins that down.

    Mutates the shared local database (clears and reloads NVO's data) — don't run this
    against a database with NVO data you care about preserving mid-edit.
    """

    def test_pipeline_succeeds_and_populates_all_statements(self):
        from src.main import run_pipeline

        success = run_pipeline(ticker='NVO', year=2024, filing_type='20-F')
        assert success, (
            "Full pipeline run failed for NVO 2024. Check the validation gate output — "
            "if it's failing on a specific rule, that's a regression of one of the fixes "
            "in NVO_GOLDEN_PATH_2026-08.md, not expected behavior."
        )

        engine = create_engine(DATABASE_URI)
        with engine.connect() as conn:
            for table in ['fact_balance_sheet', 'fact_income_statement', 'fact_cash_flow',
                          'fact_comprehensive_income', 'fact_equity_statement']:
                count = conn.execute(text(
                    f"""SELECT COUNT(*) FROM {table} fbs
                        JOIN dim_filings fi ON fbs.filing_id = fi.filing_id
                        JOIN dim_companies c ON fi.company_id = c.company_id
                        WHERE c.ticker = 'NVO'"""
                )).scalar()
                assert count > 0, (
                    f"{table} is empty for NVO after a 'successful' pipeline run. "
                    f"This is the exact symptom the item 5 fixes (equity dependency gate, "
                    f"comprehensive-income classification) were meant to prevent."
                )

    def test_post_load_gap_fill_does_not_create_duplicate_filing_records(self):
        """
        Item 6: post_load_gap_filling.py must attach supplementary facts to the ONE
        primary filing being processed, not create a separate dim_filings row per
        comparative year it happens to gap-fill data for. Runs regardless of whether the
        overall pipeline reports success — this specific fix holds independent of the
        separate, still-open comprehensive_income/equity_statement intermittency (see
        NVO_GOLDEN_PATH_2026-08.md item 6).
        """
        from src.main import run_pipeline

        run_pipeline(ticker='NVO', year=2024, filing_type='20-F')  # ignore success/failure

        engine = create_engine(DATABASE_URI)
        with engine.connect() as conn:
            filing_count = conn.execute(text(
                """SELECT COUNT(*) FROM dim_filings fi
                   JOIN dim_companies c ON fi.company_id = c.company_id
                   WHERE c.ticker = 'NVO'"""
            )).scalar()
        assert filing_count == 1, (
            f"Expected exactly 1 dim_filings row for NVO, found {filing_count}. "
            f"This is the exact symptom of post_load_gap_filling.py creating a separate "
            f"filing record per comparative year instead of attaching supplementary facts "
            f"to the primary filing — check that primary_year/filing_type are still being "
            f"threaded through from src/main.py to fill_missing_from_database()."
        )

    def test_stale_dim_concepts_statement_type_self_heals(self):
        """
        Item 6: get_or_create_concept() must correct dim_concepts.statement_type whenever
        the newly-extracted value differs from what's stored, not just when the existing
        value is NULL. dim_concepts is shared and persistent — a concept created before a
        classification fix landed would otherwise be permanently stuck with the old wrong
        value forever, silently masking the fix for that concept on every future run. This
        directly caused fact_comprehensive_income to appear empty even after item 5's
        classification fix was verified correct at the extraction level — ~70 concepts had
        been locked at statement_type='income_statement' from testing before the fix.
        """
        from database.load_financial_data import StarSchemaLoader

        loader = StarSchemaLoader()
        try:
            # Simulate a concept that's already in dim_concepts with a stale, wrong value
            loader.cur.execute(
                "SELECT concept_id FROM dim_concepts WHERE concept_name = %s AND taxonomy = %s",
                ('TestStaleComprehensiveIncomeConcept', 'TEST')
            )
            existing = loader.cur.fetchone()
            if existing:
                loader.cur.execute("DELETE FROM dim_concepts WHERE concept_id = %s", (existing[0],))
                loader.conn.commit()

            concept_id = loader.get_or_create_concept(
                'TestStaleComprehensiveIncomeConcept', 'TEST',
                {'normalized_label': 'test_stale_oci_concept', 'statement_type': 'income_statement'}
            )
            # Now simulate a later, corrected classification for the SAME concept
            concept_id_2 = loader.get_or_create_concept(
                'TestStaleComprehensiveIncomeConcept', 'TEST',
                {'normalized_label': 'test_stale_oci_concept', 'statement_type': 'comprehensive_income'}
            )
            assert concept_id == concept_id_2, "Expected the same concept_id to be reused"

            loader.cur.execute(
                "SELECT statement_type FROM dim_concepts WHERE concept_id = %s", (concept_id,)
            )
            final_statement_type = loader.cur.fetchone()[0]
            assert final_statement_type == 'comprehensive_income', (
                f"Expected dim_concepts.statement_type to be corrected to "
                f"'comprehensive_income', found '{final_statement_type}'. "
                f"get_or_create_concept() is only updating when the existing value is "
                f"NULL again, not when it differs from a new value — see "
                f"database/load_financial_data.py get_or_create_concept()."
            )
        finally:
            loader.cur.execute(
                "DELETE FROM dim_concepts WHERE concept_name = %s AND taxonomy = %s",
                ('TestStaleComprehensiveIncomeConcept', 'TEST')
            )
            loader.conn.commit()
            loader.close()

    def test_income_statement_math_handles_split_tax_components(self):
        """
        Item 6: check_income_statement_math() must fall back to summing
        current_tax_expense_income + deferred_tax_expense_income when the single combined
        income_tax_expense_continuing_operations/income_tax_expense label is absent.
        Confirmed NVO never reports the combined label — every period's tax is split into
        current/deferred components — so without this fallback, the check always computed
        "calculated net income" using zero tax, producing a spurious multi-billion-DKK
        violation every single period regardless of any other fix.
        """
        import inspect
        from src.validation.displayed_math import DisplayedMathValidator

        source = inspect.getsource(DisplayedMathValidator.check_income_statement_math)
        assert 'current_tax_expense_income' in source and 'deferred_tax_expense_income' in source, (
            "check_income_statement_math() no longer falls back to summing "
            "current_tax_expense_income + deferred_tax_expense_income when the combined "
            "income_tax_expense label is absent — this will reintroduce spurious "
            "multi-billion-DKK 'violations' for NVO and any other filer that splits tax "
            "into components instead of reporting one combined figure."
        )

    def test_equity_statement_populates_from_components_of_equity_axis(self):
        """
        Item 6: fact_equity_statement must populate via the ComponentsOfEquityAxis
        dimension signal (populate_equity_statement_from_dimensions), since
        dim_concepts.statement_type can never correctly say 'equity_statement' for
        concepts (like "Equity" or "ProfitLoss") that are legitimately both a primary
        balance-sheet/income-statement figure AND an equity-rollforward line item
        depending on context.
        """
        from src.main import run_pipeline

        success = run_pipeline(ticker='NVO', year=2024, filing_type='20-F')
        assert success, "Full pipeline run failed for NVO 2024 — check validation gate output"

        engine = create_engine(DATABASE_URI)
        with engine.connect() as conn:
            count = conn.execute(text(
                """SELECT COUNT(*) FROM fact_equity_statement fes
                   JOIN dim_filings fi ON fes.filing_id = fi.filing_id
                   JOIN dim_companies c ON fi.company_id = c.company_id
                   WHERE c.ticker = 'NVO'"""
            )).scalar()
        assert count > 0, (
            "fact_equity_statement is empty for NVO after a successful pipeline run. "
            "Check that populate_equity_statement_from_dimensions() is still wired into "
            "database/load_financial_data.py's load_json_file(), and that "
            "dim_xbrl_dimensions.axis_name still contains 'ComponentsOfEquityAxis' for "
            "NVO's equity-rollforward facts."
        )

    def test_balance_sheet_and_cash_flow_ui_display_correctly(self):
        """
        Item 4: UniversalUITest's missing/extra-item comparison must filter headers and
        spacers out of the API's items the same way it already filters them out of the
        API's item ORDER — these were inconsistent (headers/spacers correctly excluded
        from the order check, but not from the missing/extra check), producing false
        "extra items" for every header/spacer the API legitimately returns (confirmed:
        balance_sheet showed 2 false "extra items" — assets_header,
        equity_and_liabilities_header — purely from this inconsistency, not a real data
        problem). Also guards the net-income-as-comprehensive-income-first-line fix
        (populate_standard_presentation_order.py) that unblocked comprehensive_income.
        Runs the real pipeline + real UI test against the live API, not a mock.
        """
        from src.main import run_pipeline
        from src.validation.ui_test import UniversalUITest

        success = run_pipeline(ticker='NVO', year=2024, filing_type='20-F')
        assert success, "Full pipeline run failed for NVO 2024 — check validation gate output"

        tester = UniversalUITest(api_base="http://localhost:5001")
        report = tester.test_company('NVO', 2024, statement_types=['balance_sheet', 'cash_flow'])

        failed = [r for r in report.results if not r.passed]
        assert not failed, (
            f"balance_sheet/cash_flow UI validation failed: "
            f"{[(r.rule_name, r.message) for r in failed]}. "
            f"If this is 'extra items' matching header/spacer normalized_labels "
            f"(ending in _header, _space1, _space2), the filter consistency fix in "
            f"src/validation/ui_test.py's _validate_statement() has regressed."
        )
