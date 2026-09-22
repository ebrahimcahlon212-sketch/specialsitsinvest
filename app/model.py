"""One bounded ChatGPT subscription turn through the already verified Codex client.

The model sandbox permits broad reads and denies writes. Disabled capabilities
reduce exposure; observing no tool events does not prove universal containment.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event
import time
import tomllib
from datetime import datetime, timezone

from . import constants
from .constants import MODEL_NAME, MODEL_EFFORT


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _home():
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()


def _settings():
    settings = {
        'forced_login_method': 'chatgpt', 'model_provider': 'openai',
        'web_search': 'disabled', 'agents.enabled': False, 'apps._default.enabled': False,
        'analytics.enabled': False, 'feedback.enabled': False, 'history.persistence': 'none',
        'project_doc_max_bytes': 0, 'approval_policy': 'never', 'approvals_reviewer': 'user',
        'allow_login_shell': False, 'default_permissions': 'ir_readonly',
        'shell_environment_policy.inherit': 'none', 'model': constants.MODEL_NAME,
        'model_reasoning_effort': constants.MODEL_EFFORT, 'model_reasoning_summary': 'none',
    }
    settings.update({'features.' + name: False for name in constants.CODEX_DISABLED_FEATURES})
    config_file = _home() / 'config.toml'
    try:
        config = tomllib.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
    except (OSError, ValueError):
        raise ValueError('The existing Codex configuration could not be read safely.') from None
    for name in config.get('mcp_servers', {}):
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
            raise ValueError('A connector name cannot be safely disabled by this installed client.')
        settings['mcp_servers.' + name + '.enabled'] = False
    return settings


def runtime_context():
    """Cache identity without reading authentication files or saving config contents."""
    binary = constants.CODEX_BINARY
    if not binary.is_file():
        raise ValueError('The verified Codex runtime is missing. No replacement was selected.')
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != constants.CODEX_SHA256:
        raise ValueError('The Codex runtime changed; its permissions need verification before use.')
    files = [_home() / name for name in ('config.toml', 'AGENTS.md', 'AGENTS.override.md',
                                        'requirements.toml', 'managed_config.toml')]
    files.extend(binary.parent / name for name in ('config.toml', 'default-config.toml'))
    for directory in (Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / 'OpenAI' / 'Codex',
                      Path('/etc/codex')):
        files.extend(directory / name for name in ('config.toml', 'requirements.toml', 'managed_config.toml'))
    inputs = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
              for path in files}
    context = {'version': constants.CODEX_VERSION, 'runtime_sha256': digest,
               'settings_sha256': _hash(_settings()), 'configuration_files': inputs,
               'read_access': 'broad', 'writes': 'denied', 'environments': [],
               'deadline_seconds': constants.MODEL_DEADLINE_SECONDS, 'application_retries': 0}
    context['fingerprint'] = _hash(context)
    return context


def _environment():
    env = os.environ.copy()
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'CODEX_ACCESS_TOKEN',
                 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CODEX_APP_TOOLS_PIPE_PATH'):
        env.pop(name, None)
    return env


def _arguments(settings, work):
    config = {**settings, 'log_dir': str(work / 'logs'), 'sqlite_home': str(work / 'state')}
    args = []
    for key, value in config.items():
        args.extend(['-c', key + '=' + json.dumps(value)])
    args.extend(['-c', 'permissions.ir_readonly.filesystem={":root"="read"}',
                 '-c', 'permissions.ir_readonly.network.enabled=false'])
    return args


def _check_config(config, expected):
    for key, value in expected.items():
        current = config
        for segment in key.split('.'):
            current = current.get(segment) if isinstance(current, dict) else None
        if current != value:
            raise ValueError('Required Codex setting was not confirmed: ' + key)
    if any(value.get('enabled', True) is not False for value in (config.get('mcp_servers') or {}).values()):
        raise ValueError('An inherited connector remains enabled; no model request was submitted.')


def _allowance(value):
    return {key: value.get(key) for key in ('ordinaryUsageAllowed', 'rateLimits', 'rateLimitsByLimitId')}


def _error_text(exc):
    # Only our own exceptions carry messages. Never persist raw RPC errors/stderr,
    # which can contain configuration values, credentials or document contents.
    return str(exc) if type(exc) in (ValueError, RuntimeError) else 'Codex transport failed: ' + type(exc).__name__


def subscription_status(data_dir, cancel_event=None, progress=None):
    return asyncio.run(_session(Path(data_dir), None, cancel_event or Event(), progress))


def generate(data_dir, request, cancel_event, progress):
    return asyncio.run(_session(Path(data_dir), request, cancel_event, progress))


async def _session(data_dir, request, cancel_event, progress):
    result = {'status': 'failed', 'response_text': None, 'usage': None, 'error': None,
              'submitted': False, 'retries': [], 'tool_activity': [], 'metadata': {}}
    meta = result['metadata']
    status = {'auth_type': None, 'plan': None, 'allowance': None, 'model_available': False,
              'checked_at': datetime.now(timezone.utc).isoformat(), 'error': None}
    proc = None
    reader = None
    drainer = None
    thread_id = turn_id = None
    completed = False
    identity = 0
    deadline = time.monotonic() + constants.MODEL_SETUP_SECONDS
    messages = []

    def report(message, submitted=False, usage=None):
        if progress:
            progress(message, submitted=submitted, usage=usage)

    async def send(value):
        proc.stdin.write((json.dumps(value, ensure_ascii=True) + '\n').encode())
        await asyncio.wait_for(proc.stdin.drain(), max(.01, deadline - time.monotonic()))

    async def observe(message):
        nonlocal turn_id, completed
        method, params = message.get('method', ''), message.get('params') or {}
        if 'id' in message and method:
            result['tool_activity'].append({'server_request': method, 'action': 'rejected'})
            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                await send({'id': message['id'], 'result': {'decision': 'decline'}})
            else:
                await send({'id': message['id'], 'error': {'code': -32000, 'message': 'Disabled for document analysis'}})
            raise RuntimeError('Unexpected server request rejected: ' + method)
        if method == 'error':
            error = params.get('error') or {}
            result['retries'].append({'will_retry': params.get('willRetry'), 'error_type': error.get('codexErrorInfo')})
            report('Codex reported a retry or connection error; the original deadline still applies.', result['submitted'], result['usage'])
        if method == 'thread/tokenUsage/updated':
            result['usage'] = params.get('tokenUsage')
            report('Receiving the structured response.', result['submitted'], result['usage'])
        if method in ('model/rerouted', 'model/verification'):
            meta['unexpected_model_event'] = method
            raise RuntimeError('Unexpected model event; the response was rejected: ' + method)
        if method == 'turn/started':
            turn_id = params.get('turn', {}).get('id', turn_id)
        if method in ('item/started', 'item/completed'):
            item = params.get('item') or {}
            if item.get('type') not in ('userMessage', 'agentMessage', 'reasoning'):
                result['tool_activity'].append({'event': method, 'type': item.get('type')})
                raise RuntimeError('Unexpected tool activity; the response was rejected.')
            if method == 'item/completed' and item.get('type') == 'agentMessage':
                messages.append(item.get('text', ''))
        if method == 'turn/completed':
            completed = True
            turn = params.get('turn') or {}
            meta['turn_status'] = turn.get('status')
            meta['turn_error_type'] = (turn.get('error') or {}).get('codexErrorInfo')
            for item in turn.get('items', []):
                if item.get('type') not in ('userMessage', 'agentMessage', 'reasoning'):
                    result['tool_activity'].append({'event': method, 'type': item.get('type')})
                    raise RuntimeError('Unexpected tool activity; the response was rejected.')
                if item.get('type') == 'agentMessage' and item.get('text') not in messages:
                    messages.append(item.get('text', ''))

    async def read_message(stopping=False):
        nonlocal reader
        if cancel_event.is_set() and not stopping:
            raise asyncio.CancelledError
        if time.monotonic() >= deadline:
            raise TimeoutError
        if reader is None:
            reader = asyncio.create_task(proc.stdout.readline())
        while not reader.done():
            if cancel_event.is_set() and not stopping:
                raise asyncio.CancelledError
            if time.monotonic() >= deadline:
                raise TimeoutError
            await asyncio.wait({reader}, timeout=min(.1, max(0, deadline - time.monotonic())))
        line = reader.result()
        reader = None
        if not line:
            raise RuntimeError('Codex closed before confirming completion. Usage may be unknown.')
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError):
            raise RuntimeError('Codex returned an invalid protocol message.') from None
        await observe(message)
        return message

    async def rpc(method, params, stopping=False):
        nonlocal identity
        identity += 1
        expected = identity
        await send({'id': expected, 'method': method, 'params': params})
        while True:
            message = await read_message(stopping)
            if message.get('id') == expected:
                if 'error' in message:
                    raise RuntimeError('Codex ' + method + ' failed (RPC code ' + str(message['error'].get('code')) + ').')
                return message.get('result') or {}

    async def interrupt():
        nonlocal deadline
        if not result['submitted'] or completed:
            return
        deadline = time.monotonic() + constants.MODEL_CANCEL_SECONDS
        meta['cancellation_confirmed'] = False
        try:
            # turn/started can arrive after turn/start was submitted but before its reply.
            while not turn_id and not completed:
                await read_message(stopping=True)
            if completed:
                meta['cancellation_confirmed'] = True
                return
            meta['interrupt_requested'] = True
            await rpc('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, stopping=True)
            while not completed:
                await read_message(stopping=True)
            meta['cancellation_confirmed'] = True
        except (RuntimeError, ValueError, TimeoutError):
            pass

    async def drain_errors():
        # Consume, but do not log potentially sensitive client diagnostic text.
        while await proc.stderr.read(4096):
            pass

    with tempfile.TemporaryDirectory(prefix='InvestResearch-codex-') as directory:
        work = Path(directory)
        try:
            if cancel_event.is_set():
                raise asyncio.CancelledError
            context = runtime_context()
            meta['runtime_context'] = context
            if request and (request.get('model') != constants.MODEL_NAME or request.get('effort') != constants.MODEL_EFFORT):
                raise ValueError('Only the verified Luna model with low reasoning is enabled.')
            if request and request.get('runtime_context', {}).get('fingerprint') != context['fingerprint']:
                raise ValueError('Codex configuration changed after this request was prepared. Prepare it again.')
            settings = _settings()
            report('Checking the ChatGPT subscription and read-only configuration.')
            proc = await asyncio.wait_for(asyncio.create_subprocess_exec(
                str(constants.CODEX_BINARY), 'app-server', '--listen', 'stdio://', *_arguments(settings, work),
                cwd=work, env=_environment(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=constants.MODEL_MAX_PROTOCOL_BYTES,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)), max(.01, deadline - time.monotonic()))
            drainer = asyncio.create_task(drain_errors())
            initialized = await rpc('initialize', {'clientInfo': {'name': 'investresearch_summary', 'version': '1'},
                                                  'capabilities': {'experimentalApi': True}})
            if constants.CODEX_VERSION not in initialized.get('userAgent', ''):
                raise ValueError('The running Codex version differs from the verified runtime.')
            await send({'method': 'initialized', 'params': {}})
            account = (await rpc('account/read', {'refreshToken': False})).get('account') or {}
            status.update(auth_type=account.get('type'), plan=account.get('planType'))
            if status['auth_type'] != 'chatgpt':
                raise ValueError('ChatGPT subscription login is required in the installed Codex client. API access is disabled.')
            status['allowance'] = _allowance(await rpc('account/rateLimits/read', {}))
            meta['auth'] = {'type': status['auth_type'], 'plan': status['plan']}
            meta['allowance_before'] = status['allowance']
            available = await rpc('model/list', {'limit': 100, 'includeHidden': True})
            selected = next((value for value in available.get('data', []) if value.get('model') == constants.MODEL_NAME), None)
            status['model_available'] = bool(selected and any(value.get('reasoningEffort') == constants.MODEL_EFFORT
                                                            for value in selected.get('supportedReasoningEfforts', [])))
            config_reply = await rpc('config/read', {'includeLayers': True})
            _check_config(config_reply.get('config') or {}, settings)
            meta['effective_config_sha256'] = _hash(str(config_reply.get('config')).replace(str(work), '<temporary-runtime>'))
            for layer in config_reply.get('layers') or []:
                source = layer.get('name') or {}
                filename = source.get('file')
                if filename and str(Path(filename).resolve()) not in context['configuration_files']:
                    raise ValueError('An additional Codex configuration source needs review before generation.')
                if source.get('type') in ('enterpriseManaged', 'mdm', 'legacyManagedConfigTomlFromMdm'):
                    raise ValueError('Managed Codex configuration needs review before generation.')
            if not request:
                return status
            if status['allowance'].get('ordinaryUsageAllowed') is not True:
                raise ValueError('Included subscription allowance is not confirmed. No request or paid fallback was made.')
            if not status['model_available']:
                raise ValueError('Luna with low reasoning is unavailable. No substitute was selected.')
            start = await rpc('thread/start', {
                'model': constants.MODEL_NAME, 'modelProvider': 'openai', 'allowProviderModelFallback': False,
                'ephemeral': True, 'cwd': str(work), 'permissions': 'ir_readonly', 'approvalPolicy': 'never',
                'approvalsReviewer': 'user', 'environments': [], 'dynamicTools': [], 'selectedCapabilityRoots': [],
                'baseInstructions': request['prompt'], 'developerInstructions': request['prompt']})
            thread_id = start['thread']['id']
            if start.get('model') != constants.MODEL_NAME or start.get('modelProvider') != 'openai':
                raise ValueError('Model or provider substitution was rejected before submission.')
            if start.get('approvalPolicy') != 'never' or start.get('approvalsReviewer') != 'user':
                raise ValueError('Automatic approval review was not disabled.')
            if start.get('sandbox', {}).get('type') != 'readOnly' or start.get('sandbox', {}).get('networkAccess', False):
                raise ValueError('Read-only permissions without command network access were not confirmed.')
            inherited = {}
            for filename in start.get('instructionSources') or []:
                path = str(Path(filename).resolve())
                if path not in context['configuration_files']:
                    raise ValueError('An additional inherited instruction source needs review before generation.')
                inherited[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                if inherited[path] != context['configuration_files'][path]:
                    raise ValueError('Inherited instructions changed while preparing the request.')
            meta['inherited_instruction_hashes'] = inherited
            meta['thread_settings'] = {key: start.get(key) for key in ('model', 'modelProvider', 'sandbox', 'activePermissionProfile')}
            if cancel_event.is_set():
                raise asyncio.CancelledError
            # Persist intent before bytes can leave. A lost reply is not permission to retry.
            report('Submitting one Luna document-analysis request.', submitted=True)
            if cancel_event.is_set():
                raise asyncio.CancelledError
            result['submitted'] = True
            started = time.monotonic()
            deadline = started + constants.MODEL_DEADLINE_SECONDS
            turn = await rpc('turn/start', {'threadId': thread_id, 'model': constants.MODEL_NAME, 'effort': constants.MODEL_EFFORT,
                'environments': [], 'permissions': 'ir_readonly', 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                'serviceTierForTurn': 'default', 'summary': 'none',
                'input': [{'type': 'text', 'text': request['input_text']}], 'outputSchema': request['output_schema']})
            turn_id = turn.get('turn', {}).get('id', turn_id)
            while not completed:
                await read_message()
            meta['elapsed_seconds'] = round(time.monotonic() - started, 3)
            if meta.get('turn_status') != 'completed':
                raise RuntimeError('Codex did not complete the response. Usage may be incomplete.')
            if not messages or not messages[-1].strip():
                raise RuntimeError('Codex completed without a response; no result was saved.')
            result.update(status='completed', response_text=messages[-1])
        except asyncio.CancelledError:
            result.update(status='cancelled', error='Cancelled. The request will not restart automatically.')
            status['error'] = result['error']
        except TimeoutError:
            result.update(status='timed_out', error='The bounded Codex deadline was reached. No automatic retry was made.')
            status['error'] = result['error']
        except Exception as exc:
            result['error'] = status['error'] = _error_text(exc)
        finally:
            if proc:
                await interrupt()
                if reader:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                if proc.returncode is None:
                    proc.stdin.close()
                    try:
                        await asyncio.wait_for(proc.wait(), 2)
                    except TimeoutError:
                        proc.terminate()
                        meta['client_terminated'] = True
                        try:
                            await asyncio.wait_for(proc.wait(), 2)
                        except TimeoutError:
                            proc.kill()
                            await asyncio.wait_for(proc.wait(), 2)
                if drainer:
                    await asyncio.gather(drainer, return_exceptions=True)
    return result if request else status
