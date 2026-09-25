"""The public UI API. Helpers stay outside the bridge class."""

import logging
import json
import os
import sys
import webbrowser
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.constants import MAX_SAVED_TEXT, MODEL_NAME, QUESTION_MAX_CHARS
from app.db import DATA_LOCK, check_search, connect, initialize
from app import cases
from app.calc import Quantity

logger = logging.getLogger(__name__)


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SaveTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(max_length=MAX_SAVED_TEXT)


class TextResult(BaseModel):
    text: str | None = None
    error: str | None = None


class SearchResult(BaseModel):
    available: bool | None = None
    checked_at: str | None = None
    detail: str | None = None
    error: str | None = None


class CaseIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)


class SecImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    url: str = Field(min_length=1, max_length=2000)


class SecStatementInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    import_id: int = Field(gt=0)
    document_url: str = Field(min_length=1, max_length=2000)


class SecContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=1, max_length=254)


class SecContactResult(BaseModel):
    name: str | None = None
    email: str | None = None
    error: str | None = None


class SecItem(BaseModel):
    name: str
    url: str
    document_type: str | None
    size: int | None
    status: str
    detail: str | None
    document_id: int | None
    logical_document_id: str


class SecImportRecord(BaseModel):
    id: int
    request_url: str
    filing_url: str
    accession_number: str
    cik: str
    filing_date: str | None
    form_type: str | None
    status: str
    detail: str
    checked_at: str
    selected_document_url: str | None
    items: list[SecItem]


class SecStateResult(BaseModel):
    imports: list[SecImportRecord] | None = None
    active: bool = False
    error: str | None = None


class CreateCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=MAX_SAVED_TEXT)


class UpdateCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(max_length=MAX_SAVED_TEXT)
    status: Literal["research", "watching", "closed"]


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: int = Field(gt=0)
    block_id: int | None = Field(default=None, gt=0)
    quote: str | None = Field(default=None, max_length=10_000)


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    query: str = Field(min_length=1, max_length=500)


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    name: str = Field(max_length=200)
    kind: Literal["spinoff", "tender"]
    inputs: dict[str, Any]


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: int = Field(gt=0)
    block_id: int | None = Field(default=None, gt=0)
    quote: str = Field(min_length=1, max_length=10_000)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    decision: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=MAX_SAVED_TEXT)
    document_ids: list[int] = Field(max_length=1000)
    scenario_ids: list[int] = Field(max_length=1000)
    evidence: list[EvidenceInput] = Field(max_length=100)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    to_new_folder: bool = False


class SavedEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision_id: int = Field(gt=0)
    index: int = Field(ge=0)


class CaseRecord(BaseModel):
    id: int
    title: str | None
    question: str
    status: str
    created_at: str
    updated_at: str | None


class DocumentSummary(BaseModel):
    id: int
    logical_document_id: str
    name: str | None
    filing_date: str | None
    form_type: str | None
    original_sha256: str
    text_hash: str | None
    cleaner_version: str | None
    media_type: str | None
    processing_error: str | None
    searchable: bool


class Citation(BaseModel):
    document_id: int
    document_hash: str
    text_version_id: int
    start_offset: int
    end_offset: int
    quote: str
    status: Literal["quote matched"]


class DocumentView(BaseModel):
    id: int
    logical_document_id: str
    name: str | None
    filing_date: str | None
    form_type: str | None
    original_sha256: str
    text_hash: str | None
    cleaner_version: str | None
    media_type: str | None
    processing_error: str | None
    searchable: bool
    html: str
    canonical_text: str
    citation: Citation | None


class SearchHit(BaseModel):
    id: int
    block_id: int
    document_id: int
    name: str | None
    heading: str | None
    text: str
    start_offset: int
    end_offset: int
    partial: bool


class CalculationResult(BaseModel):
    inputs: dict[str, Any] | None = None
    outputs: dict[str, dict[str, Quantity]] | None = None
    display: dict[str, dict[str, str]] | None = None
    warning: str | None = None
    error: str | None = None


