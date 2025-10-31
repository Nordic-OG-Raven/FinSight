"""
Pydantic data models for FinSight

Defines schemas for financial facts, validation reports, and provenance tracking.
"""
from typing import Optional, Dict, Any, List
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


class FinancialFact(BaseModel):
    """
    Core model for a single financial fact extracted from XBRL
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # Core identification
    company: str = Field(..., description="Company ticker or identifier")
    filing_type: str = Field(..., description="Filing type (10-K, 20-F, etc.)")
    fiscal_year_end: date = Field(..., description="Fiscal year end date")
    
    # Concept information
    concept: str = Field(..., description="XBRL concept name")
    concept_namespace: Optional[str] = Field(None, description="Taxonomy namespace URI")
    taxonomy: str = Field(..., description="Taxonomy type (US-GAAP, IFRS, DEI, custom)")
    normalized_label: Optional[str] = Field(None, description="Human-readable label")
    
    # Values
    value_text: str = Field(..., description="Text representation of value")
    value_numeric: Optional[float] = Field(None, description="Numeric value if applicable")
    
    # Context (period and dimensions)
    context_id: Optional[str] = Field(None, description="XBRL context identifier")
    period_type: Optional[str] = Field(None, description="instant, duration, or forever")
    period_start: Optional[date] = Field(None, description="Period start date")
    period_end: Optional[date] = Field(None, description="Period end date")
    instant_date: Optional[date] = Field(None, description="Instant date for point-in-time facts")
    
    # Entity
    entity_scheme: Optional[str] = Field(None, description="Entity identifier scheme")
    entity_identifier: Optional[str] = Field(None, description="Entity identifier (CIK, etc.)")
    
    # Dimensions (segments, scenarios)
    dimensions: Dict[str, Any] = Field(default_factory=dict, description="Dimensional breakdowns")
    
    # Units
    unit_id: Optional[str] = Field(None, description="Unit identifier")
    unit_measure: Optional[str] = Field(None, description="Unit of measure (USD, shares, etc.)")
    unit_type: Optional[str] = Field(None, description="currency, shares, pure, other")
    
    # Concept metadata
    concept_type: Optional[str] = Field(None, description="Concept data type")
    concept_balance: Optional[str] = Field(None, description="debit or credit")
    concept_period_type: Optional[str] = Field(None, description="Concept period type")
    concept_data_type: Optional[str] = Field(None, description="Base data type")
    concept_abstract: bool = Field(False, description="Whether concept is abstract")
    
    # Provenance
    source_line: Optional[int] = Field(None, description="Line number in source document")
    source_url: Optional[str] = Field(None, description="URL of source filing")
    fact_id: Optional[str] = Field(None, description="Fact identifier in document")
    decimals: Optional[str] = Field(None, description="Decimal specification")
    precision: Optional[str] = Field(None, description="Precision specification")
    
    # Metadata
    extraction_timestamp: datetime = Field(default_factory=datetime.now, description="When fact was extracted")
    
    def to_db_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for database insertion"""
        return {
            'company': self.company,
            'filing_type': self.filing_type,
            'fiscal_year_end': self.fiscal_year_end,
            'concept': self.concept,
            'concept_namespace': self.concept_namespace,
            'taxonomy': self.taxonomy,
            'normalized_label': self.normalized_label,
            'value_text': self.value_text,
            'value_numeric': self.value_numeric,
            'context_id': self.context_id,
            'period_type': self.period_type,
            'period_start': self.period_start,
            'period_end': self.period_end,
            'instant_date': self.instant_date,
            'entity_scheme': self.entity_scheme,
            'entity_identifier': self.entity_identifier,
            'dimensions': self.dimensions,  # Will be stored as JSONB
            'unit_id': self.unit_id,
            'unit_measure': self.unit_measure,
            'unit_type': self.unit_type,
            'concept_type': self.concept_type,
            'concept_balance': self.concept_balance,
            'concept_period_type': self.concept_period_type,
            'concept_data_type': self.concept_data_type,
            'concept_abstract': self.concept_abstract,
            'source_line': self.source_line,
            'source_url': self.source_url,
            'fact_id': self.fact_id,
            'decimals': self.decimals,
            'precision': self.precision,
            'extraction_timestamp': self.extraction_timestamp
        }


class ValidationResult(BaseModel):
    """Result of a single validation rule"""
    rule_name: str = Field(..., description="Name of validation rule")
    passed: bool = Field(..., description="Whether rule passed")
    severity: str = Field("WARNING", description="ERROR, WARNING, or INFO")
    message: str = Field(..., description="Description of result")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class ValidationReport(BaseModel):
    """Complete validation report for a filing"""
    company: str
    filing_type: str
    fiscal_year_end: date
    
    # Results
    results: List[ValidationResult] = Field(default_factory=list)
    overall_score: float = Field(..., ge=0.0, le=1.0, description="Overall quality score 0-1")
    passed: bool = Field(..., description="Whether filing passed validation")
    
    # Statistics
    total_facts: int = Field(..., description="Total facts extracted")
    facts_with_numeric_values: int = Field(0)
    facts_with_periods: int = Field(0)
    facts_with_units: int = Field(0)
    completeness_score: float = Field(..., ge=0.0, le=1.0)
    
    # Metadata
    validation_timestamp: datetime = Field(default_factory=datetime.now)
    
    def add_result(self, result: ValidationResult):
        """Add a validation result"""
        self.results.append(result)
    
    def get_errors(self) -> List[ValidationResult]:
        """Get all ERROR severity results"""
        return [r for r in self.results if r.severity == "ERROR"]
    
    def get_warnings(self) -> List[ValidationResult]:
        """Get all WARNING severity results"""
        return [r for r in self.results if r.severity == "WARNING"]


class ProvenanceInfo(BaseModel):
    """Detailed provenance information for a fact"""
    extraction_method: str = Field("xbrl", description="xbrl, pdf, or llm")
    xbrl_concept: Optional[str] = None
    xbrl_context: Optional[str] = None
    pdf_page: Optional[int] = None
    pdf_table_id: Optional[str] = None
    llm_confidence: Optional[float] = None
    validation_rules_applied: List[str] = Field(default_factory=list)
    source_document_hash: Optional[str] = None


class FilingMetadata(BaseModel):
    """Metadata about a filing"""
    company: str
    ticker: str
    filing_type: str
    filing_date: date
    fiscal_year_end: date
    fiscal_year: int
    source_url: str
    document_type: str
    creation_software: Optional[str] = None
    namespaces: List[str] = Field(default_factory=list)
    total_facts_extracted: int = 0
    extraction_timestamp: datetime = Field(default_factory=datetime.now)
    extraction_duration_seconds: Optional[float] = None


class DataQualityMetrics(BaseModel):
    """Data quality metrics for a filing"""
    company: str
    fiscal_year_end: date
    
    # Completeness
    total_facts: int
    expected_facts: Optional[int] = None
    completeness_score: float = Field(..., ge=0.0, le=1.0)
    
    # Coverage by statement type
    income_statement_facts: int = 0
    balance_sheet_facts: int = 0
    cash_flow_facts: int = 0
    footnote_facts: int = 0
    
    # Quality indicators
    facts_with_provenance: int = 0
    facts_with_validation: int = 0
    validation_pass_rate: float = Field(0.0, ge=0.0, le=1.0)
    
    # Timestamp
    calculated_at: datetime = Field(default_factory=datetime.now)

