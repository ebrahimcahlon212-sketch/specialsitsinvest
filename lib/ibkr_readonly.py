"""Fail-closed PreToolUse guard for Claude sessions with the IBKR connection.

The CLI allowlist limits automatic permissions. This hook also rejects mutation
calls if an inherited permission or another MCP connection would allow them.
"""
import argparse
import json
from pathlib import Path
import shlex
import sys

BUILTINS = ('Read', 'Glob', 'Grep')
CONTRACTS = ('search_contracts',)
MODES = {
    'ibkr-bars': CONTRACTS + ('get_price_history',),
    'ibkr': CONTRACTS + ('get_price_snapshot', 'get_account_positions', 'get_account_balances', 'get_account_summary'),
}


def allowed(server, mode):
    return list(BUILTINS) + [f'mcp__{server}__{name}' for name in MODES[mode]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--policy', action='store_true')
    parser.add_argument('--allowlist', action='store_true')
    args = parser.parse_args()
    if args.allowlist:
        print(','.join(allowed(args.server, args.mode)))
        return 0
    if args.policy:
        command = shlex.join([sys.executable, str(Path(__file__).resolve()),
                              '--server', args.server, '--mode', args.mode])
        print(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': '*', 'hooks': [{'type': 'command', 'command': command}]}]}}))
        return 0
    try:
        name = json.load(sys.stdin)['tool_name']
        if name in allowed(args.server, args.mode):
            return 0
    except (ValueError, KeyError, TypeError):
        pass
    print('Denied. This broker session permits only explicitly listed read tools.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
