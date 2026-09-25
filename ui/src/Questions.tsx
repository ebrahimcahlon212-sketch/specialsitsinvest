import { useEffect, useRef, useState } from 'react';
import { Accordion, Alert, Badge, Button, Group, Paper, Select, Stack, Text, Textarea, Title } from '@mantine/core';
import * as api from './api';
import type { DocumentSummary, DocumentView, QuestionState } from './api';

export default function QuestionsPanel({ caseId, documents, onDocument }: {
  caseId: number; documents: DocumentSummary[] | undefined; onDocument: (value: DocumentView) => void;
}) {
  const [state, setState] = useState<QuestionState | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [answerId, setAnswerId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollRevision, setPollRevision] = useState(0);
  const newestAnswer = useRef<number | null>(null);
  const pendingQuestion = useRef(false);

  function accept(result: QuestionState) {
    setState(result);
    setDocumentId((current) => result.sources.some((source) => String(source.document_id) === current)
      ? current : result.selected_document_id === null ? null : String(result.selected_document_id));
    const latest = result.answers[0]?.id ?? null;
    const changed = latest !== newestAnswer.current;
    const completed = !result.active && !result.error && pendingQuestion.current;
    setAnswerId((current) => completed || changed || !result.answers.some((answer) => String(answer.id) === current)
      ? latest === null ? null : String(latest) : current);
    if (!result.active) pendingQuestion.current = false;
    newestAnswer.current = latest;
  }
  useEffect(() => {
    let disposed = false;
    api.questionStatus(caseId).then((result) => { if (!disposed) { accept(result); setError(null); } })
      .catch((reason) => { if (!disposed) setError(String(reason)); });
    return () => { disposed = true; };
  }, [caseId, documents]);
  useEffect(() => {
    if (!state?.active) return;
    let disposed = false;
    let timer: number;
    async function poll() {
      try {
        const result = await api.questionStatus(caseId);
        if (disposed) return;
        accept(result); setError(null);
        if (result.active) timer = window.setTimeout(poll, 1000);
      } catch (reason) {
        if (!disposed) setError(`Progress could not be checked. The request may still be active. ${String(reason)}`);
      }
    }
    timer = window.setTimeout(poll, 1000);
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [caseId, state?.active, pollRevision]);

  async function request(operation: () => Promise<QuestionState>) {
    setBusy(true); setError(null);
    try { accept(await operation()); setPollRevision((value) => value + 1); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function evidence(index: number) {
    if (answerId === null) return;
    setBusy(true); setError(null);
    try { onDocument(await api.readQuestionEvidence(Number(answerId), index)); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  const source = state?.sources.find((item) => String(item.document_id) === documentId);
  const answer = state?.answers.find((item) => String(item.id) === answerId);
  return <Paper withBorder p="lg"><Stack>
    <Title order={2}>Ask about a document</Title>
    <Text size="sm">Ask a question about one saved document version. GPT-5.6 Luna uses low reasoning and your ChatGPT subscription. Only your question and the retrieved passages are sent for this answer.</Text>
    <Select label="Document version for this question" placeholder="Select a saved, searchable document"
      data={(state?.sources ?? []).map((item) => ({ value: String(item.document_id), label: `${item.name ?? 'Document'}: version ${item.document_id}` }))}
      value={documentId} onChange={setDocumentId} disabled={!state || busy || state.active} />
    {source && <Text size="sm">Version {source.document_id} · filing date {source.filing_date ?? 'unknown'} · {source.total_chars.toLocaleString()} searchable characters</Text>}
    {state && !state.sources.length && <Text>Import a usable HTML or text document before asking a question.</Text>}
    <Textarea label="Question" value={question} onChange={(event) => setQuestion(event.currentTarget.value)}
      autosize minRows={2} maxLength={2000} disabled={busy || state?.active} />
    <Text size="sm">Search covers the selected document, but the answer uses at most six retrieved passages and 24,000 characters, with neighbouring text or table context where available. It is not a review of the whole filing. Generation has a 60-second deadline after client setup; cancellation never restarts the request.</Text>
    <Group>
      <Button loading={busy} disabled={!state || state.active || !source || !question.trim()}
        onClick={() => {
          pendingQuestion.current = true;
          request(() => api.askQuestion(caseId, source!.document_id, question));
        }}>Ask question</Button>
      {state?.active && <Button variant="default" disabled={busy} onClick={() => request(() => api.cancelQuestion(caseId))}>Cancel</Button>}
    </Group>
    {state?.detail && <Text role="status">{state.detail}</Text>}
    {state?.active && !state.detail && <Text role="status">The question is queued or being answered. Progress is checked every second.</Text>}
    {(error || state?.error) && <Alert color="red" role="alert">{error ?? state?.error}</Alert>}
    {(error || state?.error) && <Button variant="default" disabled={busy} onClick={() => request(() => api.questionStatus(caseId))}>Check question status</Button>}
    {!state && !error && <Text role="status">Reading saved answers…</Text>}
    {!!state?.answers.length && <Select label="Saved answers" value={answerId} onChange={setAnswerId}
      data={state.answers.map((item) => ({ value: String(item.id), label: `${item.created_at}: ${item.question}` }))} />}
    {state && !state.answers.length && <Text>No completed answers have been saved for this case.</Text>}
    {answer && <Paper withBorder p="md"><Stack>
      <Group justify="space-between"><Title order={3}>Saved answer</Title><Badge>Record {answer.id}</Badge></Group>
      <Text fw={600} style={{ whiteSpace: 'pre-wrap' }}>{answer.question}</Text>
      <Text size="sm">Saved {answer.created_at} · prompt {answer.prompt_version}</Text>
      <Text size="sm">{answer.source.name ?? 'Document'} · document version {answer.source.document_id} · filing date {answer.source.filing_date ?? 'unknown'}</Text>
      {answer.stale && <Alert color="yellow" title="Out of date">{answer.stale_reason ?? 'The relevant source or request settings have changed.'} This saved answer still refers to its original document version.</Alert>}
      {source && source.document_id !== answer.source.document_id && <Alert color="yellow">This saved answer uses document version {answer.source.document_id}, not the currently selected version {source.document_id}. Ask the question again to use the selected source.</Alert>}
      <Text size="sm">A quote match confirms that the words occur in the saved source. It does not verify the interpretation or mean that you have checked the answer.</Text>
      {answer.sentences.map((sentence, index) => <Stack key={index} gap="xs">
        <Text style={{ whiteSpace: 'pre-wrap' }}>{sentence.text}</Text>
        {sentence.status !== 'quote matched' && <Badge color="yellow">{sentence.status === 'assumption' ? 'Assumption' : 'Unresolved: support not established'}</Badge>}
        {sentence.detail && <Text size="sm">{sentence.detail}</Text>}
        {sentence.citation ? <Button variant="subtle" disabled={busy} h="auto" py="xs" onClick={() => evidence(index)}
          styles={{ label: { whiteSpace: 'normal', textAlign: 'left', lineHeight: 1.5 } }}>
          Quote matched: “{sentence.citation.quote}”
        </Button> : sentence.quote && <Text size="sm">Unverified quote: “{sentence.quote}”</Text>}
      </Stack>)}
      {!answer.sentences.length && <Text>No supported answer sentences were produced.</Text>}
      {!!answer.limitations.length && <Alert color="yellow" title="Answer limitations"><Stack gap="xs">
        {answer.limitations.map((item, index) => <Text size="sm" key={index}>{item}</Text>)}
      </Stack></Alert>}
      {!!answer.warnings.length && <Alert color="yellow" title="Retrieval limitations"><Stack gap="xs">
        {answer.warnings.map((item, index) => <Text size="sm" key={index}>{item}</Text>)}
      </Stack></Alert>}
      <Accordion><Accordion.Item value="sources"><Accordion.Control>Passages supplied for this answer ({answer.passages.length})</Accordion.Control>
        <Accordion.Panel><Stack>
          <Text size="sm">These saved ranges identify the evidence supplied, including context. Other passages and other documents were not supplied.</Text>
          <Text size="xs" style={{ overflowWrap: 'anywhere' }}>Original SHA-256: {answer.source.original_sha256}<br />Text hash: {answer.source.text_hash}<br />Cleaner: {answer.source.cleaner_version ?? 'unknown'}</Text>
          {!answer.passages.length && <Text>No useful evidence was retrieved for this question.</Text>}
          {answer.passages.map((passage) => <Paper withBorder p="sm" key={passage.id}><Stack gap="xs">
            <Text fw={600}>{passage.heading ?? 'Source passage'} · passage {passage.id}</Text>
            <Text size="sm">Document version {passage.document_id} · characters {(passage.start_offset + 1).toLocaleString()}–{passage.end_offset.toLocaleString()}</Text>
            {passage.partial && <Badge color="yellow">Partial passage or table</Badge>}
            <Text size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{passage.text}</Text>
          </Stack></Paper>)}
          {!!answer.searches.length && <Text size="sm" style={{ overflowWrap: 'anywhere' }}>Searches used: {answer.searches.map((item) => typeof item === 'string' ? item : JSON.stringify(item)).join('; ')}</Text>}
        </Stack></Accordion.Panel>
      </Accordion.Item></Accordion>
    </Stack></Paper>}
    {!!state?.runs.length && <Accordion><Accordion.Item value="runs"><Accordion.Control>Question request history</Accordion.Control>
      <Accordion.Panel><Stack>{state.runs.map((run) => <Paper key={run.id} withBorder p="sm"><Stack gap="xs">
        <Group><Text fw={600}>Request {run.id}</Text><Badge color={run.status === 'completed' ? 'blue' : 'gray'}>{run.status}</Badge></Group>
        <Text size="sm">Started {run.created_at}{run.completed_at && ` · finished ${run.completed_at}`}</Text>
        <Text size="sm">{run.detail}</Text>
        <Text size="sm">Reported retry notifications: {run.retry_count}</Text>
        {run.usage_uncertain && <Text size="sm" c="orange">Final usage is uncertain. Any reported values may be partial.</Text>}
        {run.usage === null ? <Text size="sm">Usage: unknown; no usage information was returned.</Text> :
          <Text component="pre" size="sm" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(run.usage, null, 2)}</Text>}
      </Stack></Paper>)}</Stack></Accordion.Panel>
    </Accordion.Item></Accordion>}
  </Stack></Paper>;
}