class ScenarioRecord(BaseModel):
    id: int
    case_id: int
    name: str
    kind: Literal["spinoff", "tender"]
    inputs: dict[str, Any]
    outputs: dict[str, dict[str, Quantity]]
    display: dict[str, dict[str, str]]
    warning: str | None
    created_at: str


class DecisionRecord(BaseModel):
    id: int
    case_id: int
    decision: str
    reason: str
    document_ids: list[int]
    scenario_ids: list[int]
    evidence: list[Citation]
    created_at: str


class CasesResult(BaseModel):
    cases: list[CaseRecord] | None = None
    error: str | None = None


class CaseResult(BaseModel):
    case: CaseRecord | None = None
    error: str | None = None


class DetailResult(BaseModel):
    documents: list[DocumentSummary] | None = None
    scenarios: list[ScenarioRecord] | None = None
    decisions: list[DecisionRecord] | None = None
    error: str | None = None


class DocumentResult(BaseModel):
    document: DocumentView | None = None
    error: str | None = None


class SearchHitsResult(BaseModel):
    hits: list[SearchHit] | None = None
    error: str | None = None


class SavedScenarioResult(BaseModel):
    scenario: ScenarioRecord | None = None
    error: str | None = None


class SavedDecisionResult(BaseModel):
    decision: DecisionRecord | None = None
    error: str | None = None


class ActionResult(BaseModel):
    message: str | None = None
    path: str | None = None
    warning: str | None = None
    cancelled: bool = False
    error: str | None = None


class AppStateResult(BaseModel):
    needs_setup: bool | None = None
    data_folder: str | None = None
    python_version: str | None = None
    runtime_warning: str | None = None
    second_backup_folder: str | None = None
    backup_names: list[str] | None = None
    backup_warnings: list[str] | None = None
    error: str | None = None


class SummarySourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    document_id: int = Field(gt=0)


class SummaryEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary_id: int = Field(gt=0)
    index: int = Field(ge=0, le=12)


class SummarySource(BaseModel):
    document_id: int
    name: str | None
    cleaner_version: str
    text_hash: str
    original_sha256: str
    start_offset: int
    end_offset: int
    total_chars: int


class SummaryStatement(BaseModel):
    text: str
    quote: str | None
    citation: Citation | None
    status: Literal['quote matched', 'unresolved', 'assumption']
    detail: str | None


class SummarySentence(BaseModel):
    section: Literal['company', 'event', 'what_must_happen', 'dates', 'unknowns', 'risks']
    text: str
    quote: str | None
    citation: Citation | None
    status: Literal['quote matched', 'unresolved', 'assumption']
    detail: str | None


class SummaryRecord(BaseModel):
    id: int
    run_id: int
    created_at: str
    model: str
    prompt_version: str
    source: SummarySource
    is_spinoff: Literal['yes', 'no', 'unclear']
    reasoning: SummaryStatement
    sentences: list[SummarySentence]
    stale: bool
    stale_reasons: list[str]
    usage: dict[str, Any] | None


class ModelRun(BaseModel):
    id: int
    status: str
    detail: str
    created_at: str
    completed_at: str | None
    usage: dict[str, Any] | None
    usage_uncertain: bool
    retry_count: int


class SummaryStateResult(BaseModel):
    selected_document_id: int | None = None
    source: SummarySource | None = None
    summary: SummaryRecord | None = None
    runs: list[ModelRun] = Field(default_factory=list)
    active: bool = False
    detail: str | None = None
    error: str | None = None


class SubscriptionStateResult(BaseModel):
    active: bool = False
    detail: str | None = None
    checked_at: str | None = None
    auth_type: str | None = None
    plan_type: str | None = None
    available: bool | None = None
    model: str = MODEL_NAME
    usage: dict[str, Any] | None = None
    error: str | None = None


class FactSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    document_id: int = Field(gt=0)


class FactEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fact_id: int = Field(gt=0)
    index: int = Field(ge=0)


class CheckFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    fact_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=MAX_SAVED_TEXT)


class CorrectFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    key: str = Field(min_length=1, max_length=100)
    previous_id: int | None = Field(gt=0)
    value: str | None = Field(max_length=MAX_SAVED_TEXT)
    unit: str | None = Field(max_length=200)
    currency: str | None = Field(max_length=200)
    entity: str | None = Field(max_length=1000)
    period: str | None = Field(max_length=1000)
    basis: Literal['not_applicable', 'historical', 'pro_forma', 'unknown']
    kind: Literal['published', 'forecast', 'assumption']
    qualifications: str | None = Field(max_length=MAX_SAVED_TEXT)
    reason: str = Field(min_length=1, max_length=MAX_SAVED_TEXT)
    document_id: int | None = Field(gt=0)
    quote: str | None = Field(max_length=10_000)


class FactSource(BaseModel):
    document_id: int
    name: str | None
    cleaner_version: str | None
    text_hash: str
    original_sha256: str
    total_chars: int
    filing_date: str | None
    accession_number: str | None


class FactCitation(BaseModel):
    citation: Citation
    fields: list[str]


class FactRecord(BaseModel):
    id: int
    key: str
    value: str | None
    unit: str | None
    currency: str | None
    entity: str | None
    period: str | None
    basis: Literal['not_applicable', 'historical', 'pro_forma', 'unknown']
    kind: Literal['published', 'forecast', 'assumption']
    status: Literal['extracted', 'checked', 'contradicted', 'unknown']
    origin: Literal['model', 'human']
    reason: str
    qualifications: str | None
    finding: Literal['value', 'blank_placeholder', 'not_found', 'conflicting']
    document_id: int | None
    run_id: int | None
    previous_id: int | None
    created_at: str
    citations: list[FactCitation]


class FactRow(BaseModel):
    key: str
    label: str
    effective: FactRecord | None
    proposal: FactRecord | None
    conflict: bool
    history: list[FactRecord]


class FactPassage(BaseModel):
    id: int
    document_id: int
    start_offset: int
    end_offset: int
    text: str
    heading: str | None
    partial: bool


class FactCoverage(BaseModel):
    run_id: int
    prompt_version: str
    source: FactSource
    passages: list[FactPassage]
    searches: dict[str, list[str]]
    key_passages: dict[str, list[int]]


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    case_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=QUESTION_MAX_CHARS)


class QuestionEvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    qa_id: int = Field(gt=0)
    index: int = Field(ge=0, le=7)


class QuestionAnswer(BaseModel):
    id: int
    case_id: int
    run_id: int
    created_at: str
    question: str
    source: FactSource
    passages: list[FactPassage]
    searches: list[str]
    warnings: list[str]
    sentences: list[SummaryStatement]
    limitations: list[str]
    prompt_version: str
    stale: bool
    stale_reason: str | None


class QuestionStateResult(BaseModel):
    case_id: int | None = None
    selected_document_id: int | None = None
    sources: list[FactSource] = Field(default_factory=list)
    answers: list[QuestionAnswer] = Field(default_factory=list)
    runs: list[ModelRun] = Field(default_factory=list)
    active: bool = False
    detail: str | None = None
    error: str | None = None


class FactStateResult(BaseModel):
    selected_document_id: int | None = None
    source: FactSource | None = None
    rows: list[FactRow] = Field(default_factory=list)
    active: bool = False
    detail: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    runs: list[ModelRun] = Field(default_factory=list)
    coverage: list[FactCoverage] = Field(default_factory=list)


def _failure(error: Exception, action: str) -> str:
    if isinstance(error, ValidationError):
        logger.warning("%s: invalid input.", action)
        first = error.errors(include_input=False, include_url=False)[0]
        return f"{action}: {'.'.join(map(str, first['loc']))}: {first['msg']}"
    if isinstance(error, ValueError):
        logger.warning("%s: input or saved-data validation failed.", action)
        return str(error)
    logger.exception("%s failed.", action)
    return f"{action} failed: {error}. Your saved records have been retained."


def _facts_failure(data_dir: Path, request, error: Exception, action: str) -> dict:
    message = _failure(error, action)
    try:
        value = CaseIdInput.model_validate({'case_id': request.get('case_id')} if isinstance(request, dict) else {})
    except ValidationError:
        return FactStateResult(error=message).model_dump(mode="json")
    try:
        state = FactStateResult(**cases.facts_status(data_dir, value.case_id))
        state.error = message
        return state.model_dump(mode="json")
    except Exception as status_error:
        logger.warning("Saved deal terms could not be read after %s (%s).", action, type(status_error).__name__)
        return FactStateResult(error=message + ' Saved deal terms could not be read.').model_dump(mode="json")


