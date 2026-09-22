import { useState } from 'react';
import { Alert, Button, Divider, Group, Paper, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { calculateScenario, saveScenario, type ScenarioRecord, type ScenarioRequest } from './api';

type Fields = Record<string, string>;
type ClaimFields = { name: string; value: string; counted: string };
type Display = { display: Record<string, Record<string, string>>; warning: string | null };

function blankSpinoff(): Fields {
  return Object.fromEntries(['entity', 'period', 'currency', 'profit', 'profit_measure', 'multiple_measure',
    'low', 'base', 'high', 'net_debt', 'parent_included', 'parent_payment', 'other_assets',
    'diluted_shares', 'leases_consistent', 'current_price', 'price_time'].map((field) => [field, '']));
}

function blankTender(): Fields {
  return Object.fromEntries(['name', 'tender_price', 'accepted_fraction', 'withholding_rate', 'residual_value',
    'exit_fx', 'cash_distributions', 'exit_costs', 'probability', 'duration_days',
    'withholding_basis', 'broker_confirmation'].map((field) => [field, '']));
}

function savedFields(template: ScenarioRecord | null | undefined) {
  const spin = blankSpinoff();
  let claims: ClaimFields[] = ['Lease liabilities', 'Pension deficits', 'Preferred stock',
    'Non-controlling interests'].map((name) => ({ name, value: '', counted: '' }));
  const purchase: Fields = { currency: '', shares: '', purchase_price: '', entry_fx: '', entry_costs: '' };
  let tenders = [blankTender()];
  const object = (value: unknown): Record<string, unknown> =>
    value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const text = (value: unknown) => typeof value === 'string' ? value : '';
  const amount = (value: unknown) => text(object(value).value);
  const confirmed = (value: unknown) => value === true ? 'yes' : value === false ? 'no' : '';
  if (template?.kind === 'spinoff') {
    const input = template.inputs;
    const profit = object(input.profit);
    for (const field of ['entity', 'period', 'currency']) spin[field] = text(profit[field]);
    for (const field of ['profit_measure', 'multiple_measure']) spin[field] = text(input[field]);
    for (const field of ['profit', 'net_debt', 'parent_payment', 'other_assets', 'diluted_shares', 'current_price']) {
      spin[field] = amount(input[field]);
    }
    for (const level of ['low', 'base', 'high']) spin[level] = amount(object(input.multiples)[level]);
    spin.parent_included = confirmed(input.net_debt_includes_parent_payment);
    spin.leases_consistent = confirmed(input.lease_treatment_consistent);
    spin.price_time = text(input.price_observed_at);
    if (Array.isArray(input.other_claims)) claims = input.other_claims.map((value) => {
      const claim = object(value);
      return { name: text(claim.name), value: amount(claim.amount), counted: confirmed(claim.already_counted_elsewhere) };
    });
  } else if (template?.kind === 'tender' && Array.isArray(template.inputs.scenarios)) {
    const first = object(object(template.inputs.scenarios[0]).inputs);
    purchase.currency = text(object(first.purchase_price).currency);
    for (const field of ['shares', 'purchase_price', 'entry_fx', 'entry_costs']) purchase[field] = amount(first[field]);
    tenders = template.inputs.scenarios.map((value) => {
      const scenario = object(value);
      const input = object(scenario.inputs);
      const row = blankTender();
      for (const field of ['name', 'duration_days', 'withholding_basis', 'broker_confirmation']) row[field] = text(scenario[field]);
      row.probability = amount(scenario.probability);
      for (const field of ['tender_price', 'accepted_fraction', 'withholding_rate', 'residual_value', 'exit_fx', 'cash_distributions', 'exit_costs']) {
        row[field] = amount(input[field]);
      }
      return row;
    });
  }
  return { spin, claims, purchase, tenders };
}

function quantity(value: string, unit: string, currency: string | null = null,
  entity: string | null = null, period: string | null = null) {
  return { value: value.trim() || null, unit, currency, entity, period };
}

function answer(value: string) { return value === '' ? null : value === 'yes'; }

function DecimalField({ label, value, onChange, description }: {
  label: string; value: string; onChange: (value: string) => void; description?: string;
}) {
  return <TextInput label={label} description={description} value={value} inputMode="decimal"
    placeholder="Unknown" onChange={(event) => onChange(event.currentTarget.value)} />;
}

function Confirmation({ label, value, onChange }: {
  label: string; value: string; onChange: (value: string) => void;
}) {
  return <Select label={label} value={value} onChange={(choice) => onChange(choice ?? '')}
    data={[{ value: '', label: 'Unknown' }, { value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]} />;
}

export default function Calculators({ caseId, onSaved, template }: {
  caseId: number; onSaved: () => void; template?: ScenarioRecord | null;
}) {
  const [loaded] = useState(() => savedFields(template));
  const [kind, setKind] = useState<'spinoff' | 'tender'>(() => template?.kind ?? 'spinoff');
  const [name, setName] = useState(() => template ? `${template.name} copy` : '');
  const [spin, setSpin] = useState(loaded.spin);
  const [claims, setClaims] = useState<ClaimFields[]>(loaded.claims);
  const [purchase, setPurchase] = useState<Fields>(loaded.purchase);
  const [tenders, setTenders] = useState<Fields[]>(loaded.tenders);
  const [result, setResult] = useState<Display | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState(() => template ? `Inputs copied from “${template.name}”. Calculate or save a new record; the saved original is unchanged.` : '');
  const [busy, setBusy] = useState(false);

  function changed() { setResult(null); setError(null); setStatus('Inputs changed. Calculate to see the result.'); }
  function changeSpin(field: string, value: string) { changed(); setSpin({ ...spin, [field]: value }); }
  function changePurchase(field: string, value: string) { changed(); setPurchase({ ...purchase, [field]: value }); }
  function changeTender(index: number, field: string, value: string) {
    changed(); setTenders(tenders.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
  }
  function changeClaim(index: number, field: keyof ClaimFields, value: string) {
    changed(); setClaims(claims.map((claim, rowIndex) => rowIndex === index ? { ...claim, [field]: value } : claim));
  }

  function request(): ScenarioRequest {
    if (kind === 'spinoff') {
      const currency = spin.currency.trim() || null;
      const entity = spin.entity.trim() || null;
      const period = spin.period.trim() || null;
      const money = (value: string) => quantity(value, 'million_currency_units', currency, entity, period);
      return { case_id: caseId, name, kind, inputs: {
        profit: money(spin.profit), profit_measure: spin.profit_measure, multiple_measure: spin.multiple_measure,
        multiples: { low: quantity(spin.low, 'unitless'), base: quantity(spin.base, 'unitless'), high: quantity(spin.high, 'unitless') },
        net_debt: money(spin.net_debt), net_debt_includes_parent_payment: answer(spin.parent_included),
        parent_payment: spin.parent_payment.trim() ? money(spin.parent_payment) : null,
        other_claims: claims.map((claim) => ({ name: claim.name, amount: money(claim.value), already_counted_elsewhere: answer(claim.counted) })),
        other_assets: money(spin.other_assets), diluted_shares: quantity(spin.diluted_shares, 'million_shares', null, entity, period),
        lease_treatment_consistent: answer(spin.leases_consistent),
        current_price: spin.current_price.trim() ? quantity(spin.current_price, 'currency_units_per_share', currency, entity, period) : null,
        price_observed_at: spin.price_time.trim() || null,
      } };
    }
    const currency = purchase.currency.trim() || null;
    return { case_id: caseId, name, kind, inputs: { scenarios: tenders.map((row) => ({
      name: row.name, duration_days: row.duration_days.trim() || null,
      withholding_basis: row.withholding_basis, broker_confirmation: row.broker_confirmation,
      probability: row.probability.trim() ? quantity(row.probability, 'unitless') : null,
      inputs: {
        shares: quantity(purchase.shares, 'shares'),
        purchase_price: quantity(purchase.purchase_price, 'currency_units_per_share', currency),
        entry_fx: quantity(purchase.entry_fx, 'gbp_per_currency_unit', currency),
        entry_costs: quantity(purchase.entry_costs, 'currency_units', 'GBP'),
        tender_price: quantity(row.tender_price, 'currency_units_per_share', currency),
        accepted_fraction: quantity(row.accepted_fraction, 'unitless'),
        withholding_rate: quantity(row.withholding_rate, 'unitless'),
        residual_value: row.residual_value.trim() ? quantity(row.residual_value, 'currency_units_per_share', currency) : null,
        exit_fx: quantity(row.exit_fx, 'gbp_per_currency_unit', currency),
        cash_distributions: quantity(row.cash_distributions, 'currency_units', 'GBP'),
        exit_costs: quantity(row.exit_costs, 'currency_units', 'GBP'),
      },
    })) } };
  }

  async function run(save: boolean) {
    setBusy(true); setError(null); setStatus(''); setResult(null);
    try {
      const input = request();
      const calculated = save ? await saveScenario(input) : await calculateScenario(input);
      setResult({ display: calculated.display, warning: calculated.warning });
      setStatus(save ? 'Saved a new scenario record with these inputs and outputs.' : 'Calculated from the inputs shown.');
      if (save) onSaved();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }

  const reportingCurrency = spin.currency.trim() || 'reporting currency';
  const tradingCurrency = purchase.currency.trim() || 'trading currency';
  const profitMeasures = [{ value: '', label: 'Unknown' }, { value: 'ebitda', label: 'EBITDA' },
    { value: 'operating_income', label: 'Operating income' }];
  function scenarioTitle(key: string) {
    const index = tenders.findIndex((_, rowIndex) => String(rowIndex) === key);
    return index < 0 ? key : tenders[index].name || `Scenario ${index + 1}`;
  }

  return <Stack>
    <Title order={3}>Calculations</Title>
    <Text size="sm">Enter your assumptions. Blank means unknown; enter 0 only when you have confirmed zero or not applicable.</Text>
    <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <Stack>
        <Select label="Calculator" value={kind} onChange={(choice) => {
          if (choice === 'spinoff' || choice === 'tender') { setKind(choice); changed(); }
        }} data={[{ value: 'spinoff', label: 'Spinoff valuation' }, { value: 'tender', label: 'Fixed-price tender' }]} />
        <TextInput label="Saved calculation name" value={name} onChange={(event) => { setName(event.currentTarget.value); changed(); }} />
        {kind === 'spinoff' ? <>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            <TextInput label="Company / entity" value={spin.entity} onChange={(event) => changeSpin('entity', event.currentTarget.value)} />
            <TextInput label="Applicable period / pro forma basis" value={spin.period} onChange={(event) => changeSpin('period', event.currentTarget.value)} />
            <TextInput label="Reporting currency code" description="Use whole currency units, not pence or cents." value={spin.currency}
              onChange={(event) => changeSpin('currency', event.currentTarget.value)} />
          </SimpleGrid>
          <Text size="sm">The entity, period and currency above apply to all worksheet figures. Money is in millions; shares are in millions.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Profit measure" value={spin.profit_measure} data={profitMeasures} onChange={(value) => changeSpin('profit_measure', value ?? '')} />
            <Select label="Multiple applies to" value={spin.multiple_measure} data={profitMeasures} onChange={(value) => changeSpin('multiple_measure', value ?? '')} />
            <DecimalField label={`Profit (million ${reportingCurrency})`} value={spin.profit} onChange={(value) => changeSpin('profit', value)} />
            <DecimalField label={`Net debt after separation (million ${reportingCurrency})`} description="Debt less cash; a negative amount means net cash."
              value={spin.net_debt} onChange={(value) => changeSpin('net_debt', value)} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            {['low', 'base', 'high'].map((level) => <DecimalField key={level} label={`${level[0].toUpperCase()}${level.slice(1)} multiple (unitless)`}
              value={spin[level]} onChange={(value) => changeSpin(level, value)} />)}
          </SimpleGrid>
          <Confirmation label="Does net debt already include the cash payment to the parent?" value={spin.parent_included}
            onChange={(value) => changeSpin('parent_included', value)} />
          <DecimalField label={`Cash payment to parent (million ${reportingCurrency})`} value={spin.parent_payment}
            description="Required if not already included. An included payment is never deducted again."
            onChange={(value) => changeSpin('parent_payment', value)} />
          <Text fw={600}>Other claims</Text>
          {claims.map((claim, index) => <SimpleGrid key={index} cols={{ base: 1, sm: 3 }}>
            <TextInput label="Claim" value={claim.name} onChange={(event) => changeClaim(index, 'name', event.currentTarget.value)} />
            <DecimalField label={`Amount (million ${reportingCurrency})`} value={claim.value} onChange={(value) => changeClaim(index, 'value', value)} />
            <Confirmation label="Already counted elsewhere?" value={claim.counted} onChange={(value) => changeClaim(index, 'counted', value)} />
          </SimpleGrid>)}
          <Button variant="light" onClick={() => { changed(); setClaims([...claims, { name: '', value: '', counted: '' }]); }}>Add other claim</Button>
          <Confirmation label="Have you checked that lease treatment is consistent in profit, multiples and claims?" value={spin.leases_consistent}
            onChange={(value) => changeSpin('leases_consistent', value)} />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <DecimalField label={`Other assets (million ${reportingCurrency})`} value={spin.other_assets} onChange={(value) => changeSpin('other_assets', value)} />
            <DecimalField label="Diluted shares (million shares)" value={spin.diluted_shares} onChange={(value) => changeSpin('diluted_shares', value)} />
            <DecimalField label={`Observed current price (${reportingCurrency} per share)`} description="Optional. Leave blank to calculate value without a price comparison."
              value={spin.current_price} onChange={(value) => changeSpin('current_price', value)} />
            <TextInput label="Price observation date and time" description="Include timezone, for example 2026-09-19T14:30:00+01:00."
              value={spin.price_time} onChange={(event) => changeSpin('price_time', event.currentTarget.value)} />
          </SimpleGrid>
          <Paper withBorder p="sm">
            <Text size="sm">Enterprise value = profit × multiple</Text>
            <Text size="sm">Equity value = enterprise value − net debt − claims not already counted + other assets</Text>
            <Text size="sm">Subtract the parent payment separately only if net debt excludes it.</Text>
            <Text size="sm">Value per share = equity value ÷ diluted shares</Text>
            <Text size="sm">Difference = value per share ÷ observed price − 1</Text>
          </Paper>
        </> : <>
          <Text size="sm">Each scenario assumes one settlement date and one exit FX rate. Enter net cash distributions in GBP. Withholding is your event-specific assumption; no future tax refund is assumed.</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Trading currency code" description="Prices use whole currency units, not pence or cents." value={purchase.currency}
              onChange={(event) => changePurchase('currency', event.currentTarget.value)} />
            <DecimalField label="Shares purchased (whole shares)" value={purchase.shares} onChange={(value) => changePurchase('shares', value)} />
            <DecimalField label={`Purchase price (${tradingCurrency} per share)`} value={purchase.purchase_price} onChange={(value) => changePurchase('purchase_price', value)} />
            <DecimalField label={`Entry FX (GBP per 1 ${tradingCurrency})`} value={purchase.entry_fx} onChange={(value) => changePurchase('entry_fx', value)} />
            <DecimalField label="Entry costs (GBP)" value={purchase.entry_costs} onChange={(value) => changePurchase('entry_costs', value)} />
          </SimpleGrid>
          {tenders.map((row, index) => <Paper withBorder p="md" key={index}>
            <Stack>
              <Group justify="space-between"><Title order={4}>Scenario {index + 1}</Title>
                {tenders.length > 1 && <Button variant="subtle" color="red" onClick={() => {
                  changed(); setTenders(tenders.filter((_, rowIndex) => rowIndex !== index));
                }}>Remove scenario {index + 1}</Button>}
              </Group>
              <TextInput label="Scenario name" value={row.name} onChange={(event) => changeTender(index, 'name', event.currentTarget.value)} />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <DecimalField label={`Tender price (${tradingCurrency} per share)`} value={row.tender_price} onChange={(value) => changeTender(index, 'tender_price', value)} />
                <DecimalField label="Accepted fraction (unitless, 0 to 1)" value={row.accepted_fraction} onChange={(value) => changeTender(index, 'accepted_fraction', value)} />
                <DecimalField label="Withholding rate (unitless, 0 to 1)" description="Required assumption. Applied to gross accepted tender proceeds."
                  value={row.withholding_rate} onChange={(value) => changeTender(index, 'withholding_rate', value)} />
                <DecimalField label={`Residual value (${tradingCurrency} per remaining share)`} description="Not required when all shares are accepted."
                  value={row.residual_value} onChange={(value) => changeTender(index, 'residual_value', value)} />
                <DecimalField label={`Exit FX (GBP per 1 ${tradingCurrency})`} value={row.exit_fx} onChange={(value) => changeTender(index, 'exit_fx', value)} />
                <DecimalField label="Cash distributions (net GBP)" value={row.cash_distributions} onChange={(value) => changeTender(index, 'cash_distributions', value)} />
                <DecimalField label="Exit costs (GBP)" value={row.exit_costs} onChange={(value) => changeTender(index, 'exit_costs', value)} />
                <DecimalField label="Scenario duration (days)" value={row.duration_days} onChange={(value) => changeTender(index, 'duration_days', value)} />
                <DecimalField label="Owner probability (unitless, 0 to 1; optional)" description="Expected profit requires all probabilities to sum to one."
                  value={row.probability} onChange={(value) => changeTender(index, 'probability', value)} />
              </SimpleGrid>
              <Textarea label="Withholding basis in the offer document" description="Record the basis when available; otherwise leave unknown." value={row.withholding_basis}
                onChange={(event) => changeTender(index, 'withholding_basis', event.currentTarget.value)} />
              <Textarea label="Broker confirmation / actual treatment" description="Record confirmation and its date when available." value={row.broker_confirmation}
                onChange={(event) => changeTender(index, 'broker_confirmation', event.currentTarget.value)} />
            </Stack>
          </Paper>)}
          <Button variant="light" onClick={() => { changed(); setTenders([...tenders, blankTender()]); }}>Add scenario</Button>
          <Paper withBorder p="sm">
            <Text size="sm">Initial GBP committed = shares × purchase price × entry FX + entry costs</Text>
            <Text size="sm">Accepted shares = floor(shares × accepted fraction); remaining shares = shares − accepted shares</Text>
            <Text size="sm">Accepted proceeds = accepted shares × tender price × (1 − withholding rate)</Text>
            <Text size="sm">Scenario GBP proceeds = accepted proceeds × exit FX + remaining shares × residual value × exit FX + net cash distributions − exit costs</Text>
            <Text size="sm">Scenario profit = proceeds − initial GBP committed; return = profit ÷ initial GBP committed</Text>
            <Text size="sm">Expected profit = sum of (owner probability × scenario profit)</Text>
          </Paper>
          <Text size="sm">Accepted shares round down in this calculator; check actual offer terms. Fewer than 100 shares does not establish odd-lot priority. An ISA label does not set costs or withholding to zero. The worst listed scenario is not a guaranteed maximum loss.</Text>
        </>}
        <Group><Button onClick={() => void run(false)} loading={busy}>Calculate</Button>
          <Button variant="light" onClick={() => void run(true)} disabled={busy}>Calculate and save new record</Button></Group>
      </Stack>
    </fieldset>
    {status && <Text role="status">{status}</Text>}
    {error && <Alert color="red" title="Cannot calculate or save" role="alert">{error}</Alert>}
    {result && <>
      <Divider label="Calculated outputs" />
      {result.warning && <Alert color="yellow">{result.warning}</Alert>}
      {kind === 'spinoff' ? <Table.ScrollContainer minWidth={500}>
        <Table withTableBorder>
          <Table.Thead><Table.Tr><Table.Th>Output</Table.Th>{['low', 'base', 'high'].map((level) => <Table.Th key={level}>{level}</Table.Th>)}</Table.Tr></Table.Thead>
          <Table.Tbody>{Object.keys(result.display.low ?? {}).map((field) => <Table.Tr key={field}>
            <Table.Th>{field.replaceAll('_', ' ')}</Table.Th>{['low', 'base', 'high'].map((level) => <Table.Td key={level}>{result.display[level]?.[field] ?? 'Unknown'}</Table.Td>)}
          </Table.Tr>)}</Table.Tbody>
        </Table>
      </Table.ScrollContainer> : Object.entries(result.display).map(([key, values]) => <Paper key={key} withBorder p="sm">
        <Title order={4}>{key === 'expected' ? 'Expected profit' : scenarioTitle(key)}</Title>
        <Table><Table.Tbody>{Object.entries(values).map(([field, value]) => <Table.Tr key={field}>
          <Table.Th>{field.replaceAll('_', ' ')}</Table.Th><Table.Td>{value}</Table.Td>
        </Table.Tr>)}</Table.Tbody></Table>
      </Paper>)}
    </>}
  </Stack>;
}
