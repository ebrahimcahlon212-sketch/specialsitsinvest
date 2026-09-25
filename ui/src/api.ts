// Hand-maintained mirror of app/bridge.py. Only this module accesses pywebview.
type EmptyInput = Record<string, never>;
type CaseIdInput = { case_id: number };
export type Quantity = { value: string | null; unit: string; currency: string | null; entity: string | null; period: string | null };
export type CaseRecord = { id: number; title: string | null; question: string; status: string; created_at: string; updated_at: string | null };
export type DocumentSummary = {
  id: number; logical_document_id: string; name: string | null; filing_date: string | null;
  form_type: string | null; original_sha256: string; text_hash: string | null;
  cleaner_version: string | null; media_type: string | null; processing_error: string | null; searchable: boolean;
};
export type Citation = { document_id: number; document_hash: string; text_version_id: number;
  start_offset: number; end_offset: number; quote: string; status: 'quote matched' };
export type DocumentView = DocumentSummary & { html: string; canonical_text: string; citation: Citation | null };
export type DocumentRequest = { document_id: number; block_id?: number | null; quote?: string | null };
export type SearchHit = { id: number; block_id: number; document_id: number; name: string | null;
  heading: string | null; text: string; start_offset: number; end_offset: number; partial: boolean };
export type Calculation = { inputs: Record<string, unknown>; outputs: Record<string, Record<string, Quantity>>;
  display: Record<string, Record<string, string>>; warning: string | null };
export type ScenarioRequest = { case_id: number; name: string; kind: 'spinoff' | 'tender'; inputs: Record<string, unknown> };
export type ScenarioRecord = Calculation & { id: number; case_id: number; name: string; kind: 'spinoff' | 'tender'; created_at: string };
export type EvidenceInput = { document_id: number; block_id: number | null; quote: string };
export type DecisionRequest = { case_id: number; decision: string; reason: string; document_ids: number[];
  scenario_ids: number[]; evidence: EvidenceInput[] };
export type DecisionRecord = Omit<DecisionRequest, 'evidence'> & { id: number; created_at: string; evidence: Citation[] };
export type TextResult = { text: string | null; error: string | null };
export type SearchResult = { available: boolean | null; checked_at: string | null; detail: string | null; error: string | null };
export type ActionResult = { message: string | null; path: string | null; warning: string | null; cancelled: boolean; error: string | null };
export type AppState = { needs_setup: boolean; data_folder: string; python_version: string; runtime_warning: string | null;
  second_backup_folder: string | null; backup_names: string[] | null; backup_warnings: string[]; error: string | null };
export type CaseDetail = { documents: DocumentSummary[]; scenarios: ScenarioRecord[]; decisions: DecisionRecord[] };
export type SecItem = { name: string; url: string; document_type: string | null; size: number | null;
  status: string; detail: string | null; document_id: number | null; logical_document_id: string };
export type SecImport = { id: number; request_url: string; filing_url: string; accession_number: string;
  cik: string; filing_date: string | null; form_type: string | null; status: string; detail: string;
  checked_at: string; selected_document_url: string | null; items: SecItem[] };
export type SecImportResult = { imports: SecImport[] | null; active: boolean; error: string | null };
export type SecContact = { name: string | null; email: string | null; error: string | null };
export type SummarySource = { document_id: number; name: string | null; cleaner_version: string; text_hash: string;
  original_sha256: string; start_offset: number; end_offset: number; total_chars: number;
  filing_date?: string | null; form_type?: string | null; source_url?: string | null; supplied_chars?: number | null;
  passages?: { id: number; start_offset: number; end_offset: number; heading: string | null; text: string; partial: boolean }[];
  warnings?: string[] };
export type SummaryStatement = { text: string; quote: string | null; citation: Citation | null;
  status: 'quote matched' | 'unresolved' | 'assumption'; detail: string | null; ai_comment?: string | null };
export type SummarySentence = SummaryStatement & { section: 'company' | 'event' | 'what_must_happen' | 'dates' | 'unknowns' | 'risks' };
export type SummaryRecord = { id: number; run_id: number; created_at: string; model: string; prompt_version: string;
  source: SummarySource; is_spinoff: 'yes' | 'no' | 'unclear'; reasoning: SummaryStatement; sentences: SummarySentence[];
  stale: boolean; stale_reasons: string[]; usage: Record<string, unknown> | null;
  sources?: SummarySource[]; warnings?: string[]; effort?: string | null };
export type ModelRun = { id: number; status: string; detail: string; created_at: string; completed_at: string | null;
  usage: Record<string, unknown> | null; retry_count: number; usage_uncertain: boolean };
