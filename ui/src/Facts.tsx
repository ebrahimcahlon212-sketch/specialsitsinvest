import { Fragment, useEffect, useState } from 'react';
import { Accordion, Alert, Badge, Button, Group, Paper, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import * as api from './api';
import type { DocumentSummary, DocumentView, FactCorrection, FactRecord, FactRow, FactSource, FactState } from './api';

const factLabels = [
  ['parent_name', 'Parent company'], ['spinco_name', 'New company'], ['distribution_ratio', 'Distribution ratio'],
  ['record_date', 'Record date'], ['distribution_date', 'Distribution date'], ['listing_exchange', 'Listing exchange'],
  ['expected_ticker', 'Expected ticker'], ['when_issued_trading', 'When-issued trading'],
  ['shares_outstanding_after', 'Shares outstanding after separation'], ['debt_at_separation', 'Debt at separation'],
  ['cash_at_separation', 'Cash at separation'], ['cash_payment_to_parent', 'Cash payment to parent'],
  ['pension_and_other_liabilities', 'Pension and other liabilities'], ['pro_forma_revenue', 'Pro forma revenue'],
  ['pro_forma_operating_income', 'Pro forma operating income'], ['pro_forma_ebitda', 'Pro forma EBITDA'],
  ['conditions_to_distribution', 'Conditions to distribution'], ['tax_free_condition', 'Tax-free condition'],
  ['management_equity_awards', 'Management equity awards'],
] as const;

function statusColor(status: FactRecord['status']) {
  return status === 'checked' ? 'green' : status === 'extracted' ? 'blue' : status === 'contradicted' ? 'red' : 'gray';
}

function SourceDetails({ source }: { source: FactSource }) {
  return <Stack gap={3}>
    <Text size="sm">{source.name ?? 'Document'} · version {source.document_id} · filing date {source.filing_date ?? 'unknown'}</Text>
    <Text size="sm">Accession: {source.accession_number ?? 'unknown'} · {source.total_chars.toLocaleString()} characters in the saved text</Text>
    <Accordion><Accordion.Item value="identity"><Accordion.Control>Exact source identity</Accordion.Control>
      <Accordion.Panel><Text size="xs" style={{ overflowWrap: 'anywhere' }}>
        Cleaner: {source.cleaner_version ?? 'unknown'}<br />Original SHA-256: {source.original_sha256}<br />Text hash: {source.text_hash}
      </Text></Accordion.Panel></Accordion.Item></Accordion>
  </Stack>;
}

function FactDetails({ fact, busy, onEvidence }: { fact: FactRecord; busy: boolean; onEvidence: (id: number, index: number) => void }) {
  const unverified = fact.origin === 'model' && fact.status === 'unknown';
  return <Stack gap="xs">
    <Group><Text fw={600}>{fact.value ?? 'Unknown'}</Text><Badge color={statusColor(fact.status)}>{fact.status}</Badge>
      <Badge variant="outline">{fact.origin === 'human' ? 'Owner record' : 'Model proposal'}</Badge></Group>
    <Text size="sm">{unverified && 'Unverified proposed context: '}Unit: {fact.unit ?? 'unknown'} · Currency: {fact.currency ?? 'unknown'} · Company/entity: {fact.entity ?? 'unknown'}</Text>
    <Text size="sm">{unverified && 'Unverified proposed context: '}Date or period: {fact.period ?? 'unknown'} · Basis: {fact.basis.replaceAll('_', ' ')} · Kind: {fact.kind}</Text>
    {fact.qualifications && <Text size="sm">{unverified && 'Unverified proposed context: '}Qualifications: {fact.qualifications}</Text>}
    <Text size="sm">{fact.origin === 'model' ? 'Model explanation / validation' : 'Reason'}: {fact.reason || 'not recorded'}</Text>
    <Text size="sm">Finding: {fact.finding.replaceAll('_', ' ')} · saved {fact.created_at} · record {fact.id}{fact.previous_id !== null && ` · previous record ${fact.previous_id}`}</Text>
    <Text size="sm">Document version: {fact.document_id ?? 'none'} · model request: {fact.run_id ?? 'none'}</Text>
    {fact.citations.map((item, index) => <Button key={index} variant="subtle" disabled={busy} h="auto" py="xs"
      styles={{ label: { whiteSpace: 'normal', textAlign: 'left', lineHeight: 1.5 } }} onClick={() => onEvidence(fact.id, index)}>
      Quote matched · proposed support for {item.fields.join(', ').replaceAll('_', ' ')}: “{item.citation.quote}”
    </Button>)}
    {!fact.citations.length && <Text size="sm">No verified source passage is attached to this record.</Text>}
  </Stack>;
}

function CorrectionForm({ row, caseId, sourceId, documents, busy, onSave, onCheck, onClose }: {
  row: FactRow; caseId: number; sourceId: number | null; documents: DocumentSummary[]; busy: boolean;
  onSave: (value: FactCorrection) => Promise<boolean>; onCheck: (id: number, reason: string) => Promise<boolean>; onClose: () => void;
}) {
  const [original] = useState(row.effective);
  const [draft, setDraft] = useState(() => ({
    value: original?.value ?? '', unit: original?.unit ?? '', currency: original?.currency ?? '',
    entity: original?.entity ?? '', period: original?.period ?? '', basis: original?.basis ?? 'unknown',
    kind: original?.kind ?? 'published', qualifications: original?.qualifications ?? '', reason: '',
    document_id: String(original?.document_id ?? sourceId ?? ''),
    quote: original?.citations.find((item) => item.fields.includes('value'))?.citation.quote ?? '',
  }));
  const changed = (original?.id ?? null) !== (row.effective?.id ?? null);
  const nullIfBlank = (value: string) => value.trim() || null;
  const knownWithoutEvidence = !!draft.value.trim() && !draft.quote.trim() && draft.kind !== 'assumption';
  const choices = documents.filter((item) => item.searchable).map((item) => ({ value: String(item.id), label: `${item.name ?? 'Document'}: version ${item.id}` }));
  if (draft.document_id && !choices.some((item) => item.value === draft.document_id)) {
    choices.push({ value: draft.document_id, label: `Saved source document version ${draft.document_id}` });
  }
  async function save() {
    const result = await onSave({
      case_id: caseId, key: row.key, previous_id: original?.id ?? null, value: nullIfBlank(draft.value),
      unit: nullIfBlank(draft.unit), currency: nullIfBlank(draft.currency), entity: nullIfBlank(draft.entity),
      period: nullIfBlank(draft.period), basis: draft.basis, kind: draft.kind,
      qualifications: nullIfBlank(draft.qualifications), reason: draft.reason.trim(),
      document_id: draft.quote.trim() && draft.document_id ? Number(draft.document_id) : null, quote: nullIfBlank(draft.quote),
    });
    if (result) onClose();
  }
  return <Paper withBorder p="md"><Stack>
    <Title order={4}>Review or correct {row.label.toLowerCase()}</Title>
    <Text size="sm">Saving creates a new owner record. Earlier proposals and corrections remain in history. Leave the value blank to record it as unknown.</Text>
    {changed && <Alert color="yellow">The current record changed while this form was open. Your draft remains here; close and reopen the form to review the new record before saving.</Alert>}
    <Textarea label="Value" description="Enter quantities as decimal text. No calculation or rounding is performed here." value={draft.value} disabled={busy}
      onChange={(event) => setDraft({ ...draft, value: event.currentTarget.value })} autosize minRows={2} />
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      {(['unit', 'currency', 'entity', 'period'] as const).map((field) => <TextInput key={field}
        label={{ unit: 'Unit', currency: 'Currency', entity: 'Company/entity', period: 'Date or reporting period' }[field]}
        value={draft[field]} disabled={busy} onChange={(event) => setDraft({ ...draft, [field]: event.currentTarget.value })} />)}
      <Select label="Basis" value={draft.basis} disabled={busy} data={[
        { value: 'unknown', label: 'Unknown' }, { value: 'historical', label: 'Historical' },
        { value: 'pro_forma', label: 'Pro forma' }, { value: 'not_applicable', label: 'Not applicable' },
      ]} onChange={(value) => { if (value) setDraft({ ...draft, basis: value as FactRecord['basis'] }); }} />
      <Select label="Kind" value={draft.kind} disabled={busy} data={[
        { value: 'published', label: 'Published' }, { value: 'forecast', label: 'Forecast' }, { value: 'assumption', label: 'Owner assumption' },
      ]} onChange={(value) => { if (value) setDraft({ ...draft, kind: value as FactRecord['kind'] }); }} />
    </SimpleGrid>
    <Textarea label="Qualifications" value={draft.qualifications} disabled={busy} autosize minRows={2}
      onChange={(event) => setDraft({ ...draft, qualifications: event.currentTarget.value })} />
    <Select label="Source document for the correction" placeholder="Select a saved document" data={choices} value={draft.document_id || null}
      disabled={busy} clearable onChange={(value) => setDraft({ ...draft, document_id: value ?? '' })} />
    <Textarea label="Verbatim supporting quote" value={draft.quote} disabled={busy} autosize minRows={3}
      description="After changing a value, update its supporting quote. A quote match alone does not confirm the interpretation. A known value without a quote must be an owner assumption."
      error={knownWithoutEvidence ? 'Supply a supporting quote or choose Owner assumption.' : draft.quote.trim() && !draft.document_id ? 'Select the source document for this quote.' : null}
      onChange={(event) => setDraft({ ...draft, quote: event.currentTarget.value })} />
    <Textarea label="Reason for your check or correction" required value={draft.reason} disabled={busy} autosize minRows={2}
      onChange={(event) => setDraft({ ...draft, reason: event.currentTarget.value })} />
    <Group><Button disabled={busy || changed || !draft.reason.trim() || knownWithoutEvidence || (!!draft.quote.trim() && !draft.document_id)} onClick={save}>Save correction as checked</Button>
      {original?.origin === 'model' && original.status === 'extracted' && original.value !== null && original.citations.length > 0 && <Button variant="default"
        disabled={busy || changed || !draft.reason.trim()} onClick={async () => { if (await onCheck(original.id, draft.reason.trim())) onClose(); }}>
        Mark original proposal checked
      </Button>}
      <Button variant="subtle" disabled={busy} onClick={onClose}>Close correction form</Button>
    </Group>
    <Text size="sm">“Mark original proposal checked” keeps the original proposal's values. “Save correction as checked” uses the fields above; a blank value stays unknown.</Text>
  </Stack></Paper>;
}

export default function FactsPanel({ caseId, documents, onDocument, onChanged }: {
  caseId: number; documents: DocumentSummary[] | undefined; onDocument: (value: DocumentView) => void; onChanged: () => Promise<void>;
}) {
  const [state, setState] = useState<FactState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    api.factsStatus(caseId).then((result) => { if (!disposed) setState(result); })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [caseId, documents]);
  useEffect(() => {
    if (!state?.active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.factsStatus(caseId);
        if (disposed) return;
        setState(result); setError(null);
        if (result.active) timer = window.setTimeout(poll, 1000);
        else await onChanged();
      } catch (reason) { if (!disposed) setError(`Progress could not be checked; extraction may still be active. ${String(reason)}`); }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [caseId, state?.active, pollRevision]);
  async function request(operation: () => Promise<FactState>, changed = false): Promise<boolean> {
    setBusy(true); setError(null);
    try {
      const result = await operation();
      setState(result); setPollRevision((value) => value + 1);
      if (changed && !result.error) await onChanged();
      return !result.error;
    } catch (reason) { setError(String(reason)); return false; }
    finally { setBusy(false); }
  }
  async function evidence(id: number, index: number) {
    setBusy(true); setError(null);
    try { onDocument(await api.readFactEvidence(id, index)); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  const choices = (documents ?? []).filter((item) => item.searchable).map((item) => ({ value: String(item.id), label: `${item.name ?? 'Document'}: version ${item.id}` }));
  const rows: FactRow[] = factLabels.map(([key, label]) => state?.rows.find((row) => row.key === key) ?? {
    key, label, effective: null, proposal: null, conflict: false, history: [],
  });
  return <Paper withBorder p="lg"><Stack>
    <Title order={2}>Deal terms</Title>
    <Text size="sm">Extract proposed facts from selected passages of one information statement using your ChatGPT subscription. Unknown terms stay unknown; proposals never replace your saved corrections.</Text>
    <Select label="Information statement for deal terms" placeholder="Select a saved, searchable document" data={choices}
      value={state?.selected_document_id == null ? null : String(state.selected_document_id)} disabled={!state || busy || state.active}
      onChange={(value) => { if (value !== null) request(() => api.setFactsSource(caseId, Number(value))); }} />
    {state?.source && <SourceDetails source={state.source} />}
    <Text size="sm">OpenAI receives the selected passages. This is partial analysis. Unknown may mean a blank term, missing context or a failed evidence check; it does not establish that the filing omits the term. Values are not copied into the valuation worksheet automatically.</Text>
    <Group><Button loading={busy} disabled={!state?.source || state.active} onClick={() => request(() => api.extractFacts(caseId, state!.source!.document_id))}>Extract deal terms</Button>
      {state?.active && <Button variant="default" disabled={busy} onClick={() => request(() => api.cancelFacts(caseId))}>Cancel</Button>}
    </Group>
    <Text size="sm">Matching completed batches are reused. Cancelled or interrupted requests do not restart automatically. Subscription usage is shown without an invented GBP cost.</Text>
    {state?.detail && <Text role="status">{state.detail}</Text>}
    {(error || state?.error) && <Alert color="red" role="alert">{error ?? state?.error}</Alert>}
    {(error || state?.error) && <Button variant="default" disabled={busy} onClick={() => request(() => api.factsStatus(caseId))}>Check extraction status</Button>}
    {!!state?.warnings.length && <>
      <Alert color="yellow"><Stack gap="xs"><Text>{state.warnings[0]}</Text>
        <Text size="sm">Review {state.warnings.length} warning{state.warnings.length === 1 ? '' : 's'} below.</Text></Stack></Alert>
      <Accordion><Accordion.Item value="warnings"><Accordion.Control>Coverage warnings ({state.warnings.length})</Accordion.Control>
        <Accordion.Panel><Stack gap="sm">{state.warnings.map((warning, index) => <Text size="sm" key={index}>{warning}</Text>)}</Stack></Accordion.Panel>
      </Accordion.Item></Accordion>
    </>}
    {!state && !error && <Text role="status">Reading saved deal terms…</Text>}
    {documents && choices.length === 0 && <Text>Import a usable HTML or text information statement before extracting deal terms.</Text>}
    {state && <>
      <Text size="sm">Extracted means proposed by the model. Only you can mark a value checked. Matching quotations confirm the words occur, not that the interpretation is correct.</Text>
      <Table.ScrollContainer minWidth={670}><Table withTableBorder striped verticalSpacing="sm">
        <Table.Thead><Table.Tr><Table.Th>Term</Table.Th><Table.Th>Current value and context</Table.Th><Table.Th>Status</Table.Th><Table.Th>Review</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{rows.map((row) => <Fragment key={row.key}>
          <Table.Tr><Table.Td style={{ width: '22%' }}>{row.label}</Table.Td>
            <Table.Td style={{ maxWidth: 450 }}><Text style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{row.effective?.value ?? 'Unknown'}</Text>
              {row.effective && <Text size="xs">{row.effective.origin === 'model' && row.effective.status === 'unknown' && 'Unverified proposed context: '}{[row.effective.unit, row.effective.currency, row.effective.entity, row.effective.period, row.effective.basis.replaceAll('_', ' '), row.effective.kind].filter(Boolean).join(' · ')}</Text>}
              {row.effective?.qualifications && !(row.effective.origin === 'model' && row.effective.status === 'unknown') && <Text size="sm">{row.effective.qualifications}</Text>}
              {row.conflict && <Text size="sm" c="red">A model proposal conflicts with the current record. Review both below.</Text>}
            </Table.Td><Table.Td><Stack gap={3}><Badge color={statusColor(row.effective?.status ?? 'unknown')}>{row.effective?.status ?? 'unknown'}</Badge>
              {row.effective?.origin === 'human' && <Text size="xs">Owner record retained</Text>}</Stack></Table.Td>
            <Table.Td><Button size="xs" variant="default" onClick={() => { setExpanded(expanded === row.key ? null : row.key); setEditing(null); }}>{expanded === row.key ? 'Close' : 'Evidence / edit'}</Button></Table.Td>
          </Table.Tr>
          {expanded === row.key && <Table.Tr><Table.Td colSpan={4}><Stack p="sm">
            {row.effective ? <FactDetails fact={row.effective} busy={busy} onEvidence={evidence} /> : <Text>Unknown: no saved value has been produced. You may enter a sourced correction or an explicit assumption.</Text>}
            {row.proposal && row.proposal.id !== row.effective?.id && <Paper withBorder p="md"><Stack>
              <Title order={4}>Latest model proposal{row.conflict ? ': conflict' : ''}</Title>
              <Text size="sm">Your owner record above remains current. A proposal from another document version is kept separately.</Text>
              <FactDetails fact={row.proposal} busy={busy} onEvidence={evidence} />
            </Stack></Paper>}
            {editing !== row.key ? <Button variant="default" disabled={busy} onClick={() => setEditing(row.key)}>Review or correct value</Button> :
              <CorrectionForm key={row.key} row={row} caseId={caseId} sourceId={state.selected_document_id} documents={documents ?? []} busy={busy}
                onSave={(value) => request(() => api.correctFact(value), true)} onCheck={(id, reason) => request(() => api.checkFact(caseId, id, reason), true)} onClose={() => setEditing(null)} />}
            <Accordion><Accordion.Item value="history"><Accordion.Control>Record history ({row.history.length})</Accordion.Control>
              <Accordion.Panel><Stack>{row.history.map((fact) => <Paper key={fact.id} withBorder p="sm"><FactDetails fact={fact} busy={busy} onEvidence={evidence} /></Paper>)}
                {!row.history.length && <Text>No history is saved for this term.</Text>}
              </Stack></Accordion.Panel></Accordion.Item></Accordion>
          </Stack></Table.Td></Table.Tr>}
        </Fragment>)}</Table.Tbody>
      </Table></Table.ScrollContainer>
    </>}
    {!!state?.coverage.length && <Accordion><Accordion.Item value="coverage"><Accordion.Control>Passages recorded for extraction</Accordion.Control>
      <Accordion.Panel><Stack>{state.coverage.map((coverage) => <Paper key={coverage.run_id} withBorder p="md"><Stack>
        <Title order={4}>Request {coverage.run_id} · {coverage.prompt_version}</Title>
        <Text size="sm">Status: {state.runs.find((run) => run.id === coverage.run_id)?.status ?? 'see saved request record'}. Failed or interrupted requests do not establish completed review.</Text>
        <SourceDetails source={coverage.source} />
        <Text size="sm">{coverage.passages.length} recorded passage(s). The whole filing was not reviewed.</Text>
        <Accordion><Accordion.Item value="passages"><Accordion.Control>Read the recorded passages and exact ranges</Accordion.Control><Accordion.Panel><Stack>
          {coverage.passages.map((passage) => <Paper key={passage.id} withBorder p="sm"><Stack gap="xs">
            <Text fw={600}>{passage.heading ?? 'Passage'} · saved passage {passage.id}</Text>
            <Text size="sm">Document version {passage.document_id} · characters {(passage.start_offset + 1).toLocaleString()}–{passage.end_offset.toLocaleString()}</Text>
            {passage.partial && <Badge color="yellow">Partial table or passage</Badge>}
            <Text size="sm">Terms: {Object.entries(coverage.key_passages).filter(([, ids]) => ids.includes(passage.id)).map(([key]) => factLabels.find(([name]) => name === key)?.[1] ?? key).join(', ') || 'not specified'}</Text>
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{passage.text}</Text>
          </Stack></Paper>)}
        </Stack></Accordion.Panel></Accordion.Item></Accordion>
      </Stack></Paper>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>}
    {!!state?.runs.length && <Accordion><Accordion.Item value="runs"><Accordion.Control>Extraction request history and usage</Accordion.Control>
      <Accordion.Panel><Stack>{state.runs.map((run) => <Paper key={run.id} withBorder p="sm"><Stack gap="xs">
        <Group><Text fw={600}>Request {run.id}</Text><Badge>{run.status}</Badge></Group>
        <Text size="sm">{run.created_at}{run.completed_at && ` · finished ${run.completed_at}`}</Text><Text size="sm">{run.detail}</Text>
        <Text size="sm">Reported retry notifications: {run.retry_count}</Text>
        {run.usage_uncertain && <Text size="sm" c="orange">Final usage is uncertain; any reported values may be partial.</Text>}
        {run.usage === null ? <Text size="sm">Usage: unknown; no usage information was returned.</Text> :
          <Text component="pre" size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(run.usage, null, 2)}</Text>}
      </Stack></Paper>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>}
  </Stack></Paper>;
}
