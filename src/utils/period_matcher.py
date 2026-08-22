#!/usr/bin/env python3
"""
Period Matching Utility

Single source of truth for matching periods across different statement types.
Replaces complex, competing strategies scattered throughout SQL queries.

Strategies:
- 'exact': Exact date match
- 'fiscal_year_end': Match fiscal year end date
- 'calendar_year_end': Match December 31
- 'previous_year': Match previous fiscal year
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from config import DATABASE_URI


@dataclass
class PeriodInfo:
    """Information about a time period"""
    period_id: int
    fiscal_year: int
    fiscal_quarter: Optional[int]
    period_type: str  # 'instant' or 'duration'
    instant_date: Optional[date]
    start_date: Optional[date]
    end_date: Optional[date]
    fiscal_year_end: Optional[date]


class PeriodMatcher:
    """
    Single source of truth for period matching.
    
    Replaces complex, competing strategies scattered throughout SQL queries
    with a single, testable, reusable utility.
    """
    
    def __init__(self, engine=None):
        """Initialize with database connection"""
        if engine is None:
            self.engine = create_engine(DATABASE_URI)
        else:
            self.engine = engine
    
    def match_period(
        self,
        target_period_id: int,
        source_periods: List[PeriodInfo],
        strategy: str = 'fiscal_year_end',
        filing_id: Optional[int] = None
    ) -> Optional[PeriodInfo]:
        """
        Match target period to best source period.
        
        Args:
            target_period_id: Period ID to match
            source_periods: List of candidate source periods
            strategy: Matching strategy ('exact', 'fiscal_year_end', 'calendar_year_end', 'previous_year')
            filing_id: Optional filing ID for context (used for previous_year strategy)
        
        Returns:
            Best matching PeriodInfo or None if no match
        """
        if not source_periods:
            return None
        
        # Get target period info
        target = self._get_period_info(target_period_id)
        if not target:
            return None
        
        if strategy == 'exact':
            return self._match_exact(target, source_periods)
        elif strategy == 'fiscal_year_end':
            return self._match_fiscal_year_end(target, source_periods, filing_id)
        elif strategy == 'calendar_year_end':
            return self._match_calendar_year_end(target, source_periods)
        elif strategy == 'previous_year':
            return self._match_previous_year(target, source_periods, filing_id)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _get_period_info(self, period_id: int) -> Optional[PeriodInfo]:
        """Get period information from database"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    period_id,
                    fiscal_year,
                    fiscal_quarter,
                    period_type,
                    instant_date,
                    start_date,
                    end_date
                FROM dim_time_periods
                WHERE period_id = :period_id
            """), {'period_id': period_id})
            
            row = result.fetchone()
            if not row:
                return None
            
            # Get fiscal_year_end from filing if available
            fiscal_year_end = None
            if row[1]:  # fiscal_year exists
                # Try to get fiscal_year_end from most recent filing for this period
                filing_result = conn.execute(text("""
                    SELECT f.fiscal_year_end
                    FROM dim_filings f
                    JOIN dim_time_periods tp ON 
                        EXTRACT(YEAR FROM f.fiscal_year_end) = tp.fiscal_year
                    WHERE tp.period_id = :period_id
                    ORDER BY f.fiscal_year_end DESC
                    LIMIT 1
                """), {'period_id': period_id})
                filing_row = filing_result.fetchone()
                if filing_row:
                    fiscal_year_end = filing_row[0]
            
            return PeriodInfo(
                period_id=row[0],
                fiscal_year=row[1],
                fiscal_quarter=row[2],
                period_type=row[3],
                instant_date=row[4],
                start_date=row[5],
                end_date=row[6],
                fiscal_year_end=fiscal_year_end
            )
    
    def _match_exact(self, target: PeriodInfo, sources: List[PeriodInfo]) -> Optional[PeriodInfo]:
        """Match by exact date"""
        if target.period_type == 'instant' and target.instant_date:
            # For instant periods, match exact date
            for source in sources:
                if source.instant_date == target.instant_date:
                    return source
        elif target.period_type == 'duration':
            # For duration periods, match start and end dates
            for source in sources:
                if (source.start_date == target.start_date and 
                    source.end_date == target.end_date):
                    return source
        
        return None
    
    def _match_fiscal_year_end(
        self, 
        target: PeriodInfo, 
        sources: List[PeriodInfo],
        filing_id: Optional[int] = None
    ) -> Optional[PeriodInfo]:
        """
        Match by fiscal year end date.
        
        Strategy:
        1. Prefer exact match with target's start_date (for beginning balance)
        2. Prefer dates that match fiscal_year_end of target's fiscal year
        3. Prefer December 31 or January 1
        4. Prefer most recent date
        """
        if not sources:
            return None
        
        # Get fiscal_year_end if available
        fiscal_year_end = target.fiscal_year_end
        if filing_id and not fiscal_year_end:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT fiscal_year_end
                    FROM dim_filings
                    WHERE filing_id = :filing_id
                """), {'filing_id': filing_id})
                row = result.fetchone()
                if row:
                    fiscal_year_end = row[0]
        
        # Score each source period
        scored = []
        for source in sources:
            if source.period_type != 'instant' or not source.instant_date:
                continue
            
            score = 0
            
            # Prefer exact match with target's start_date (for beginning balance)
            if target.start_date and source.instant_date == target.start_date:
                score += 1000
            
            # CRITICAL: For end balance, prefer target's end_date (typically Jan 1 of next year)
            # This is when component breakdown data typically exists
            if target.end_date and source.instant_date == target.end_date:
                score += 1200  # Higher priority than fiscal_year_end match
            
            # Prefer dates that match fiscal_year_end
            if fiscal_year_end:
                if source.instant_date == fiscal_year_end:
                    score += 500
                elif source.instant_date == target.end_date:
                    score += 400
            
            # Prefer January 1 of next year (common end-of-year date for component data)
            target_year = target.fiscal_year
            if target.start_date:
                target_year = target.start_date.year
            elif target.instant_date:
                target_year = target.instant_date.year
            
            if (source.instant_date.month == 1 and 
                source.instant_date.day == 1 and
                source.instant_date.year == target_year + 1):
                score += 600  # Prefer Jan 1 of next year over Dec 31
            
            # Prefer December 31 (fallback)
            if source.instant_date.month == 12 and source.instant_date.day == 31:
                score += 100
            
            # Prefer most recent date (higher score for later dates)
            score += (source.instant_date.year * 10) + source.instant_date.month
            
            scored.append((score, source))
        
        if not scored:
            return None
        
        # Return highest scoring period
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    
    def _match_calendar_year_end(
        self, 
        target: PeriodInfo, 
        sources: List[PeriodInfo]
    ) -> Optional[PeriodInfo]:
        """Match by calendar year end (December 31)"""
        target_year = target.fiscal_year
        if target.instant_date:
            target_year = target.instant_date.year
        
        # Find December 31 of target year
        for source in sources:
            if (source.instant_date and 
                source.instant_date.month == 12 and 
                source.instant_date.day == 31 and
                source.instant_date.year == target_year):
                return source
        
        return None
    
    def _match_previous_year(
        self, 
        target: PeriodInfo, 
        sources: List[PeriodInfo],
        filing_id: Optional[int] = None
    ) -> Optional[PeriodInfo]:
        """
        Match previous fiscal year END date.
        
        For beginning balance calculations:
        - Target: 2024 duration period (start_date = 2024-01-01, end_date = 2025-01-01)
        - Source: 2023 instant period with instant_date = 2023-12-31 (end of previous year)
        
        CRITICAL: We want the END of the previous year, not the START of the current year.
        """
        target_year = target.fiscal_year
        if target.start_date:
            # For duration periods, use start_date year - 1 to get previous year
            target_year = target.start_date.year
        elif target.instant_date:
            target_year = target.instant_date.year
        
        previous_year = target_year - 1
        
        # Filter to previous year periods
        previous_year_sources = [
            s for s in sources 
            if s.fiscal_year == previous_year or 
               (s.instant_date and s.instant_date.year == previous_year)
        ]
        
        if not previous_year_sources:
            return None
        
        # Get fiscal_year_end if available
        fiscal_year_end = target.fiscal_year_end
        if filing_id and not fiscal_year_end:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT fiscal_year_end
                    FROM dim_filings
                    WHERE filing_id = :filing_id
                """), {'filing_id': filing_id})
                row = result.fetchone()
                if row:
                    fiscal_year_end = row[0]
        
        # Score each source period - prefer END of previous year
        scored = []
        for source in previous_year_sources:
            if source.period_type != 'instant' or not source.instant_date:
                continue
            
            score = 0
            
            # CRITICAL: Prefer December 31 of previous year (end of previous year)
            if source.instant_date.month == 12 and source.instant_date.day == 31:
                score += 1000
            
            # Prefer dates that match fiscal_year_end of previous year
            if fiscal_year_end:
                prev_year_end = fiscal_year_end.replace(year=previous_year)
                if source.instant_date == prev_year_end:
                    score += 500
            
            # Prefer dates that match target's start_date - 1 day (end of previous year)
            if target.start_date:
                prev_year_end_date = target.start_date - timedelta(days=1)
                if source.instant_date == prev_year_end_date:
                    score += 800
            
            # Prefer most recent date in previous year
            score += source.instant_date.day  # Higher score for later in month
            score += source.instant_date.month * 10  # Higher score for later months
            
            scored.append((score, source))
        
        if not scored:
            return None
        
        # Return highest scoring period
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    
    def get_periods_for_filing(
        self, 
        filing_id: int, 
        period_type: Optional[str] = None
    ) -> List[PeriodInfo]:
        """Get all periods for a filing, optionally filtered by period_type"""
        with self.engine.connect() as conn:
            query = text("""
                SELECT DISTINCT
                    tp.period_id,
                    tp.fiscal_year,
                    tp.fiscal_quarter,
                    tp.period_type,
                    tp.instant_date,
                    tp.start_date,
                    tp.end_date,
                    f.fiscal_year_end
                FROM dim_time_periods tp
                JOIN fact_financial_metrics fm ON tp.period_id = fm.period_id
                JOIN dim_filings f ON fm.filing_id = f.filing_id
                WHERE f.filing_id = :filing_id
            """)
            
            if period_type:
                query = text(str(query) + " AND tp.period_type = :period_type")
                result = conn.execute(query, {'filing_id': filing_id, 'period_type': period_type})
            else:
                result = conn.execute(query, {'filing_id': filing_id})
            
            periods = []
            for row in result.fetchall():
                periods.append(PeriodInfo(
                    period_id=row[0],
                    fiscal_year=row[1],
                    fiscal_quarter=row[2],
                    period_type=row[3],
                    instant_date=row[4],
                    start_date=row[5],
                    end_date=row[6],
                    fiscal_year_end=row[7]
                ))
            
            return periods