export type SummaryState = { selected_document_id: number | null; source: SummarySource | null; summary: SummaryRecord | null;
  selected_document_ids: number[]; sources: SummarySource[]; warnings: string[]; model: string; effort: string; deadline_seconds: number;
  runs: ModelRun[]; active: boolean; detail: string | null; error: string | null };
export type SubscriptionState = { active: boolean; detail: string | null; checked_at: string | null; auth_type: string | null;
  plan_type: string | null; available: boolean | null; model: string; effort?: string | null;
  usage: Record<string, unknown> | null; error: string | null };
export type FactSource = { document_id: number; name: string | null; cleaner_version: string | null; text_hash: string;
  original_sha256: string; total_chars: number; filing_date: string | null; accession_number: string | null };
export type FactRecord = { id: number; key: string; value: string | null; unit: string | null; currency: string | null;
  entity: string | null; period: string | null; basis: 'not_applicable' | 'historical' | 'pro_forma' | 'unknown';
  kind: 'published' | 'forecast' | 'assumption'; status: 'extracted' | 'checked' | 'contradicted' | 'unknown';
  origin: 'model' | 'human'; reason: string; qualifications: string | null;
  finding: 'value' | 'blank_placeholder' | 'not_found' | 'conflicting'; document_id: number | null;
  run_id: number | null; previous_id: number | null; created_at: string; citations: { citation: Citation; fields: string[] }[] };
export type FactRow = { key: string; label: string; effective: FactRecord | null; proposal: FactRecord | null;
  conflict: boolean; history: FactRecord[] };
export type FactCoverage = { run_id: number; prompt_version: string; source: FactSource;
  passages: { id: number; document_id: number; start_offset: number; end_offset: number; text: string; heading: string | null; partial: boolean }[];
  searches: Record<string, string[]>; key_passages: Record<string, number[]> };
export type FactState = { selected_document_id: number | null; source: FactSource | null; rows: FactRow[];
  active: boolean; detail: string | null; error: string | null; warnings: string[]; runs: ModelRun[]; coverage: FactCoverage[] };
export type FactCorrection = { case_id: number; key: string; previous_id: number | null; value: string | null;
  unit: string | null; currency: string | null; entity: string | null; period: string | null; basis: FactRecord['basis'];
  kind: FactRecord['kind']; qualifications: string | null; reason: string; document_id: number | null; quote: string | null };
export type QuestionAnswer = { id: number; case_id: number; run_id: number; created_at: string; question: string;
  source: FactSource; passages: FactCoverage['passages']; searches: unknown[]; warnings: string[];
  sentences: SummaryStatement[]; limitations: string[]; prompt_version: string; stale: boolean; stale_reason: string | null };
export type QuestionState = { case_id: number; selected_document_id: number | null; sources: FactSource[];
  active: boolean; detail: string | null; error: string | null; answers: QuestionAnswer[]; runs: ModelRun[] };
