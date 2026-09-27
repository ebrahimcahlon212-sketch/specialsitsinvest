import { useEffect, useRef, useState } from 'react';
import { Accordion, Alert, Badge, Button, Group, MultiSelect, Paper, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import * as api from './api';
import type { DocumentSummary, DocumentView, ResearchState, ReviewPlan } from './api';

const sections: Record<string, string> = {
  company: 'The business', event: 'The event', conditions: 'Conditions and completion', dates: 'Key dates',
  financials: 'Finances', risks: 'Risks', opportunity: 'The possible opportunity', unknowns: 'What remains unclear',
};

function Details({ value }: { value: unknown }) {
  return <Text component="pre" size="xs" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
    {value == null ? 'Unknown: no information was returned.' : JSON.stringify(value, null, 2)}
  </Text>;
}

export default function ResearchPanel({ caseId, caseUpdatedAt, documents, onChanged, onDocument }: {
  caseId: number; caseUpdatedAt?: string | null; documents?: DocumentSummary[];
  onChanged: () => Promise<void> | void; onDocument: (value: DocumentView) => void;
}) {
  const [state, setState] = useState<ResearchState | null>(null);
  const [url, setUrl] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [plan, setPlan] = useState<ReviewPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  const selectionChanged = useRef(false);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  useEffect(() => {
    setState(null); setPlan(null); setSelected([]); setError(null); setUrl(''); selectionChanged.current = false;
  }, [caseId]);
  useEffect(() => {
    let disposed = false;
    setPlan(null);
    api.researchStatus(caseId).then((result) => {
      if (disposed) return;
      setState(result); setUrl((value) => value || result.collection?.url || '');
      if (result.selected_document_ids.length) setSelected((value) => value.length || selectionChanged.current ? value : result.selected_document_ids.map(String));
    }).catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [caseId, caseUpdatedAt, documents]);
  useEffect(() => {
    if (!state || selected.length || selectionChanged.current) return;
    const latest = new Map<string, DocumentSummary>();
    (documents ?? []).forEach((row) => {
      if (!latest.has(row.logical_document_id) || latest.get(row.logical_document_id)!.id < row.id) latest.set(row.logical_document_id, row);
    });
    setSelected([...latest.values()].filter((row) => row.searchable).slice(0, 12).map((row) => String(row.id)));
  }, [state, documents, selected.length]);
  useEffect(() => {
    if (!state?.active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.researchStatus(caseId);
        if (disposed) return;
        setState(result); setError(null);
        if (result.active) timer = window.setTimeout(poll, 1000);
        else {
          setPlan(null);
          if (result.selected_document_ids.length) setSelected(result.selected_document_ids.map(String));
          await changed.current();
        }
      } catch (reason) {
        if (!disposed) setError(`Progress could not be checked. Work may still be active. ${String(reason)}`);
      }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [caseId, state?.active, pollRevision]);
  async function request(operation: () => Promise<ResearchState>) {
    setBusy(true); setError(null);
    try {
      const result = await operation(); setState(result); setPlan(result.active ? result.plan : null);
      setPollRevision((value) => value + 1);
      if (!result.active) await changed.current();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function preview() {
    setBusy(true); setError(null); setPlan(null);
    try { setPlan(await api.prepareResearch(caseId, selected.map(Number))); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function evidence(index: number) {
    if (!state?.report) return;
    setBusy(true); setError(null);
    try { onDocument(await api.readResearchEvidence(state.report.id, index)); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  const locked = busy || !!state?.active;
  const report = state?.report;
  const choices = (documents ?? []).filter((row) => row.searchable).map((row) => ({
    value: String(row.id), label: `${row.name ?? 'Document'}: version ${row.id}`,
  }));
  selected.forEach((id) => {
    if (!choices.some((choice) => choice.value === id)) choices.push({ value: id, label: `Saved document version ${id}` });
  });
  return <Paper withBorder p="lg"><Stack>
    <Title order={2}>Investigate case</Title>
    <Text size="sm">Find documents linked from an official company or deal page, then review the selected saved text in bounded batches. Missing documents and unfinished batches remain visible.</Text>
    <TextInput label="Official company or deal URL" placeholder="https://..." maxLength={2000} value={url}
      disabled={locked} onChange={(event) => setUrl(event.currentTarget.value)} />
    <Group><Button variant="default" disabled={locked || !url.trim() || !state}
      onClick={() => request(() => api.collectResearchSources(caseId, url.trim()))}>Find documents</Button>
      {state?.active && <Button variant="default" disabled={busy} onClick={() => request(() => api.cancelResearch(caseId))}>Cancel</Button>}
    </Group>
    <Text size="sm">This checks a limited set of links on the supplied site. It cannot guarantee that every relevant or latest document has been found. Access terms and sign-in pages need your action; they are not accepted automatically.</Text>
    {state?.collection && <Accordion defaultValue="collection"><Accordion.Item value="collection">
      <Accordion.Control>Document collection and gaps</Accordion.Control><Accordion.Panel><Stack gap="sm">
        <Text size="sm">Checked {state.collection.checked_at} · {state.collection.request_count} request(s){state.collection.cancelled && ' · collection cancelled'}</Text>
        {state.collection.documents.map((row, index) => <Stack key={`${row.document_id}-${index}`} gap={2}>
          <Text size="sm" fw={600}>{row.name ?? 'Document'} · version {row.document_id} · {row.status}</Text>
          <Text size="xs" style={{ overflowWrap: 'anywhere' }}>{row.source_url}</Text>
        </Stack>)}
        {!state.collection.documents.length && <Text size="sm">No usable documents were saved by this collection.</Text>}
        {state.collection.gaps.map((gap, index) => <Alert color="yellow" key={index}>{gap}</Alert>)}
      </Stack></Accordion.Panel></Accordion.Item></Accordion>}
    <MultiSelect label="Documents for this investigation" description="Choose up to 12 saved documents, using one version of each. Check the selection before previewing."
      data={choices} value={selected} maxValues={12} disabled={!state || locked} searchable
      onChange={(values) => { selectionChanged.current = true; setSelected(values); setPlan(null); }} />
    <Text size="sm">{selected.length} saved version(s) selected. Unselected documents are not reviewed.</Text>
    <Group><Button variant="default" loading={busy} disabled={!state || locked || !selected.length} onClick={preview}>Preview full review</Button>
      {state?.active && <Text role="status">{state.detail ?? 'Work is active.'}</Text>}
    </Group>
    {!state?.active && state?.detail && <Text role="status">{state.detail}</Text>}
    {(error || state?.error) && <Alert color="red" role="alert">{error ?? state?.error}</Alert>}
    {(error || state?.error) && <Button variant="default" disabled={busy} onClick={() => request(() => api.researchStatus(caseId))}>Check investigation status</Button>}
    {!state && !error && <Text role="status">Reading saved investigation...</Text>}
    {state?.plan && (!plan || state.active) && <Accordion><Accordion.Item value="progress"><Accordion.Control>Last started review: completed and unfinished batches</Accordion.Control>
      <Accordion.Panel><Stack gap="xs">
        <Text size="sm">These are saved progress records. Use Preview full review to check the current selection before continuing.</Text>
        {state.plan.batches.map((batch) => <Text size="sm" key={batch.index}>
          Batch {batch.index + 1} · version {batch.document_id} · characters {(batch.start_offset + 1).toLocaleString()} to {batch.end_offset.toLocaleString()} · {batch.status}
        </Text>)}
      </Stack></Accordion.Panel></Accordion.Item></Accordion>}
    {plan && <Paper withBorder p="md"><Stack gap="sm">
      <Title order={3}>Review plan</Title>
      <Text>{plan.sources.length} document(s) · {plan.total_chars.toLocaleString()} searchable characters · {plan.batch_count} batches</Text>
      <Text>{plan.cached_batches} completed batches available to reuse · at most {plan.max_new_requests} new model requests</Text>
      <Text size="sm">ChatGPT subscription · {plan.model} · {plan.effort} reasoning · up to {plan.deadline_seconds} seconds per new request, plus connection time. No GBP charge is inferred from subscription usage.</Text>
      {plan.warnings.map((warning, index) => <Alert color="yellow" key={index}>{warning}</Alert>)}
      {plan.blockers.map((blocker, index) => <Alert color="red" key={index}>{blocker}</Alert>)}
      <Accordion><Accordion.Item value="batches"><Accordion.Control>Document versions and batch coverage</Accordion.Control>
        <Accordion.Panel><Stack gap="sm">
          {plan.sources.map((source) => <Text size="sm" key={source.document_id}>{source.name ?? 'Document'} · version {source.document_id} · {source.total_chars.toLocaleString()} characters</Text>)}
          {plan.batches.map((batch) => <Text size="sm" key={batch.index}>
            Batch {batch.index + 1} · document version {batch.document_id} · characters {(batch.start_offset + 1).toLocaleString()} to {batch.end_offset.toLocaleString()} · {batch.cached ? 'completed result available' : batch.status}
          </Text>)}
        </Stack></Accordion.Panel></Accordion.Item></Accordion>
      <Button disabled={locked || !plan.allowed} onClick={() => request(() => api.startResearch(caseId, selected.map(Number), plan.plan_key))}>
        {plan.cached_batches > 0 ? 'Continue review' : 'Review documents'}
      </Button>
      <Text size="sm">Only this selection is reviewed. Completed matching batches are reused. There is no paid API fallback. Cancel stops further batches; interrupted requests are not restarted automatically and their final usage can remain unknown.</Text>
    </Stack></Paper>}
    {report && <Paper withBorder p="md"><Stack>
      <Group justify="space-between"><Title order={3}>Saved investigation</Title><Badge>Record {report.id}</Badge></Group>
      <Text size="sm">Saved {report.created_at} · {report.model} · {report.effort} reasoning · prompt {report.prompt_version}</Text>
      {report.stale && <Alert color="yellow" title="Out of date">{report.stale_reasons.join(' ')} Earlier research remains saved.</Alert>}
      <Table.ScrollContainer minWidth={550}><Table><Table.Thead><Table.Tr>
        <Table.Th>Saved document</Table.Th><Table.Th>Text in completed batches</Table.Th><Table.Th>Status</Table.Th>
      </Table.Tr></Table.Thead><Table.Tbody>{report.coverage.map((row) => <Table.Tr key={row.document_id}>
        <Table.Td>{row.name ?? 'Document'} · version {row.document_id}</Table.Td>
        <Table.Td>{row.reviewed_chars.toLocaleString()} of {row.total_chars.toLocaleString()} characters</Table.Td>
        <Table.Td>{row.status}</Table.Td>
      </Table.Tr>)}</Table.Tbody></Table></Table.ScrollContainer>
      <Text size="sm">Coverage means text supplied to completed review batches. It does not establish that every source is present, that extraction preserved every table, or that the interpretation is correct.</Text>
      {report.warnings.map((warning, index) => <Alert color="yellow" key={index}>{warning}</Alert>)}
      <Text size="sm">“Quote matched” confirms that the quoted words occur in that saved document version. It does not verify the claim or the separately labelled AI interpretation. Financial calculations and your investment decision remain separate.</Text>
      {[...new Set([...Object.keys(sections), ...report.items.map((item) => item.section)])].map((section) => <Stack key={section} gap="sm">
        <Title order={4}>{sections[section] ?? section}</Title>
        {!report.items.some((item) => item.section === section) && <Text size="sm">Unresolved: no finding was produced for this section.</Text>}
        {report.items.map((item, index) => item.section === section && <Paper key={index} withBorder p="sm"><Stack gap="xs">
          <Text>{item.text}</Text>
          <Group gap="xs">{item.citation && <Badge color="blue">Quote matched</Badge>}
            {item.status !== 'quote matched' && <Badge color="yellow">{item.status === 'assumption' ? 'Assumption' : 'Unresolved'}</Badge>}</Group>
          {item.detail && <Text size="sm">{item.detail}</Text>}
          {(item.quote || item.citation) && <Accordion><Accordion.Item value="evidence"><Accordion.Control>{item.citation ? 'Supporting quotation' : 'Unverified quotation'}</Accordion.Control>
            <Accordion.Panel>{item.citation ? <Button variant="subtle" disabled={busy} h="auto" py="xs" onClick={() => evidence(index)}
              styles={{ label: { whiteSpace: 'normal', textAlign: 'left', lineHeight: 1.5 } }}>
              Open quoted passage · version {item.citation.document_id}: “{item.citation.quote}”
            </Button> : <Text size="sm">{item.quote}</Text>}</Accordion.Panel>
          </Accordion.Item></Accordion>}
          {item.ai_comment && <Paper withBorder p="sm"><Text size="sm" fw={600}>AI interpretation</Text><Text size="sm">{item.ai_comment}</Text></Paper>}
        </Stack></Paper>)}
      </Stack>)}
      <Accordion><Accordion.Item value="usage"><Accordion.Control>Reported subscription usage</Accordion.Control>
        <Accordion.Panel><Details value={report.usage.length ? report.usage : null} /></Accordion.Panel>
      </Accordion.Item></Accordion>
    </Stack></Paper>}
    {state && !report && <Text size="sm">No investigation report has been saved for this case yet.</Text>}
    {!!state?.runs.length && <Accordion><Accordion.Item value="runs"><Accordion.Control>Investigation request history</Accordion.Control>
      <Accordion.Panel><Stack>{state.runs.map((run) => <Paper key={run.id} withBorder p="sm"><Stack gap="xs">
        <Group><Text fw={600}>Request {run.id}</Text><Badge>{run.status}</Badge></Group>
        <Text size="sm">Started {run.created_at}{run.completed_at && ` · finished ${run.completed_at}`}</Text>
        <Text size="sm">{run.detail} · reported retry notifications: {run.retry_count}</Text>
        {run.usage_uncertain && <Text size="sm" c="orange">Final usage is unknown; reported values may be partial.</Text>}
        <Details value={run.usage} />
      </Stack></Paper>)}</Stack></Accordion.Panel>
    </Accordion.Item></Accordion>}
  </Stack></Paper>;
}
