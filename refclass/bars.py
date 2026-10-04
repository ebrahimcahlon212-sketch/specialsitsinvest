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


def transcript_bars(path, server):
    """Only tool results, never assistant text, can become broker bar inputs.

    Require explicit broker price conventions. Unsupported live schemas are gaps,
    not permission to invent split factors. Original tool payloads are retained.
    """
    calls, rows = {}, []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        message = json.loads(line)
        for block in message.get('message', {}).get('content', []):
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                name = block.get('name', '')
                if name.startswith('mcp__' + server + '__') and re.search(r'histor|daily.*bar', name, re.I) and not re.search(r'order|cancel|trade', name, re.I):
                    calls[block['id']] = name
            if block.get('type') != 'tool_result' or block.get('tool_use_id') not in calls or block.get('is_error'):
                continue
            content = block.get('content')
            if isinstance(content, list):
                content = ''.join(c.get('text', '') for c in content if c.get('type') == 'text')
            payload = json.loads(content) if isinstance(content, str) else content
            if not isinstance(payload, dict) or not isinstance(payload.get('bars'), list):
                raise ValueError('Unsupported historical broker response schema. Preserve transcript for mapping review.')
            for index, native in enumerate(payload['bars']):
                bar = {key: native.get(key, payload.get(key)) for key in
                       ('ticker', 'date', 'close', 'adjusted_close', 'adjustment')}
                if any(v is None for v in bar.values()) or bar['adjustment'] != 'split_only':
                    raise ValueError('Broker did not explicitly supply both close conventions. Mapping review required.')
                bar.update(provider='IBKR', broker_response=payload, broker_index=index,
                           broker_tool=calls[block['tool_use_id']], transcript=str(Path(path).resolve()),
                           transcript_line=number, tool_use_id=block['tool_use_id'])
                rows.append(bar)
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
                'Use only the existing IBKR connection, read-only historical market data tools. Never call '
                'order, cancellation or account mutation tools. Fetch regular-session daily historical bars for '
                + json.dumps(query) + '. Include XBI. Preserve the broker session dates. '
                'Return one JSON object per daily bar with provider="IBKR", ticker, date (YYYY-MM-DD), '
                'close (unadjusted), adjusted_close (split-only), adjustment="split_only", and '
                'broker_contract identifying the returned contract. Never use dividend-adjusted closes. '
                'Do not invent adjustment factors, dates or missing bars. If the tool cannot provide both '
                'price conventions, return an error object with ticker and reason instead. '
                'Copy numbers exactly from the response. Do not use current quotes, reports or the web. '
                'Put JSON lines between <<<BEGIN OUTPUT>>> and <<<END OUTPUT>>>.\n')
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
            (folder / (key + '.collection.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(f'Saved {output}. Bar gaps {len(result["gaps"])}.')
        return 1 if result['gaps'] else 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Stopped. {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