def _pick(bridge, folder: bool = False) -> Path | None:
    import webview

    if bridge._window is None:
        raise ValueError("Open the desktop window to choose a file or folder.")
    choices = bridge._window.create_file_dialog(
        webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN,
        allow_multiple=False,
        file_types=() if folder else ("HTML, text or PDF (*.html;*.htm;*.txt;*.pdf)",),
    )
    if not choices:
        return None
    return Path(choices[0] if not isinstance(choices, str) else choices).resolve()


def _second_backup(data_dir: Path) -> Path | None:
    with closing(connect(data_dir)) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = 'second_backup_folder'").fetchone()
    return Path(row[0]) if row else None


class Bridge:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._window = None

    def summary_status(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return SummaryStateResult(**cases.summary_status(self._data_dir, value.case_id)).model_dump()
        except Exception as error:
            return SummaryStateResult(error=_failure(error, 'Read summary')).model_dump()

    def question_status(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return QuestionStateResult(**cases.question_status(self._data_dir, value.case_id)).model_dump()
        except Exception as error:
            return QuestionStateResult(error=_failure(error, 'Read document questions')).model_dump()

    def ask_question(self, request: dict) -> dict:
        try:
            value = QuestionInput.model_validate(request)
            return QuestionStateResult(**cases.ask_question(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return QuestionStateResult(error=_failure(error, 'Ask document question')).model_dump()

    def cancel_question(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return QuestionStateResult(**cases.cancel_question(self._data_dir, value.case_id)).model_dump()
        except Exception as error:
            return QuestionStateResult(error=_failure(error, 'Cancel document question')).model_dump()

    def read_question_evidence(self, request: dict) -> dict:
        try:
            value = QuestionEvidenceInput.model_validate(request)
            return DocumentResult(document=cases.read_question_evidence(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return DocumentResult(error=_failure(error, 'Read answer quotation')).model_dump()

    def set_summary_source(self, request: dict) -> dict:
        try:
            value = SummarySourceInput.model_validate(request)
            return SummaryStateResult(**cases.set_summary_source(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return SummaryStateResult(error=_failure(error, 'Select summary source')).model_dump()

    def generate_summary(self, request: dict) -> dict:
        try:
            value = SummarySourceInput.model_validate(request)
            return SummaryStateResult(**cases.generate_summary(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return SummaryStateResult(error=_failure(error, 'Generate summary')).model_dump()

    def cancel_summary(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return SummaryStateResult(**cases.cancel_summary(self._data_dir, value.case_id)).model_dump()
        except Exception as error:
            return SummaryStateResult(error=_failure(error, 'Cancel summary')).model_dump()

    def read_summary_evidence(self, request: dict) -> dict:
        try:
            value = SummaryEvidenceInput.model_validate(request)
            return DocumentResult(document=cases.read_summary_evidence(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return DocumentResult(error=_failure(error, 'Read summary quotation')).model_dump()

    def subscription_status(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            return SubscriptionStateResult(**cases.subscription_state(self._data_dir)).model_dump()
        except Exception as error:
            return SubscriptionStateResult(error=_failure(error, 'Read subscription status')).model_dump()

    def check_subscription(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            return SubscriptionStateResult(**cases.check_subscription(self._data_dir)).model_dump()
        except Exception as error:
            return SubscriptionStateResult(error=_failure(error, 'Check subscription')).model_dump()

    def facts_status(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return FactStateResult(**cases.facts_status(self._data_dir, value.case_id)).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Read deal terms')

    def set_facts_source(self, request: dict) -> dict:
        try:
            value = FactSourceInput.model_validate(request)
            return FactStateResult(**cases.set_facts_source(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Select deal terms source')

    def extract_facts(self, request: dict) -> dict:
        try:
            value = FactSourceInput.model_validate(request)
            return FactStateResult(**cases.extract_facts(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Extract deal terms')

    def cancel_facts(self, request: dict) -> dict:
        try:
            value = CaseIdInput.model_validate(request)
            return FactStateResult(**cases.cancel_facts(self._data_dir, value.case_id)).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Cancel deal terms extraction')

    def read_fact_evidence(self, request: dict) -> dict:
        try:
            value = FactEvidenceInput.model_validate(request)
            return DocumentResult(document=cases.read_fact_evidence(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return DocumentResult(error=_failure(error, 'Read fact quotation')).model_dump(mode="json")

    def check_fact(self, request: dict) -> dict:
        try:
            value = CheckFactInput.model_validate(request)
            return FactStateResult(**cases.check_fact(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Check fact')

    def correct_fact(self, request: dict) -> dict:
        try:
            value = CorrectFactInput.model_validate(request)
            return FactStateResult(**cases.correct_fact(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return _facts_failure(self._data_dir, request, error, 'Save fact correction')

    def read_text(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            with closing(connect(self._data_dir)) as connection:
                row = connection.execute(
                    "SELECT value FROM settings WHERE key = 'saved_text'"
                ).fetchone()
            return TextResult(text=row["value"] if row is not None else None).model_dump()
        except ValidationError:
            logger.error("Invalid read-text request.")
            return TextResult(error="The read request was invalid.").model_dump()
        except Exception:
            logger.exception("Reading the saved text failed.")
            return TextResult(error="Could not read your saved text. See app.log.").model_dump()

    def save_text(self, request: dict) -> dict:
        try:
            value = SaveTextInput.model_validate(request)
            with DATA_LOCK, closing(connect(self._data_dir)) as connection, connection:
                connection.execute(
                    "INSERT INTO settings(key, value) VALUES ('saved_text', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (value.text,),
                )
            return TextResult(text=value.text).model_dump()
        except ValidationError:
            logger.error("Invalid save-text request.")
            return TextResult(error="Enter text of at most 100,000 characters.").model_dump()
        except Exception:
            logger.exception("Saving the text failed.")
            return TextResult(error="Could not save your text. See app.log.").model_dump()

    def read_search_check(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            with closing(connect(self._data_dir)) as connection:
                row = connection.execute(
                    "SELECT available, checked_at, detail FROM checks "
                    "WHERE name = 'fts5' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            if row is None:
                return SearchResult(error="Search has not been checked.").model_dump()
            return SearchResult(**dict(row)).model_dump()
        except ValidationError:
            logger.error("Invalid search-status request.")
            return SearchResult(error="The search-status request was invalid.").model_dump()
        except Exception:
            logger.exception("Reading the search check failed.")
            return SearchResult(error="Could not read the search check. See app.log.").model_dump()

    def app_state(self, request: dict) -> dict:
        try:
            from app.backup import list_backups

            EmptyInput.model_validate(request)
            needs_setup = not (self._data_dir / "app.db").exists()
            second = None if needs_setup else _second_backup(self._data_dir)
            warnings = []
            try:
                backups = list_backups(self._data_dir / "backups", warnings=warnings)
                backup_names = [item["name"] for item in backups]
            except (OSError, ValueError) as error:
                warnings.append(_failure(error, "Read available backups"))
                backup_names = None
            return AppStateResult(
                needs_setup=needs_setup, data_folder=str(self._data_dir),
                python_version=sys.version.split()[0],
                runtime_warning="Provisional Python 3.12 check; Python 3.13 compatibility is unverified."
                if sys.version_info[:2] != (3, 13) else None,
                second_backup_folder=str(second) if second else None,
                backup_names=backup_names, backup_warnings=warnings,
            ).model_dump()
        except Exception as error:
            return AppStateResult(error=_failure(error, "Read app status")).model_dump()

    def start_fresh(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            with DATA_LOCK:
                if (self._data_dir / "app.db").exists():
                    raise ValueError("A database already exists. Existing research will not be replaced.")
                initialize(self._data_dir)
                check_search(self._data_dir)
            return ActionResult(message="Your empty research database is ready.").model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Start fresh")).model_dump()

    def list_cases(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            return CasesResult(cases=cases.list_cases(self._data_dir)).model_dump()
        except Exception as error:
            return CasesResult(error=_failure(error, "Read cases")).model_dump()

    def create_case(self, request: dict) -> dict:
        try:
            value = CreateCaseInput.model_validate(request)
            return CaseResult(case=cases.create_case(self._data_dir, value.title, value.question)).model_dump()
        except Exception as error:
            return CaseResult(error=_failure(error, "Create case")).model_dump()

    def update_case(self, request: dict) -> dict:
        try:
            value = UpdateCaseInput.model_validate(request)
            return CaseResult(case=cases.update_case(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return CaseResult(error=_failure(error, "Save case")).model_dump()

    def case_detail(self, request: dict) -> dict:
        try:
            from app.documents import list_documents

            value = CaseIdInput.model_validate(request)
            return DetailResult(
                documents=list_documents(self._data_dir, value.case_id),
                scenarios=cases.list_scenarios(self._data_dir, value.case_id),
                decisions=cases.list_decisions(self._data_dir, value.case_id),
            ).model_dump(mode="json")
        except Exception as error:
            return DetailResult(error=_failure(error, "Read case")).model_dump()

    def import_local(self, request: dict) -> dict:
        try:
            from app.documents import import_local

            value = CaseIdInput.model_validate(request)
            selected = _pick(self)
            if selected is None:
                return ActionResult(cancelled=True).model_dump()
            document = import_local(self._data_dir, value.case_id, selected)
            return ActionResult(message=f"Saved {document['name'] or 'document'}.",
                                warning=document["processing_error"]).model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Import document")).model_dump()

    def sec_contact(self, request: dict) -> dict:
        try:
            from app import sec

            EmptyInput.model_validate(request)
            return SecContactResult(**sec.contact(self._data_dir)).model_dump()
        except Exception as error:
            return SecContactResult(error=_failure(error, "Read SEC contact")).model_dump()

    def save_sec_contact(self, request: dict) -> dict:
        try:
            from app import sec

            value = SecContactInput.model_validate(request)
            return SecContactResult(**sec.save_contact(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return SecContactResult(error=_failure(error, "Save SEC contact")).model_dump()

    def sec_import_status(self, request: dict) -> dict:
        try:
            from app import sec, worker

            value = CaseIdInput.model_validate(request)
            return SecStateResult(imports=sec.list_imports(self._data_dir, value.case_id),
                                  active=worker.busy()).model_dump()
        except Exception as error:
            return SecStateResult(error=_failure(error, "Read SEC import progress")).model_dump()

    def sec_import(self, request: dict) -> dict:
        try:
            from app import sec

            value = SecImportInput.model_validate(request)
            sec.start_import(self._data_dir, **value.model_dump())
            return self.sec_import_status({'case_id': value.case_id})
        except Exception as error:
            return SecStateResult(error=_failure(error, "Import SEC filing")).model_dump()

    def sec_select_statement(self, request: dict) -> dict:
        try:
            from app import sec

            value = SecStatementInput.model_validate(request)
            sec.select_statement(self._data_dir, **value.model_dump())
            return self.sec_import_status({'case_id': value.case_id})
        except Exception as error:
            return SecStateResult(error=_failure(error, "Select information statement")).model_dump()

    def search_documents(self, request: dict) -> dict:
        try:
            from app.documents import search

            value = SearchInput.model_validate(request)
            return SearchHitsResult(hits=search(self._data_dir, value.case_id, value.query)).model_dump()
        except Exception as error:
            return SearchHitsResult(error=_failure(error, "Search documents")).model_dump()

    def read_document(self, request: dict) -> dict:
        try:
            from app.documents import read_document

            value = DocumentInput.model_validate(request)
            return DocumentResult(document=read_document(self._data_dir, **value.model_dump())).model_dump()
        except Exception as error:
            return DocumentResult(error=_failure(error, "Open saved document")).model_dump()

    def open_original(self, request: dict) -> dict:
        try:
            from app.documents import original_path

            value = DocumentInput.model_validate(request)
            if not webbrowser.open(original_path(self._data_dir, value.document_id).as_uri()):
                raise ValueError("The external browser could not be opened.")
            return ActionResult(message="Original opened in the external browser.").model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Open original")).model_dump()

    def read_saved_evidence(self, request: dict) -> dict:
        try:
            from app.documents import read_citation

            value = SavedEvidenceInput.model_validate(request)
            with closing(connect(self._data_dir)) as connection:
                row = connection.execute("SELECT evidence_json FROM decisions WHERE id = ?", (value.decision_id,)).fetchone()
            if row is None:
                raise ValueError("The saved decision does not exist.")
            evidence = json.loads(row[0])
            if value.index >= len(evidence):
                raise ValueError("The saved passage does not exist.")
            return DocumentResult(document=read_citation(self._data_dir, evidence[value.index])).model_dump()
        except Exception as error:
            return DocumentResult(error=_failure(error, "Open saved evidence")).model_dump()

    def calculate_scenario(self, request: dict) -> dict:
        try:
            value = ScenarioInput.model_validate(request)
            return CalculationResult(**cases.calculate_scenario(value.kind, value.inputs)).model_dump(mode="json")
        except Exception as error:
            return CalculationResult(error=_failure(error, "Cannot calculate")).model_dump()

    def save_scenario(self, request: dict) -> dict:
        try:
            value = ScenarioInput.model_validate(request)
            return SavedScenarioResult(scenario=cases.save_scenario(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return SavedScenarioResult(error=_failure(error, "Save scenario")).model_dump()

    def save_decision(self, request: dict) -> dict:
        try:
            value = DecisionInput.model_validate(request)
            return SavedDecisionResult(decision=cases.save_decision(self._data_dir, **value.model_dump())).model_dump(mode="json")
        except Exception as error:
            return SavedDecisionResult(error=_failure(error, "Save decision")).model_dump()

    def export_case(self, request: dict) -> dict:
        try:
            from app.backup import export_case

            value = CaseIdInput.model_validate(request)
            destination = _pick(self, folder=True)
            if destination is None:
                return ActionResult(cancelled=True).model_dump()
            result = export_case(self._data_dir, value.case_id, destination)
            return ActionResult(message="Case exported as Markdown and facts CSV.",
                                path=str(Path(result["paths"][0]).parent), warning=result.get("warning")).model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Export case")).model_dump()

    def create_backup(self, request: dict) -> dict:
        try:
            from app.backup import create_backup

            EmptyInput.model_validate(request)
            result = create_backup(self._data_dir, _second_backup(self._data_dir))
            return ActionResult(message="Complete backup saved and verified.", path=str(result["path"]),
                                warning=result.get("warning")).model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Back up research")).model_dump()

    def choose_second_backup(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            selected = _pick(self, folder=True)
            if selected is None:
                return ActionResult(cancelled=True).model_dump()
            with DATA_LOCK, closing(connect(self._data_dir)) as connection, connection:
                connection.execute(
                    "INSERT INTO settings VALUES ('second_backup_folder', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(selected),)
                )
            return ActionResult(message="Second backup folder saved.", path=str(selected)).model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Set backup folder")).model_dump()

    def restore_backup(self, request: dict) -> dict:
        try:
            from app.backup import restore_backup

            value = RestoreInput.model_validate(request)
            source = _pick(self, folder=True)
            if source is None:
                return ActionResult(cancelled=True).model_dump()
            destination = _pick(self, folder=True) if value.to_new_folder else self._data_dir
            if destination is None:
                return ActionResult(cancelled=True).model_dump()
            with DATA_LOCK:
                restore_backup(source, destination)
                initialize(destination)
                check_search(destination)
            return ActionResult(message="Backup restored into the empty folder; existing research was preserved.",
                                path=str(destination), warning="Credentials must be entered again if needed.").model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Restore backup")).model_dump()

    def open_data_folder(self, request: dict) -> dict:
        try:
            EmptyInput.model_validate(request)
            os.startfile(self._data_dir)
            return ActionResult(message="Research data folder opened.").model_dump()
        except Exception as error:
            return ActionResult(error=_failure(error, "Open data folder")).model_dump()
