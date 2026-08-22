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
def nvo_2024_facts():
    """Parse NVO's FY2024 20-F once and share across tests in this module."""
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
    return result['facts']


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
    (schema drift + the period-deduplication bug it surfaced) closed — it would have been
    permanently red before that. Now that the pipeline reaches SUCCESS with zero critical
    validation issues, this pins that down.

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
