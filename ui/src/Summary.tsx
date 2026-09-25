import { useEffect, useState } from 'react';
import { Accordion, Alert, Badge, Button, Group, MultiSelect, Paper, Stack, Text, Title } from '@mantine/core';
import * as api from './api';
import type { DocumentSummary, DocumentView, SummarySource, SummaryState, SummaryStatement, SubscriptionState } from './api';

const sections = [
  ['company', 'The business'], ['event', 'The event'], ['what_must_happen', 'Conditions and completion'],
  ['dates', 'Key dates'], ['unknowns', 'What remains unclear'], ['risks', 'Risks'],
] as const;

function Usage({ value, uncertain = false }: { value: Record<string, unknown> | null; uncertain?: boolean }) {
  const total = value?.total && typeof value.total === 'object' ? value.total as Record<string, unknown> : null;
  const limits = value?.rateLimits && typeof value.rateLimits === 'object' ? value.rateLimits as Record<string, unknown> : null;
  return <Stack gap="xs">
    {uncertain && <Text size="sm" c="orange">Final usage is uncertain. Any reported values may be partial.</Text>}
    {total && <Text size="sm">Reported tokens: input {typeof total.inputTokens === 'number' ? total.inputTokens.toLocaleString() : 'unknown'} · output {typeof total.outputTokens === 'number' ? total.outputTokens.toLocaleString() : 'unknown'} · cached input {typeof total.cachedInputTokens === 'number' ? total.cachedInputTokens.toLocaleString() : 'unknown'}</Text>}
    {limits && ['primary', 'secondary'].map((name) => {
      const allowanceWindow = limits[name];
      if (!allowanceWindow || typeof allowanceWindow !== 'object') return null;
      const values = allowanceWindow as Record<string, unknown>;
      return <Text size="sm" key={name}>Subscription window {typeof values.windowDurationMins === 'number' ? `(${values.windowDurationMins.toLocaleString()} minutes)` : '(duration unknown)'}: {typeof values.usedPercent === 'number' ? `${values.usedPercent}% used` : 'usage unknown'} · resets {typeof values.resetsAt === 'number' ? new Date(values.resetsAt * 1000).toLocaleString() : 'unknown'}</Text>;
    })}
    {value === null ? <Text size="sm">Usage: unknown; no usage information was returned.</Text> : <Accordion>
      <Accordion.Item value="usage"><Accordion.Control>Reported usage details</Accordion.Control>
        <Accordion.Panel><Text component="pre" size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {JSON.stringify(value, null, 2)}
        </Text></Accordion.Panel></Accordion.Item>
    </Accordion>}
  </Stack>;
}

function Source({ source, reviewed = false, legacyRange = false }: { source: SummarySource; reviewed?: boolean; legacyRange?: boolean }) {
  const passages = source.passages ?? [];
  return <Stack gap={3}>
    <Text size="sm">{source.name ?? 'Document'} · document version {source.document_id}</Text>
    <Text size="sm">Filing date: {source.filing_date ?? 'unknown'} · form: {source.form_type ?? 'unknown'} · {source.total_chars.toLocaleString()} searchable characters</Text>
    {reviewed && (legacyRange
      ? <Text size="sm">Supplied characters {(source.start_offset + 1).toLocaleString()}–{source.end_offset.toLocaleString()} of this saved version.</Text>
      : <Text size="sm">Supplied {(source.supplied_chars ?? passages.reduce((total, passage) => total + passage.end_offset - passage.start_offset, 0)).toLocaleString()} characters in {passages.length} passage(s).</Text>)}
    <Accordion><Accordion.Item value="version"><Accordion.Control>{reviewed ? 'Supplied passages and source identity' : 'Selected source identity'}</Accordion.Control>
      <Accordion.Panel><Stack gap="sm">
        <Text size="xs" style={{ overflowWrap: 'anywhere' }}>Original SHA-256: {source.original_sha256}<br />Text hash: {source.text_hash}<br />Cleaner: {source.cleaner_version}</Text>
        {source.source_url && <Text size="sm" style={{ overflowWrap: 'anywhere' }}>Source address: {source.source_url}</Text>}
        {(source.warnings ?? []).map((warning, index) => <Text size="sm" c="orange" key={index}>{warning}</Text>)}
        {reviewed && passages.map((passage) => <Paper key={passage.id} withBorder p="sm"><Stack gap="xs">
          <Text fw={600}>{passage.heading ?? 'Source passage'} · passage {passage.id}</Text>
          <Text size="sm">Characters {(passage.start_offset + 1).toLocaleString()}–{passage.end_offset.toLocaleString()} · document version {source.document_id}</Text>
          {passage.partial && <Badge color="yellow">Partial passage or table</Badge>}
          <Text size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{passage.text}</Text>
        </Stack></Paper>)}
      </Stack></Accordion.Panel>
    </Accordion.Item></Accordion>
  </Stack>;
}

