import { useEffect, useRef, useState } from 'react';
import { Accordion, Alert, Badge, Button, Checkbox, Container, Divider, Drawer, Group, Paper, Select, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import * as api from './api';
import type { ActionResult, AppState, CaseRecord, CaseDetail, DocumentView, EvidenceInput, ScenarioRecord, SearchHit, SearchResult, SecImport, SecImportResult } from './api';
import Calculators from './Calculators';
import SummaryPanel, { SubscriptionSettings } from './Summary';
import FactsPanel from './Facts';
import QuestionsPanel from './Questions';
import './styles.css';

function actionText(result: ActionResult) {
  return result.cancelled ? 'Cancelled.' : [result.message, result.path, result.warning].filter(Boolean).join('\n');
}
function Feedback({ error, message }: { error: string | null; message: string }) {
  return <>{error && <Alert color="red" role="alert">{error}</Alert>}
    {message && <Text role="status" style={{ whiteSpace: 'pre-wrap' }}>{message}</Text>}</>;
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [records, setRecords] = useState<CaseRecord[]>([]);
  const [selected, setSelected] = useState<CaseRecord | null>(null);
  const [screen, setScreen] = useState<'cases' | 'settings'>('cases');
  const [filter, setFilter] = useState('');
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('Connecting to the desktop app…');
  const [busy, setBusy] = useState(false);

  async function reload() {
    const next = await api.appState();
    setState(next);
    if (!next.needs_setup) setRecords(await api.listCases());
    setMessage('');
  }
  useEffect(() => { reload().catch((reason) => setError(String(reason))); }, []);
  async function setup(restore: boolean) {
    setBusy(true); setError(null);
    try {
      const result = restore ? await api.restoreBackup(false) : await api.startFresh();
      await reload(); setMessage(actionText(result));
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }
  async function addCase() {
    setBusy(true); setError(null);
    try {
      const value = await api.createCase(title, question);
      setTitle(''); setQuestion(''); await reload(); setSelected(value);
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }
  function savedCase(value: CaseRecord) {
    setSelected(value); setRecords(records.map((row) => row.id === value.id ? value : row));
  }

  return <Container size="xl" py="lg"><Stack>
    <Group justify="space-between" wrap="wrap">
      <Title order={1}>Investment Research</Title>
      {state && !state.needs_setup && <Group>
        <Button variant={screen === 'cases' ? 'filled' : 'default'} onClick={() => { setScreen('cases'); setSelected(null); }}>Cases</Button>
        <Button variant={screen === 'settings' ? 'filled' : 'default'} onClick={() => setScreen('settings')}>Settings</Button>
      </Group>}
    </Group>
    {state?.runtime_warning && <Alert color="yellow">{state.runtime_warning}</Alert>}
    <Feedback error={error} message={message} />
    {state?.needs_setup ? <Paper withBorder p="lg"><Stack>
      <Title order={2}>Start your research folder</Title>
      <Text>No research database exists at {state.data_folder}.</Text>
      <Text>Start fresh, or select a complete backup folder containing its manifest. Existing research is never replaced.</Text>
      <Group><Button loading={busy} onClick={() => setup(false)}>Start fresh</Button>
        <Button variant="default" disabled={busy} onClick={() => setup(true)}>Restore from backup</Button></Group>
    </Stack></Paper> : state && screen === 'settings' ? <Settings state={state} refresh={reload} />
      : state && selected ? <CaseScreen key={selected.id} record={selected} onSaved={savedCase} onBack={() => setSelected(null)} />
      : state && <>
        <Paper withBorder p="lg"><Stack>
          <Title order={2}>Create a case</Title>
          <Text size="sm">One case represents one event. Enter a name of your choosing; no company or filing details are assumed.</Text>
          <TextInput label="Case name" value={title} onChange={(e) => setTitle(e.currentTarget.value)} maxLength={200} />
          <Textarea label="Research question or notes" value={question} onChange={(e) => setQuestion(e.currentTarget.value)} autosize minRows={2} />
          <Button onClick={addCase} loading={busy} disabled={!title.trim()}>Create case</Button>
        </Stack></Paper>
        <TextInput label="Find a case" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} />
        <Table.ScrollContainer minWidth={550}><Table striped highlightOnHover>
          <Table.Thead><Table.Tr><Table.Th>Case</Table.Th><Table.Th>Status</Table.Th><Table.Th>Last saved</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>{records.filter((row) => (row.title ?? '').toLowerCase().includes(filter.toLowerCase())).map((row) => <Table.Tr key={row.id}>
            <Table.Td><Button variant="subtle" onClick={() => setSelected(row)}>{row.title ?? `Case ${row.id}`}</Button></Table.Td>
            <Table.Td>{row.status}</Table.Td><Table.Td>{row.updated_at ?? row.created_at}</Table.Td>
          </Table.Tr>)}</Table.Tbody>
        </Table></Table.ScrollContainer>
        {!records.length && <Text>No cases have been created yet.</Text>}
      </>}
  </Stack></Container>;
}

function CaseScreen({ record, onSaved, onBack }: { record: CaseRecord; onSaved: (value: CaseRecord) => void; onBack: () => void }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [title, setTitle] = useState(record.title ?? '');
  const [question, setQuestion] = useState(record.question);
  const [status, setStatus] = useState<'research' | 'watching' | 'closed'>(record.status as 'research' | 'watching' | 'closed');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [document, setDocument] = useState<DocumentView | null>(null);
  const [blockId, setBlockId] = useState<number | null>(null);
  const [quote, setQuote] = useState('');
  const [decision, setDecision] = useState('');
  const [reason, setReason] = useState('');
  const [documentIds, setDocumentIds] = useState<number[]>([]);
  const [scenarioIds, setScenarioIds] = useState<number[]>([]);
  const [evidence, setEvidence] = useState<EvidenceInput[]>([]);
  const [template, setTemplate] = useState<ScenarioRecord | null>(null);
  const [calculatorLoad, setCalculatorLoad] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const evidencePane = useRef<HTMLDivElement>(null);
  async function refresh() { setDetail(await api.caseDetail(record.id)); }
  useEffect(() => { refresh().catch((e) => setError(String(e))); }, []);
  useEffect(() => { evidencePane.current?.querySelector('mark')?.scrollIntoView({ block: 'center' }); }, [document]);
  async function run(operation: () => Promise<void>) {
    setBusy(true); setError(null); setMessage('');
    try { await operation(); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function openDocument(id: number, block: number | null = null) {
    await run(async () => { setDocument(await api.readDocument({ document_id: id, block_id: block })); setBlockId(block); setQuote(''); });
  }
  function toggle(ids: number[], id: number, checked: boolean) { return checked ? [...new Set([...ids, id])] : ids.filter((value) => value !== id); }
  function useEvidence() {
    if (!document?.citation) return;
    setEvidence([...evidence, { document_id: document.id, block_id: blockId, quote: document.citation.quote }]);
    setDocumentIds([...new Set([...documentIds, document.id])]);
    setMessage('The matched passage is attached to your unsaved decision. Add a decision and reason below to save it.');
  }

  return <Stack>
    <Group justify="space-between"><Button variant="subtle" onClick={onBack}>Back to cases</Button>
      <Button variant="default" disabled={busy} onClick={() => run(async () => { setMessage(actionText(await api.exportCase(record.id))); })}>Export case</Button></Group>
    <Feedback error={error} message={message} />
    <Paper withBorder p="lg"><Stack>
      <Title order={2}>{record.title ?? 'Case'}</Title>
      <TextInput label="Case name" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <Select label="Status" value={status} data={['research', 'watching', 'closed']} onChange={(value) => setStatus((value ?? 'research') as typeof status)} />
      <Textarea label="Research question and notes" value={question} onChange={(e) => setQuestion(e.currentTarget.value)} autosize minRows={3} />
      <Button disabled={busy} onClick={() => run(async () => {
        onSaved(await api.updateCase({ case_id: record.id, title, question, status })); setMessage('Case notes saved.');
      })}>Save case notes</Button>
    </Stack></Paper>
    <SummaryPanel caseId={record.id} caseUpdatedAt={record.updated_at} documents={detail?.documents} onDocument={(value) => {
      setDocument(value); setBlockId(null); setQuote('');
    }} />
    <FactsPanel caseId={record.id} documents={detail?.documents} onChanged={refresh} onDocument={(value) => {
      setDocument(value); setBlockId(null); setQuote('');
    }} />
    <QuestionsPanel caseId={record.id} documents={detail?.documents} onDocument={(value) => {
      setDocument(value); setBlockId(null); setQuote('');
    }} />
    <SecImports caseId={record.id} onChanged={refresh} onRead={(id) => openDocument(id)} />
    <Paper withBorder p="lg"><Stack>
      <Group justify="space-between"><Title order={2}>Documents</Title><Button disabled={busy} onClick={() => run(async () => {
        const result = await api.importLocal(record.id); await refresh(); setHits(null); setMessage(actionText(result));
      })}>Import HTML, text or PDF file</Button></Group>
      <Text size="sm">Original files remain saved. Local files do not establish SEC filing metadata or exhibit completeness. The AI summary panel identifies the exact portion reviewed.</Text>
      {detail?.documents.map((row) => <Paper key={row.id} withBorder p="sm"><Group justify="space-between">
        <Stack gap={3}><Text fw={600}>{row.name ?? 'Unnamed document'}</Text>
          <Text size="sm">Version {row.id} · Filing date: {row.filing_date ?? 'unknown'} · Form: {row.form_type ?? 'unknown'}</Text>
          <Text size="sm">{row.processing_error ?? (row.searchable ? 'Saved and searchable' : 'No usable text')}</Text></Stack>
        <Group><Button variant="default" disabled={busy || !row.searchable} onClick={() => openDocument(row.id)}>Read</Button>
          <Button variant="subtle" disabled={busy} onClick={() => run(async () => { setMessage(actionText(await api.openOriginal(row.id))); })}>Original</Button></Group>
      </Group></Paper>)}
      {detail && !detail.documents.length && <Text>No documents saved for this case.</Text>}
      <Group align="end"><TextInput style={{ flex: 1 }} label="Search saved document text" description="Enter a phrase to find in this case." value={query} onChange={(e) => setQuery(e.currentTarget.value)} />
        <Button disabled={busy || !query.trim()} onClick={() => run(async () => { setHits(await api.searchDocuments(record.id, query)); })}>Search</Button></Group>
      {hits?.map((hit) => <Paper key={hit.block_id} withBorder p="sm"><Stack gap="xs">
        <Group><Button variant="subtle" onClick={() => openDocument(hit.document_id, hit.block_id)}>{hit.name ?? 'Document'} · {hit.heading ?? 'Passage'}</Button>
          {hit.partial && <Badge color="yellow">Partial table or passage</Badge>}</Group>
        <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{hit.text}</Text>
      </Stack></Paper>)}
      {hits?.length === 0 && <Text>No matching passages were found.</Text>}
    </Stack></Paper>
    <div id="calculator"><Calculators key={`${record.id}:${calculatorLoad}`} caseId={record.id} template={template}
      onSaved={() => { refresh().catch((e) => setError(String(e))); }} /></div>
    <Title order={2}>Saved scenarios</Title>
    <Accordion>{detail?.scenarios.map((row) => <Accordion.Item value={String(row.id)} key={row.id}>
      <Accordion.Control>{row.name} · {row.kind} · {row.created_at}</Accordion.Control>
      <Accordion.Panel><Stack>
        <Text size="sm">Saved record {row.id}. Later calculations do not change these inputs or results.</Text>
        {row.warning && <Alert color="yellow">{row.warning}</Alert>}
        {Object.entries(row.display).map(([group, values]) => <div key={group}><Text fw={600}>{group}</Text>
          {Object.entries(values).map(([label, value]) => <Text key={label}>{label.replaceAll('_', ' ')}: {value}</Text>)}</div>)}
        <Button variant="default" onClick={() => {
          setTemplate(row); setCalculatorLoad(calculatorLoad + 1);
          window.document.getElementById('calculator')?.scrollIntoView({ block: 'start' });
        }}>Use these inputs</Button>
        <Text size="sm">Opens every saved input and assumption in the calculator. Save the revision as a new record.</Text>
      </Stack></Accordion.Panel>
    </Accordion.Item>)}</Accordion>
    {detail && !detail.scenarios.length && <Text>No scenarios have been saved.</Text>}
    <Paper withBorder p="lg"><Stack>
      <Title order={2}>Record a decision</Title>
      <TextInput label="Decision" value={decision} onChange={(e) => setDecision(e.currentTarget.value)} />
      <Textarea label="Reason, assumptions and unresolved questions" value={reason} onChange={(e) => setReason(e.currentTarget.value)} autosize minRows={3} />
      <Text fw={600}>Documents used</Text>
      {detail?.documents.map((row) => <Checkbox key={row.id} label={`${row.name ?? 'Document'}: version ${row.id}`} checked={documentIds.includes(row.id)}
        onChange={(e) => setDocumentIds(toggle(documentIds, row.id, e.currentTarget.checked))} />)}
      <Text fw={600}>Saved scenarios used</Text>
      {detail?.scenarios.map((row) => <Checkbox key={row.id} label={`${row.name}: saved record ${row.id}`} checked={scenarioIds.includes(row.id)}
        onChange={(e) => setScenarioIds(toggle(scenarioIds, row.id, e.currentTarget.checked))} />)}
      {evidence.map((item, index) => <Group key={index} justify="space-between"><Text size="sm">Quote from version {item.document_id}: {item.quote}</Text>
        <Button variant="subtle" size="xs" onClick={() => setEvidence(evidence.filter((_, i) => i !== index))}>Remove unsaved quote</Button></Group>)}
      <Text size="sm">Use “Attach passage to decision” in the document reader to preserve a matched quote. A match confirms the text occurs; it does not confirm its interpretation.</Text>
      <Button disabled={busy || !decision.trim() || !reason.trim()} onClick={() => run(async () => {
        await api.saveDecision({ case_id: record.id, decision, reason, document_ids: documentIds, scenario_ids: scenarioIds, evidence });
        setDecision(''); setReason(''); setDocumentIds([]); setScenarioIds([]); setEvidence([]); await refresh(); setMessage('Decision and its references saved.');
      })}>Save decision</Button>
    </Stack></Paper>
    <Title order={2}>Decision history</Title>
    {detail?.decisions.map((row) => <Paper key={row.id} withBorder p="lg"><Stack gap="xs">
      <Text fw={600}>{row.decision}</Text><Text size="sm">{row.created_at}</Text>
      <Text style={{ whiteSpace: 'pre-wrap' }}>{row.reason}</Text>
      <Text size="sm">Document versions: {row.document_ids.join(', ') || 'none'}. Saved scenarios: {row.scenario_ids.join(', ') || 'none'}.</Text>
      {row.evidence.map((citation, index) => <Button key={index} variant="subtle" style={{ height: 'auto', whiteSpace: 'normal' }} onClick={() => run(async () => {
        setDocument(await api.readSavedEvidence(row.id, index)); setBlockId(null); setQuote('');
      })}>{citation.status}: {citation.quote}</Button>)}
    </Stack></Paper>)}
    {detail && !detail.decisions.length && <Text>No decisions have been saved.</Text>}
    <Drawer opened={document !== null} onClose={() => setDocument(null)} position="right" size="xl" title={document?.name ?? 'Saved document'}
      onEnterTransitionEnd={() => evidencePane.current?.querySelector('mark')?.scrollIntoView({ block: 'center' })}>
      {document && <Stack>
        <Text size="sm">Filing date: {document.filing_date ?? 'unknown'} · Form: {document.form_type ?? 'unknown'} · Text version {document.id}</Text>
        <Button variant="default" onClick={() => run(async () => { setMessage(actionText(await api.openOriginal(document.id))); })}>Open original externally</Button>
        <Textarea label="Quote to locate in this document" description={blockId ? 'Matching is restricted to the selected search passage.' : 'A repeated quote needs more context or a selected search passage.'}
          value={quote} onChange={(e) => setQuote(e.currentTarget.value)} />
        <Button disabled={busy || !quote.trim()} onClick={() => run(async () => { setDocument(await api.readDocument({ document_id: document.id, block_id: blockId, quote })); })}>Match quote</Button>
        {error && <Alert color="red" role="alert">{error}</Alert>}
        {message && <Text role="status">{message}</Text>}
        {document.citation && <><Badge color="blue">Quote matched</Badge><Text size="sm">This confirms the text occurs, not that its interpretation is correct.</Text>
          {quote.trim() && <Button onClick={useEvidence}>Attach passage to decision</Button>}</>}
        <Divider />
        <div className="evidence" ref={evidencePane} dangerouslySetInnerHTML={{ __html: document.html }} />
      </Stack>}
    </Drawer>
  </Stack>;
}

function Settings({ state, refresh }: { state: AppState; refresh: () => Promise<void> }) {
  const [search, setSearch] = useState<SearchResult | null>(null);
  const [note, setNote] = useState('');
  const [noteReady, setNoteReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    api.readSearchCheck().then(setSearch).catch((e) => setError(String(e)));
    api.readText().then((r) => { setNote(r.text ?? ''); setNoteReady(true); }).catch((e) => setError(String(e)));
  }, []);
  async function run(operation: () => Promise<ActionResult>) {
    setBusy(true); setError(null); setMessage('Working…');
    try { const result = await operation(); await refresh(); setMessage(actionText(result)); }
    catch (e) { setError(String(e)); setMessage(''); } finally { setBusy(false); }
  }
  return <Stack><Title order={2}>Settings</Title><Feedback error={error} message={message} />
    <Paper withBorder p="lg"><Stack><Title order={3}>Research data</Title><Text>{state.data_folder}</Text>
      <Button variant="default" disabled={busy} onClick={() => run(api.openDataFolder)}>Open data folder</Button>
      <Text>Search available: {search?.available === true ? 'yes' : search?.available === false ? 'no' : 'unknown'}</Text>
      <Text size="sm">{search?.detail} {search?.checked_at && `Checked ${search.checked_at}`}</Text>
      <Text size="sm">Python {state.python_version}; project target: Python 3.13.</Text>
    </Stack></Paper>
    <SubscriptionSettings />
    <SecContactSettings />
    <Paper withBorder p="lg"><Stack><Title order={3}>Backup and restore</Title>
      <Text>Backups include the database and every referenced original and cleaned document. A backup is complete only after its files are verified.</Text>
      <Text>Second backup folder: {state.second_backup_folder ?? 'not selected; a second-location backup is not verified'}</Text>
      <Group><Button disabled={busy} onClick={() => run(api.createBackup)}>Create backup</Button>
        <Button variant="default" disabled={busy} onClick={() => run(api.chooseSecondBackup)}>Choose second backup folder</Button></Group>
      <Text fw={600}>Verified complete local backups</Text>
      {state.backup_names === null ? <Text>Available backups could not be checked.</Text> : state.backup_names.length ? state.backup_names.map((name) => <Text size="sm" key={name}>{name}</Text>) : <Text>No complete local backups are available.</Text>}
      {state.backup_warnings.map((warning) => <Alert color="yellow" key={warning}>{warning}</Alert>)}
      <Divider /><Text>To test restoration safely, first select a complete snapshot folder, then an empty destination folder. Your current research stays open and unchanged.</Text>
      <Button variant="default" disabled={busy} onClick={() => run(() => api.restoreBackup(true))}>Restore a copy into an empty folder</Button>
      <Text size="sm">Manual restoration acceptance and a backup on a second disk remain for you to check. Credentials are not included in backups.</Text>
    </Stack></Paper>
    <Paper withBorder p="lg"><Stack><Title order={3}>Saved note</Title>
      <Textarea label="General note" value={note} disabled={!noteReady || busy} onChange={(e) => setNote(e.currentTarget.value)} autosize minRows={3} />
      <Button disabled={!noteReady || busy} onClick={() => run(async () => {
        await api.saveText(note); return { message: 'Note saved.', path: null, warning: null, cancelled: false, error: null };
      })}>Save note</Button></Stack></Paper>
  </Stack>;
}

function SecImports({ caseId, onChanged, onRead }: {
  caseId: number; onChanged: () => Promise<void>; onRead: (id: number) => Promise<void>;
}) {
  const [url, setUrl] = useState('');
  const [imports, setImports] = useState<SecImport[] | null>(null);
  const [active, setActive] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let disposed = false;
    api.secImportStatus(caseId).then((result) => {
      if (!disposed) { setImports(result.imports); setActive(result.active); }
    }).catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [caseId]);
  useEffect(() => {
    if (!active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.secImportStatus(caseId);
        if (disposed) return;
        setImports(result.imports); setActive(result.active); setError(null);
        if (!result.active) await onChanged();
        if (result.active && !disposed) timer = window.setTimeout(poll, 1000);
      } catch (reason) {
        if (!disposed) { setError(String(reason)); setActive(false); }
      }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [caseId, active]);
  async function request(operation: () => Promise<SecImportResult>) {
    setRequesting(true); setError(null);
    try {
      const result = await operation();
      setImports(result.imports); setActive(result.active);
      if (!result.active) await onChanged();
    } catch (reason) { setError(String(reason)); }
    finally { setRequesting(false); }
  }
  return <Paper withBorder p="lg"><Stack>
    <Title order={2}>Import a SEC filing</Title>
    <Text size="sm">Paste the SEC filing page or a document URL. The app checks the filing's document list and saves the main document and exhibits within its download limits.</Text>
    <TextInput label="SEC filing or document URL" value={url} onChange={(event) => setUrl(event.currentTarget.value)}
      disabled={requesting || active} onKeyDown={(event) => {
        if (event.key === 'Enter' && imports !== null && !requesting && !active && url.trim()) {
          event.preventDefault(); request(() => api.secImport(caseId, url.trim()));
        }
      }} />
    <Group><Button loading={requesting} disabled={active || imports === null || !url.trim()}
      onClick={() => request(() => api.secImport(caseId, url.trim()))}>Import filing</Button>
      {active && <Text role="status">Import is active. Document statuses update once a second.</Text>}</Group>
    {error && <><Alert color="red" role="alert">{error}</Alert>
      <Button variant="default" disabled={requesting} onClick={() => request(() => api.secImportStatus(caseId))}>Retry status check</Button></>}
    {imports === null && !error && <Text role="status">Reading saved filing imports…</Text>}
    {imports?.length === 0 && <Text>No SEC filings have been imported into this case.</Text>}
    {imports?.map((filing) => <Paper key={filing.id} withBorder p="md"><Stack gap="sm">
      <Group justify="space-between"><Title order={3}>{filing.form_type || 'Form unknown'} · {filing.accession_number || 'Accession unknown'}</Title>
        <Badge color={filing.status === 'complete' ? 'green' : ['failed', 'interrupted'].includes(filing.status) ? 'red' : 'yellow'}>{filing.status}</Badge></Group>
      <Text size="sm">CIK: {filing.cik || 'unknown'} · Filing date: {filing.filing_date ?? 'unknown'} · Checked: {filing.checked_at || 'unknown'}</Text>
      <Text size="sm" style={{ overflowWrap: 'anywhere' }}>Filing URL: {filing.filing_url || 'unknown'}</Text>
      {filing.request_url !== filing.filing_url && <Text size="sm" style={{ overflowWrap: 'anywhere' }}>Requested URL: {filing.request_url}</Text>}
      <Text role="status" style={{ whiteSpace: 'pre-wrap' }}>{filing.detail}</Text>
      <Text size="sm">Fetched means downloaded, not analysed. Saving the registration cover does not establish that the complete information statement is present.</Text>
      {filing.selected_document_url ? <Text size="sm" style={{ overflowWrap: 'anywhere' }}>Selected information statement: {filing.selected_document_url}. Read it to confirm its completeness.</Text>
        : <Alert color="yellow">No information statement is selected. Choose a suitable listed document after checking its contents.</Alert>}
      {filing.items.length === 0 && <Text>No filing document list has been saved.</Text>}
      {filing.items.length > 0 && <Accordion><Accordion.Item value="documents">
      <Accordion.Control>Filing documents and exhibits ({filing.items.length})</Accordion.Control>
      <Accordion.Panel><Stack>
      {filing.items.map((item) => {
        const selected = item.url === filing.selected_document_url;
        const supported = /\.(html?|txt)(?:[?#]|$)/i.test(item.url);
        return <Paper key={item.url} withBorder p="sm"><Stack gap="xs">
          <Group justify="space-between"><Text fw={600}>{item.name}</Text><Badge variant="light">{item.status}</Badge></Group>
          <Text size="sm">Type: {item.document_type ?? 'unknown'} · Size: {item.size === null ? 'unknown' : `${item.size} bytes`}</Text>
          <Text size="sm" style={{ overflowWrap: 'anywhere' }}>{item.url}</Text>
          {item.detail && <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{item.detail}</Text>}
          <Group>
            {item.status === 'fetched' && item.document_id !== null && <Button variant="default" onClick={() => onRead(item.document_id!)}>Read saved document</Button>}
            {supported && <Button variant="default" disabled={active || requesting || (selected && item.status === 'fetched')}
              onClick={() => request(() => api.secSelectStatement(caseId, filing.id, item.url))}>
              {selected ? item.status === 'fetched' ? 'Selected statement' : 'Retry selected statement' : 'Use as information statement'}
            </Button>}
          </Group>
        </Stack></Paper>;
      })}
      </Stack></Accordion.Panel>
      </Accordion.Item></Accordion>}
    </Stack></Paper>)}
  </Stack></Paper>;
}

function SecContactSettings() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    api.secContact().then((contact) => {
      setName(contact.name ?? ''); setEmail(contact.email ?? ''); setReady(true);
    }).catch((reason) => setError(String(reason)));
  }, []);
  async function save() {
    setSaving(true); setError(null); setMessage('');
    try {
      const contact = await api.saveSecContact(name.trim(), email.trim());
      setName(contact.name ?? ''); setEmail(contact.email ?? ''); setMessage('SEC contact saved.');
    } catch (reason) { setError(String(reason)); }
    finally { setSaving(false); }
  }
  return <Paper withBorder p="lg"><Stack><Title order={3}>SEC contact</Title>
    <Text size="sm">SEC requests identify you with this name and email address.</Text>
    <TextInput label="SEC contact name" value={name} disabled={!ready || saving} onChange={(event) => setName(event.currentTarget.value)} />
    <TextInput label="SEC contact email" type="email" value={email} disabled={!ready || saving} onChange={(event) => setEmail(event.currentTarget.value)} />
    <Button loading={saving} disabled={!ready || !name.trim() || !email.trim()} onClick={save}>Save SEC contact</Button>
    <Feedback error={error} message={message} />
  </Stack></Paper>;
}