type Failure = { error: string | null };
type Bridge = {
  read_text(request: EmptyInput): Promise<TextResult>;
  save_text(request: { text: string }): Promise<TextResult>;
  read_search_check(request: EmptyInput): Promise<SearchResult>;
  app_state(request: EmptyInput): Promise<Partial<AppState> & Failure>;
  start_fresh(request: EmptyInput): Promise<ActionResult>;
  list_cases(request: EmptyInput): Promise<{ cases: CaseRecord[] | null } & Failure>;
  create_case(request: { title: string; question: string }): Promise<{ case: CaseRecord | null } & Failure>;
  update_case(request: { case_id: number; title: string; question: string; status: 'research' | 'watching' | 'closed' }): Promise<{ case: CaseRecord | null } & Failure>;
  case_detail(request: CaseIdInput): Promise<{ documents: DocumentSummary[] | null; scenarios: ScenarioRecord[] | null; decisions: DecisionRecord[] | null } & Failure>;
  import_local(request: CaseIdInput): Promise<ActionResult>;
  search_documents(request: CaseIdInput & { query: string }): Promise<{ hits: SearchHit[] | null } & Failure>;
  read_document(request: DocumentRequest): Promise<{ document: DocumentView | null } & Failure>;
  open_original(request: DocumentRequest): Promise<ActionResult>;
  read_saved_evidence(request: { decision_id: number; index: number }): Promise<{ document: DocumentView | null } & Failure>;
  calculate_scenario(request: ScenarioRequest): Promise<Partial<Calculation> & Failure>;
  save_scenario(request: ScenarioRequest): Promise<{ scenario: ScenarioRecord | null } & Failure>;
  save_decision(request: DecisionRequest): Promise<{ decision: DecisionRecord | null } & Failure>;
  export_case(request: CaseIdInput): Promise<ActionResult>;
  create_backup(request: EmptyInput): Promise<ActionResult>;
  choose_second_backup(request: EmptyInput): Promise<ActionResult>;
  restore_backup(request: { to_new_folder: boolean }): Promise<ActionResult>;
  open_data_folder(request: EmptyInput): Promise<ActionResult>;
  sec_import(request: CaseIdInput & { url: string }): Promise<SecImportResult>;
  sec_import_status(request: CaseIdInput): Promise<SecImportResult>;
  sec_select_statement(request: CaseIdInput & { import_id: number; document_url: string }): Promise<SecImportResult>;
  sec_contact(request: EmptyInput): Promise<SecContact>;
  save_sec_contact(request: { name: string; email: string }): Promise<SecContact>;
  summary_status(request: CaseIdInput): Promise<SummaryState>;
  set_summary_source(request: CaseIdInput & ({ document_ids: number[] } | { document_id: number })): Promise<SummaryState>;
  generate_summary(request: CaseIdInput & ({ document_ids: number[] } | { document_id: number })): Promise<SummaryState>;
  cancel_summary(request: CaseIdInput): Promise<SummaryState>;
  read_summary_evidence(request: { summary_id: number; index: number }): Promise<{ document: DocumentView | null } & Failure>;
  subscription_status(request: EmptyInput): Promise<SubscriptionState>;
  check_subscription(request: EmptyInput): Promise<SubscriptionState>;
  facts_status(request: CaseIdInput): Promise<FactState>;
  set_facts_source(request: CaseIdInput & { document_id: number }): Promise<FactState>;
  extract_facts(request: CaseIdInput & { document_id: number }): Promise<FactState>;
  cancel_facts(request: CaseIdInput): Promise<FactState>;
  read_fact_evidence(request: { fact_id: number; index: number }): Promise<{ document: DocumentView | null } & Failure>;
  check_fact(request: CaseIdInput & { fact_id: number; reason: string }): Promise<FactState>;
  correct_fact(request: FactCorrection): Promise<FactState>;
  question_status(request: CaseIdInput): Promise<QuestionState>;
  ask_question(request: CaseIdInput & { document_id: number; question: string }): Promise<QuestionState>;
  cancel_question(request: CaseIdInput): Promise<QuestionState>;
  read_question_evidence(request: { qa_id: number; index: number }): Promise<{ document: DocumentView | null } & Failure>;
};

declare global { interface Window { pywebview?: { api?: Bridge } } }
const bridgeReady = new Promise<Bridge>((resolve) => {
  const ready = () => { if (window.pywebview?.api?.read_text) resolve(window.pywebview.api); };
  window.addEventListener('pywebviewready', ready, { once: true });
  ready();
});
function checked<T extends Failure>(result: T): T { if (result.error) throw new Error(result.error); return result; }
function present<T>(value: T | null | undefined): T { if (value == null) throw new Error('The app returned an incomplete result.'); return value; }

