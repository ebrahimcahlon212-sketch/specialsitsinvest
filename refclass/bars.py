"""Historical-bar request preparation for the kit's existing Claude IBKR connection."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
from .collectors.ibkr import collect
from .locking import job_lock

ROOT = Path(__file__).resolve().parents[1]


def request(tickers, since, until):
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    if start > end:
        raise ValueError('Start date must not follow end date.')
    symbols = sorted(set(tickers) | {'XBI'})
    if not all(re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', t) for t in symbols):
        raise ValueError('Invalid ticker.')
    return dict(tickers=symbols, since=since, until=until)


def capability_gaps(query, today=None):
    today = today or date.today()
    try:
        earliest = today.replace(year=today.year - 5)
    except ValueError:
        earliest = today.replace(year=today.year - 5, day=28)
    gaps = []
    if date.fromisoformat(query['since']) < earliest:
        gaps.append(f"Configured get_price_history is limited to FIVE_YEARS back from {today}; "
                    f"requested history before {earliest} is unavailable, with no end-date pagination.")
    if date.fromisoformat(query['until']) > today:
        gaps.append('Requested future bars are unavailable.')
    return gaps


def transcript_bars(path, server):
    """Save original tool responses, including unsupported bars as explicit gaps.

    Plain OHLCV is never silently relabelled split-adjusted. The transport is
    retained even when the provider cannot supply the required price convention.
    """
    calls, rows, contracts = {}, [], {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        message = json.loads(line)
        for block in message.get('message', {}).get('content', []):
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                name = block.get('name', '')
                if name in {f'mcp__{server}__get_price_history', f'mcp__{server}__search_contracts', f'mcp__{server}__historical_bars'}:
                    calls[block['id']] = dict(name=name, input=block.get('input', {}))
            if block.get('type') != 'tool_result' or block.get('tool_use_id') not in calls:
                continue
            call = calls[block['tool_use_id']]
            content = block.get('content')
            if isinstance(content, list):
                content = ''.join(c.get('text', '') for c in content if c.get('type') == 'text')
            try:
                payload = json.loads(content) if isinstance(content, str) else content
            except ValueError:
                payload = content
            if call['name'] == f'mcp__{server}__search_contracts':
                def visit(value):
                    if isinstance(value, dict):
                        conid = value.get('contract_id', value.get('conid', value.get('con_id')))
                        symbol = value.get('ticker', value.get('symbol'))
                        if conid is not None and symbol:
                            contracts[str(conid)] = symbol
                        for child in value.values():
                            visit(child)
                    elif isinstance(value, list):
                        for child in value:
                            visit(child)
                visit(payload)
                continue
            origin = dict(provider='IBKR', broker_response=payload, broker_tool=call['name'],
                          broker_input=call['input'], transcript=str(Path(path).resolve()),
                          transcript_line=number, tool_use_id=block['tool_use_id'])
            if block.get('is_error') or not isinstance(payload, dict) or not isinstance(payload.get('bars'), list):
                rows.append(dict(origin, error='Historical tool error or unsupported payload. Original response retained; no verified split-only bars.'))
                continue
            for index, native in enumerate(payload['bars']):
                if not isinstance(native, dict):
                    rows.append(dict(origin, error='Unsupported daily bar. Original response retained.'))
                    continue
                bar = {key: native.get(key, payload.get(key)) for key in
                       ('ticker', 'date', 'close', 'adjusted_close', 'adjustment')}
                bar['ticker'] = bar.get('ticker') or payload.get('symbol') or contracts.get(str(call['input'].get('contract_id')))
                if not all(bar.get(k) is not None for k in ('ticker', 'date', 'close')):
                    rows.append(dict(origin, broker_index=index,
                        error='Plain OHLCV missing ticker, date or close; close convention unavailable.'))
                    break
                if bar.get('adjustment') != 'split_only' or bar.get('adjusted_close') is None:
                    bar = {k: bar[k] for k in ('ticker', 'date', 'close')}
                    bar['purpose'] = 'independent_check_only'
                rows.append(dict(bar, **origin, broker_index=index))
    if not rows:
        raise ValueError('No historical IBKR tool results. Assistant-generated bars are not primary evidence.')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tickers', nargs='+', required=True)
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--saved', type=Path, help='Offline saved broker JSONL; makes no connection')
    parser.add_argument('--transcript', type=Path, help='Saved Claude stream containing original IBKR tool results')
    parser.add_argument('--server', default='ibkr')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    try:
        query = request(args.tickers, args.since, args.until)
        folder = ROOT / 'data/refclass/raw/ibkr' / date.today().isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        key = '-'.join(query['tickers']) + '_' + args.since + '_' + args.until
        output = folder / (key + '.jsonl')
        if args.prepare:
            prompt = folder / (key + '.request.md')
            prompt.write_text(
                'Use the existing IBKR read-only connection to resolve tickers to contract IDs, then call '
                'get_price_history with each contract ID, period FIVE_YEARS and daily bars. '
                'The period is counted back from today. There is no end-date parameter; never invent one '
                'or attempt historical pagination. Requested tickers and dates: ' + json.dumps(query) + '. '
                'Include XBI. Tool responses are captured directly; do not transform OHLCV into adjusted_close, '
                'invent split factors or claim that plain closes have a verified adjustment convention. '
                'Plain OHLCV closes are retained only for the independent comparison with Massive. Missing history and symbols remain explicit gaps. '
                'Do not use current quotes, reports or the web as historical prices.\n' +
                '\n'.join(capability_gaps(query)) + '\n')
            print(prompt); print(output)
            return 0
        if args.saved is None and args.transcript is None:
            raise ValueError('Use ./run.sh refclass fetch-bars for the live connection, or --saved offline.')
        with job_lock(folder / '.fetch.lock'):
            # Validate before saving, but allow missing-ticker gaps to be retained.
            lines = ('\n'.join(json.dumps(row) for row in transcript_bars(args.transcript, args.server)) + '\n'
                     if args.transcript else args.saved.read_text())
            for line in lines.splitlines():
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('Broker JSONL must contain objects.')
            if args.saved is None or args.saved.resolve() != output.resolve():
                if output.exists() and output.read_text() != lines:
                    raise ValueError('Existing raw download differs. Preserve it and use a new download date.')
                output.write_text(lines)
            result = collect(output, **query)
            result['gaps'].extend(capability_gaps(query))
            result['complete'] = not result['gaps']
            result['gap_count'] = len(result['gaps']) + len(result['coverage_gaps'])
            (folder / (key + '.collection.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(f'Saved {output}. Bar gaps {len(result["gaps"])}.')
        return 1 if result['gaps'] else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Stopped. {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