function Statement({ value, onEvidence, busy }: { value: SummaryStatement; onEvidence: () => void; busy: boolean }) {
  const matched = value.citation !== null;
  return <Stack gap="xs">
    <Text>{value.text}</Text>
    <Group gap="xs">
      {value.status !== 'quote matched' && <Badge color="yellow">{value.status === 'assumption' ? 'Assumption' : matched ? 'Unresolved' : 'Unresolved: unsupported'}</Badge>}
      {matched && <Badge color="blue">Quote matched</Badge>}
    </Group>
    {value.detail && <Text size="sm">{value.detail}</Text>}
    {(matched || value.quote) && <Accordion><Accordion.Item value="quote"><Accordion.Control>{matched ? 'Supporting quotation' : 'Unverified quotation'}</Accordion.Control>
      <Accordion.Panel>{matched ? <Stack gap="xs">
        <Text size="sm">Document version {value.citation!.document_id}</Text>
        <Button variant="subtle" disabled={busy} onClick={onEvidence} h="auto" py="xs"
          styles={{ label: { whiteSpace: 'normal', textAlign: 'left', lineHeight: 1.5 } }}>
          Open quoted passage: “{value.citation!.quote}”
        </Button>
      </Stack> : <Text size="sm">Unverified quote: “{value.quote}”</Text>}</Accordion.Panel>
    </Accordion.Item></Accordion>}
    {value.ai_comment && <Paper withBorder p="sm"><Stack gap="xs">
      <Text size="sm" fw={600}>AI interpretation</Text>
      <Text size="sm">{value.ai_comment}</Text>
      <Text size="xs" c="dimmed">Commentary for your review. The quotation check does not verify this interpretation.</Text>
    </Stack></Paper>}
  </Stack>;
}