export async function readText() { return checked(await (await bridgeReady).read_text({})); }
export async function saveText(text: string) { return checked(await (await bridgeReady).save_text({ text })); }
export async function readSearchCheck() { return checked(await (await bridgeReady).read_search_check({})); }
export async function appState(): Promise<AppState> {
  const r = checked(await (await bridgeReady).app_state({}));
  return { ...r, needs_setup: present(r.needs_setup), data_folder: present(r.data_folder),
    python_version: present(r.python_version), runtime_warning: r.runtime_warning ?? null,
    second_backup_folder: r.second_backup_folder ?? null, backup_names: r.backup_names ?? null, backup_warnings: present(r.backup_warnings) };
}
export async function startFresh() { return checked(await (await bridgeReady).start_fresh({})); }
export async function listCases() { return present(checked(await (await bridgeReady).list_cases({})).cases); }
export async function createCase(title: string, question: string) { return present(checked(await (await bridgeReady).create_case({ title, question })).case); }
export async function updateCase(request: Parameters<Bridge['update_case']>[0]) { return present(checked(await (await bridgeReady).update_case(request)).case); }
export async function caseDetail(case_id: number): Promise<CaseDetail> {
  const r = checked(await (await bridgeReady).case_detail({ case_id }));
  return { documents: present(r.documents), scenarios: present(r.scenarios), decisions: present(r.decisions) };
}
export async function importLocal(case_id: number) { return checked(await (await bridgeReady).import_local({ case_id })); }
export async function searchDocuments(case_id: number, query: string) { return present(checked(await (await bridgeReady).search_documents({ case_id, query })).hits); }
export async function readDocument(request: DocumentRequest) { return present(checked(await (await bridgeReady).read_document(request)).document); }
export async function openOriginal(document_id: number) { return checked(await (await bridgeReady).open_original({ document_id })); }
export async function readSavedEvidence(decision_id: number, index: number) { return present(checked(await (await bridgeReady).read_saved_evidence({ decision_id, index })).document); }
export async function calculateScenario(request: ScenarioRequest): Promise<Calculation> {
  const r = checked(await (await bridgeReady).calculate_scenario(request));
  return { inputs: present(r.inputs), outputs: present(r.outputs), display: present(r.display), warning: r.warning ?? null };
}
export async function saveScenario(request: ScenarioRequest) { return present(checked(await (await bridgeReady).save_scenario(request)).scenario); }
export async function saveDecision(request: DecisionRequest) { return present(checked(await (await bridgeReady).save_decision(request)).decision); }
export async function exportCase(case_id: number) { return checked(await (await bridgeReady).export_case({ case_id })); }
export async function createBackup() { return checked(await (await bridgeReady).create_backup({})); }
export async function chooseSecondBackup() { return checked(await (await bridgeReady).choose_second_backup({})); }
export async function restoreBackup(to_new_folder: boolean) { return checked(await (await bridgeReady).restore_backup({ to_new_folder })); }
export async function openDataFolder() { return checked(await (await bridgeReady).open_data_folder({})); }
export async function secImport(case_id: number, url: string) {
  const result = checked(await (await bridgeReady).sec_import({ case_id, url }));
  return { ...result, imports: present(result.imports) };
}
export async function secImportStatus(case_id: number) {
  const result = checked(await (await bridgeReady).sec_import_status({ case_id }));
  return { ...result, imports: present(result.imports) };
}
export async function secSelectStatement(case_id: number, import_id: number, document_url: string) {
  const result = checked(await (await bridgeReady).sec_select_statement({ case_id, import_id, document_url }));
  return { ...result, imports: present(result.imports) };
}
export async function secContact() { return checked(await (await bridgeReady).sec_contact({})); }
export async function saveSecContact(name: string, email: string) {
  return checked(await (await bridgeReady).save_sec_contact({ name, email }));
}
export async function summaryStatus(case_id: number) { return (await bridgeReady).summary_status({ case_id }); }
export async function setSummarySource(case_id: number, document_ids: number[]) { return checked(await (await bridgeReady).set_summary_source({ case_id, document_ids })); }
export async function generateSummary(case_id: number, document_ids: number[]) { return checked(await (await bridgeReady).generate_summary({ case_id, document_ids })); }
export async function cancelSummary(case_id: number) { return checked(await (await bridgeReady).cancel_summary({ case_id })); }
export async function readSummaryEvidence(summary_id: number, index: number) {
  return present(checked(await (await bridgeReady).read_summary_evidence({ summary_id, index })).document);
}
export async function subscriptionStatus() { return (await bridgeReady).subscription_status({}); }
export async function checkSubscription() { return (await bridgeReady).check_subscription({}); }
export async function factsStatus(case_id: number) { return (await bridgeReady).facts_status({ case_id }); }
export async function setFactsSource(case_id: number, document_id: number) { return (await bridgeReady).set_facts_source({ case_id, document_id }); }
export async function extractFacts(case_id: number, document_id: number) { return (await bridgeReady).extract_facts({ case_id, document_id }); }
export async function cancelFacts(case_id: number) { return (await bridgeReady).cancel_facts({ case_id }); }
export async function readFactEvidence(fact_id: number, index: number) {
  return present(checked(await (await bridgeReady).read_fact_evidence({ fact_id, index })).document);
}
export async function checkFact(case_id: number, fact_id: number, reason: string) { return (await bridgeReady).check_fact({ case_id, fact_id, reason }); }
export async function correctFact(request: FactCorrection) { return (await bridgeReady).correct_fact(request); }
export async function questionStatus(case_id: number) { return (await bridgeReady).question_status({ case_id }); }
export async function askQuestion(case_id: number, document_id: number, question: string) {
  return checked(await (await bridgeReady).ask_question({ case_id, document_id, question }));
}
export async function cancelQuestion(case_id: number) { return checked(await (await bridgeReady).cancel_question({ case_id })); }
export async function readQuestionEvidence(qa_id: number, index: number) {
  return present(checked(await (await bridgeReady).read_question_evidence({ qa_id, index })).document);
}
