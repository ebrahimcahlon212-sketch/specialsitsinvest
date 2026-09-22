"""Saved Luna response; synthetic protocol envelopes. No automated live requests."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace

import pytest

from app import constants, model


# Actual response saved by the owner's 20 September 2026 subscription probe.
SAVED_RESPONSE = {
    'summary': 'The holding period for Spinco common stock received by WDC stockholders includes the holding period of the corresponding WDC common stock.',
    'quote': 'the holding period with respect to shares of Spinco common stock received by WDC stockholders (including any\nfractional shares deemed received, as discussed below) will include the holding period of the WDC common stock with respect to which such Spinco common stock was received;',
}
SAVED_USAGE = {'total': {'totalTokens': 2951, 'inputTokens': 2854, 'outputTokens': 97},
               'last': {'totalTokens': 2951, 'inputTokens': 2854, 'outputTokens': 97}}


@pytest.fixture
def protocol(monkeypatch, tmp_path):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'synthetic-codex-home'))
    context = {'fingerprint': 'synthetic-context', 'configuration_files': {}}
    monkeypatch.setattr(model, 'runtime_context', lambda: context)
    monkeypatch.setattr(constants, 'MODEL_CANCEL_SECONDS', .15)
    controls = {'auth': 'chatgpt', 'allowance': True, 'model': constants.MODEL_NAME,
                'sandbox': {'type': 'readOnly', 'networkAccess': False}, 'mode': 'complete'}
    sent = []
    launches = []
    cancel = Event()
    config = {}
    for key, value in model._settings().items():
        parent = config
        segments = key.split('.')
        for segment in segments[:-1]:
            parent = parent.setdefault(segment, {})
        parent[segments[-1]] = value

    async def spawn(*args, **kwargs):
        launches.append((args, kwargs))
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        proc = SimpleNamespace(stdout=stdout, stderr=stderr, returncode=None)

        def emit(value):
            stdout.feed_data((json.dumps(value) + '\n').encode())

        def completed(state='completed'):
            emit({'method': 'turn/completed', 'params': {'turn': {'id': 'synthetic-turn', 'status': state,
                 'items': [{'type': 'agentMessage', 'text': json.dumps(SAVED_RESPONSE)}] if state == 'completed' else []}}})

        def write(line):
            message = json.loads(line)
            sent.append(message)
            method = message.get('method')
            reply = {}
            if method == 'initialize':
                reply = {'userAgent': 'Codex Desktop/' + constants.CODEX_VERSION}
            elif method == 'account/read':
                reply = {'account': {'type': controls['auth'], 'planType': 'pro', 'email': 'must-not-be-saved@example.invalid'}}
            elif method == 'account/rateLimits/read':
                reply = {'ordinaryUsageAllowed': controls['allowance'], 'rateLimits': {'primary': {'usedPercent': 7}}}
            elif method == 'model/list':
                reply = {'data': [{'model': controls['model'], 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]}
            elif method == 'config/read':
                reply = {'config': config, 'layers': []}
            elif method == 'thread/start':
                reply = {'thread': {'id': 'synthetic-thread'}, 'model': controls['model'], 'modelProvider': 'openai',
                         'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandbox': controls['sandbox'],
                         'instructionSources': []}
            elif method == 'turn/start':
                reply = {'turn': {'id': 'synthetic-turn'}}
            elif method == 'turn/interrupt':
                emit({'id': message['id'], 'result': {}})
                if controls['mode'] != 'no-cancel-ack':
                    completed('interrupted')
                return
            if 'id' in message and method:
                emit({'id': message['id'], 'result': reply})
            if method == 'turn/start':
                emit({'method': 'turn/started', 'params': {'turn': {'id': 'synthetic-turn'}}})
                if controls['mode'] != 'missing-usage':
                    emit({'method': 'thread/tokenUsage/updated', 'params': {'tokenUsage': SAVED_USAGE}})
                if controls['mode'] == 'tool':
                    emit({'id': 'synthetic-approval', 'method': 'item/commandExecution/requestApproval', 'params': {'command': 'never executed'}})
                elif controls['mode'] == 'reroute':
                    emit({'method': 'model/rerouted', 'params': {'toModel': 'another-model'}})
                elif controls['mode'] == 'retry':
                    emit({'method': 'error', 'params': {'willRetry': True, 'error': {'codexErrorInfo': 'serverOverloaded', 'message': 'secret-should-not-persist'}}})
                    completed()
                elif controls['mode'] in ('cancel', 'no-cancel-ack'):
                    asyncio.get_running_loop().call_later(.01, cancel.set)
                elif controls['mode'] != 'timeout':
                    completed()

        async def drain():
            pass

        def close():
            if proc.returncode is None:
                proc.returncode = 0
                stdout.feed_eof()
                stderr.feed_eof()

        async def wait():
            return proc.returncode

        proc.stdin = SimpleNamespace(write=write, drain=drain, close=close)
        proc.wait, proc.terminate, proc.kill = wait, close, close
        return proc

    monkeypatch.setattr(model.asyncio, 'create_subprocess_exec', spawn)
    request = {'model': constants.MODEL_NAME, 'effort': 'low', 'prompt': 'Synthetic protocol test: answer from source only.',
               'prompt_version': 'synthetic-1', 'input_text': SAVED_RESPONSE['quote'],
               'output_schema': {'type': 'object'}, 'runtime_context': context}
    return SimpleNamespace(controls=controls, sent=sent, launches=launches, cancel=cancel,
                           request=request, folder=tmp_path, config=config)


def run(protocol, progress=None):
    return model.generate(protocol.folder, protocol.request, protocol.cancel, progress)


def test_saved_response_completes_once_with_usage_and_read_only_controls(protocol):
    updates = []
    result = run(protocol, lambda message, **values: updates.append(values))
    assert result['status'] == 'completed'
    assert json.loads(result['response_text']) == SAVED_RESPONSE
    assert SAVED_RESPONSE['quote'] in protocol.request['input_text']
    assert result['usage'] == SAVED_USAGE
    assert result['tool_activity'] == []
    assert 'must-not-be-saved' not in json.dumps(result)
    turns = [value for value in protocol.sent if value.get('method') == 'turn/start']
    assert len(turns) == 1
    assert turns[0]['params']['environments'] == []
    assert turns[0]['params']['approvalPolicy'] == 'never'
    assert turns[0]['params']['approvalsReviewer'] == 'user'
    start = next(value['params'] for value in protocol.sent if value.get('method') == 'thread/start')
    assert start['allowProviderModelFallback'] is False and start['ephemeral'] is True
    assert updates[0]['submitted'] is False
    assert any(value['submitted'] for value in updates)


@pytest.mark.parametrize('key,value,error', [
    ('auth', 'apiKey', 'subscription login'), ('allowance', False, 'allowance'),
    ('model', 'another-model', 'unavailable'),
    ('sandbox', {'type': 'dangerFullAccess'}, 'Read-only'),
    ('sandbox', {'type': 'readOnly', 'networkAccess': True}, 'Read-only'),
])
def test_unverified_auth_allowance_model_or_permissions_never_submit(protocol, key, value, error):
    protocol.controls[key] = value
    result = run(protocol)
    assert result['status'] == 'failed' and error in result['error']
    assert result['submitted'] is False
    assert not any(value.get('method') == 'turn/start' for value in protocol.sent)


def test_enabled_connector_and_feature_fail_before_submission(protocol):
    protocol.config['mcp_servers'] = {'synthetic': {'enabled': True}}
    result = run(protocol)
    assert 'connector remains enabled' in result['error']
    protocol.config.pop('mcp_servers')
    protocol.config['features']['shell_tool'] = True
    assert 'features.shell_tool' in run(protocol)['error']
    assert not any(value.get('method') == 'turn/start' for value in protocol.sent)


def test_cancel_before_start_or_during_submission_callback_does_not_send(protocol):
    protocol.cancel.set()
    assert run(protocol)['status'] == 'cancelled'
    assert protocol.launches == []
    protocol.cancel.clear()
    def progress(message, submitted=False, usage=None):
        if submitted:
            protocol.cancel.set()
    result = run(protocol, progress)
    assert result['status'] == 'cancelled' and result['submitted'] is False
    assert not any(value.get('method') == 'turn/start' for value in protocol.sent)


@pytest.mark.parametrize('mode,status', [('cancel', 'cancelled'), ('timeout', 'timed_out'), ('no-cancel-ack', 'cancelled')])
def test_cancel_and_deadline_interrupt_once_without_restart(protocol, monkeypatch, mode, status):
    protocol.controls['mode'] = mode
    monkeypatch.setattr(constants, 'MODEL_DEADLINE_SECONDS', .05)
    result = run(protocol)
    assert result['status'] == status and result['submitted'] is True
    assert result['response_text'] is None
    assert result['usage'] == SAVED_USAGE
    methods = [value.get('method') for value in protocol.sent]
    assert methods.count('turn/start') == 1 and methods.count('turn/interrupt') == 1
    assert result['metadata']['cancellation_confirmed'] is (mode != 'no-cancel-ack')


@pytest.mark.parametrize('mode', ['tool', 'reroute'])
def test_unexpected_activity_fails_and_interrupts(protocol, mode):
    protocol.controls['mode'] = mode
    result = run(protocol)
    assert result['status'] == 'failed' and result['response_text'] is None
    assert sum(value.get('method') == 'turn/start' for value in protocol.sent) == 1
    assert any(value.get('method') == 'turn/interrupt' for value in protocol.sent)
    if mode == 'tool':
        assert result['tool_activity'][0]['action'] == 'rejected'
        assert any(value.get('result') == {'decision': 'decline'} for value in protocol.sent)


def test_retry_is_recorded_without_application_retry_and_usage_can_be_unknown(protocol):
    protocol.controls['mode'] = 'retry'
    result = run(protocol)
    assert result['retries'] == [{'will_retry': True, 'error_type': 'serverOverloaded'}]
    assert 'secret-should-not-persist' not in json.dumps(result)
    assert sum(value.get('method') == 'turn/start' for value in protocol.sent) == 1
    protocol.controls['mode'] = 'missing-usage'
    assert run(protocol)['usage'] is None


def test_status_uses_no_thread_or_generation(protocol):
    result = model.subscription_status(protocol.folder)
    assert result['auth_type'] == 'chatgpt' and result['plan'] == 'pro'
    assert result['model_available'] is True and result['error'] is None
    assert not any(value.get('method') in ('thread/start', 'turn/start') for value in protocol.sent)