export default function SummaryPanel({ caseId, caseUpdatedAt, documents, onDocument }: {
  caseId: number; caseUpdatedAt: string | null; documents: DocumentSummary[] | undefined; onDocument: (value: DocumentView) => void;
}) {
  const [state, setState] = useState<SummaryState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    api.summaryStatus(caseId).then((result) => { if (!disposed) setState(result); })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [caseId, caseUpdatedAt, documents]);
  useEffect(() => {
    if (!state?.active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.summaryStatus(caseId);
        if (disposed) return;
        setState(result); setError(null);
        if (result.active) timer = window.setTimeout(poll, 1000);
      } catch (reason) {
        if (!disposed) setError(`Progress could not be checked. The request may still be active. ${String(reason)}`);
      }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [caseId, state?.active, pollRevision]);
  async function request(operation: () => Promise<SummaryState>) {
    setBusy(true); setError(null);
    try { setState(await operation()); setPollRevision((value) => value + 1); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function evidence(index: number) {
    if (!state?.summary) return;
    setBusy(true); setError(null);
    try { onDocument(await api.readSummaryEvidence(state.summary.id, index)); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  const summary = state?.summary;
  const selectedIds = state?.selected_document_ids.length ? state.selected_document_ids : state?.selected_document_id == null ? [] : [state.selected_document_id];
  const selectedSources = state?.sources.length ? state.sources : state?.source ? [state.source] : [];
  const savedSources = summary?.sources?.length ? summary.sources : summary ? [summary.source] : [];
  const choices = (documents ?? []).filter((row) => row.searchable).map((row) => ({
    value: String(row.id), label: `${row.name ?? 'Document'}: version ${row.id}`,
  }));
  selectedSources.forEach((source) => {
    if (!choices.some((choice) => choice.value === String(source.document_id))) {
      choices.push({ value: String(source.document_id), label: `${source.name ?? 'Document'}: version ${source.document_id}` });
    }
  });
  return <Paper withBorder p="lg"><Stack>
    <Title order={2}>Case briefing</Title>
    <Text size="sm">Build a plain-English briefing from selected saved documents, with supporting quotations and separately labelled AI interpretation.</Text>
    {state && <Text size="sm">Uses your ChatGPT subscription · {state.model} · {state.effort} reasoning</Text>}
    <MultiSelect label="Documents for this briefing" description="Select up to six documents, using one version of each."
      placeholder="Select saved, searchable documents" maxValues={6} data={choices} value={selectedIds.map(String)}
      disabled={!state || busy || state.active} onChange={(values) => request(() => api.setSummarySource(caseId, values.map(Number)))} />
    {selectedSources.map((source) => <Source key={source.document_id} source={source} />)}
    {!!state?.warnings.length && <Alert color="yellow" title="Source limitations"><Stack gap="xs">
      {state.warnings.map((warning, index) => <Text size="sm" key={index}>{warning}</Text>)}
    </Stack></Alert>}
    {documents && choices.length === 0 && <Text>Import usable HTML, text or PDF documents before generating a briefing.</Text>}
    <Text size="sm">Only selected passages will be supplied. The saved briefing lists the exact document versions and ranges used; it does not imply that every page was reviewed.</Text>
    <Text size="sm">OpenAI receives those passages, your saved case notes, and any owner-checked or corrected facts. Notes are supplied as unverified context; owner facts remain separate from source evidence. The model process has broad read-only filesystem access, with supported optional tools and connectors disabled. This is not a guarantee that no tool can execute.</Text>
    <Group><Button loading={busy} disabled={!state || !selectedIds.length || state.active}
      onClick={() => request(() => api.generateSummary(caseId, selectedIds))}>
      {summary ? 'Refresh case briefing' : 'Generate case briefing'}
    </Button>
      {state?.active && <Button variant="default" disabled={busy} onClick={() => request(() => api.cancelSummary(caseId))}>Cancel</Button>}
    </Group>
    <Text size="sm">An unchanged completed request reuses its saved result. A new request uses subscription allowance; it never switches to paid API access. A cancelled or interrupted request is not restarted automatically.</Text>
    {state && <Text size="sm">A new request allows up to 30 seconds to connect and {state.deadline_seconds} seconds to generate.</Text>}
    {state?.active && <Text role="status">{state.detail ?? 'Briefing request is active. Progress updates once a second.'}</Text>}
    {!state?.active && state?.detail && <Text role="status">{state.detail}</Text>}
    {(error || state?.error) && <Alert color="red" role="alert">{error ?? state?.error}</Alert>}
    {(error || state?.error) && <Button variant="default" disabled={busy} onClick={() => request(() => api.summaryStatus(caseId))}>Check briefing status</Button>}
    {!state && !error && <Text role="status">Reading saved briefing…</Text>}
    {summary && <Paper withBorder p="md"><Stack>
      <Group justify="space-between"><Title order={3}>Saved AI briefing</Title><Badge>Record {summary.id}</Badge></Group>
      <Text size="sm">Saved {summary.created_at} · {summary.model}{summary.effort && ` · ${summary.effort} reasoning`} · prompt {summary.prompt_version}</Text>
      {summary.stale && <Alert color="yellow" title="Out of date">{summary.stale_reasons.join(' ')} Review the selected sources before refreshing. The previous briefing remains saved.</Alert>}
      <Text size="sm">{savedSources.length} document{savedSources.length === 1 ? '' : 's'}; only the listed passages were reviewed.</Text>
      <Accordion><Accordion.Item value="coverage"><Accordion.Control>Documents and coverage limits</Accordion.Control>
        <Accordion.Panel><Stack>
          {savedSources.map((source) => <Source key={source.document_id} source={source} reviewed legacyRange={!summary.sources?.length} />)}
          {!!summary.warnings?.length && <Alert color="yellow" title="Briefing limitations"><Stack gap="xs">
            {summary.warnings.map((warning, index) => <Text size="sm" key={index}>{warning}</Text>)}
          </Stack></Alert>}
        </Stack></Accordion.Panel>
      </Accordion.Item></Accordion>
      <Text size="sm">Only the supplied passages were reviewed, not every page of the selected documents. A quote match confirms that the words occur in the cited document version. It does not verify the factual interpretation, the separate AI commentary, or mean that you have checked the briefing.</Text>
      <Title order={4}>Does this describe a spinoff? {summary.is_spinoff}</Title>
      <Statement value={summary.reasoning} busy={busy} onEvidence={() => evidence(0)} />
      {sections.map(([section, label]) => <Stack key={section} gap="sm"><Title order={4}>{label}</Title>
        {summary.sentences.filter((item) => item.section === section).length === 0 && <Text>Unresolved: no statement was produced for this section.</Text>}
        {summary.sentences.map((item, index) => item.section === section && <Statement key={index} value={item} busy={busy} onEvidence={() => evidence(index + 1)} />)}
      </Stack>)}
      <Usage value={summary.usage} />
    </Stack></Paper>}
    {state && !summary && <Text>No completed briefing has been saved for this case.</Text>}
    {!!state?.runs.length && <Accordion><Accordion.Item value="runs"><Accordion.Control>Briefing request history</Accordion.Control>
      <Accordion.Panel><Stack>{state.runs.map((run) => <Paper key={run.id} withBorder p="sm"><Stack gap="xs">
        <Group><Text fw={600}>Request {run.id}</Text><Badge color={run.status === 'completed' ? 'blue' : 'gray'}>{run.status}</Badge></Group>
        <Text size="sm">Started {run.created_at}{run.completed_at && ` · finished ${run.completed_at}`}</Text>
        <Text size="sm">{run.detail}</Text><Text size="sm">Reported retry notifications: {run.retry_count}</Text>
        <Usage value={run.usage} uncertain={run.usage_uncertain} />
      </Stack></Paper>)}</Stack></Accordion.Panel>
    </Accordion.Item></Accordion>}
  </Stack></Paper>;
}

export function SubscriptionSettings() {
  const [state, setState] = useState<SubscriptionState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    api.subscriptionStatus().then((result) => { if (!disposed) setState(result); })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, []);
  useEffect(() => {
    if (!state?.active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.subscriptionStatus();
        if (disposed) return;
        setState(result); setError(null);
        if (result.active) timer = window.setTimeout(poll, 1000);
      } catch (reason) { if (!disposed) setError(`Connection status could not be read. ${String(reason)}`); }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [state?.active, pollRevision]);
  async function check() {
    setBusy(true); setError(null);
    try { setState(await api.checkSubscription()); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function status() {
    setBusy(true); setError(null);
    try { setState(await api.subscriptionStatus()); setPollRevision((value) => value + 1); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <Paper withBorder p="lg"><Stack>
    <Title order={3}>ChatGPT subscription</Title>
    <Text size="sm">Uses the installed Codex client and your existing ChatGPT login. Check connection reads authentication, model availability and subscription allowance; it does not generate a briefing.</Text>
    <Button loading={busy} disabled={state?.active} onClick={check}>Check connection</Button>
    <Text>Connection: {state?.available === true ? 'available' : state?.available === false ? 'unavailable' : 'unknown'}</Text>
    <Text size="sm">Authentication: {state?.auth_type ?? 'unknown'} · plan: {state?.plan_type ?? 'unknown'} · checked: {state?.checked_at ?? 'not checked'}</Text>
    <Text size="sm">Briefing model: {state?.model ?? 'not checked'} · {state?.effort ?? 'unknown'} reasoning</Text>
    {state?.detail && <Text role="status">{state.detail}</Text>}
    {(error || state?.error) && <Alert color="red" role="alert">{error ?? state?.error}</Alert>}
    {error && <Button variant="default" disabled={busy} onClick={status}>Read connection status again</Button>}
    <Usage value={state?.usage ?? null} />
    <Text size="sm">Subscription usage has no calculated GBP charge here. Paid API access is disabled. The £50 monthly ceiling and £5 approval threshold remain recorded for possible future API use.</Text>
  </Stack></Paper>;
}
