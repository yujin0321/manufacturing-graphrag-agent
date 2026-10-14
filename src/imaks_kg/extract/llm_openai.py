"""GPT-6.1 Sol Responses API adapter; one HTTP request per budgeted attempt."""
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from copy import deepcopy

from imaks_kg.extract import llm
from imaks_kg.extract.common import ExtractError, safe_name
from imaks_kg.settings import DOTENV_FILE

MODEL_ID = 'gpt-6.1-sol'
MAX_OUTPUT_TOKENS = 16000
EFFORT = 'low'
TIMEOUT_S = 600.0
ENDPOINT = 'https://api.openai.com/v1/responses'
KEY_ENV = 'OPENAI_API_KEY'
OUTBOUND_DOCS = ('SOP-001', 'SOP-002', 'SOP-003', 'SOP-004')


def api_key():
    value = os.environ.get(KEY_ENV, '').strip()
    if value:
        return value
    if DOTENV_FILE.is_file():
        for line in DOTENV_FILE.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line.startswith('export '):
                line = line[7:]
            name, sep, value = line.partition('=')
            if sep and name.strip() == KEY_ENV:
                value = value.strip()
                if value[:1] in ('"', "'") and value[-1:] == value[:1]:
                    return value[1:-1].strip()
                return value.split(' #', 1)[0].strip()
    return ''


def redact(text):
    text = str(text)
    key = api_key()
    if key:
        text = text.replace(key, '[REDACTED]')
    return re.sub(r'sk-[A-Za-z0-9_-]+', '[REDACTED]', text)[:1000]


class OpenAIError(Exception):
    def __init__(self, message, status=None, body=None, headers=None):
        super().__init__(redact(message))
        self.status, self.body, self.headers = status, body or {}, headers or {}


class OpenAIClient:
    def __init__(self, transport=None):
        if not api_key():
            raise ExtractError(f'{KEY_ENV}가 환경변수 또는 .env에 없어 실제 호출을 거부함')
        self.transport = transport or urllib.request.urlopen

    def create(self, request, key):
        req = urllib.request.Request(ENDPOINT, data=json.dumps(request).encode('utf-8'),
              headers={'Authorization': 'Bearer ' + api_key(), 'Content-Type': 'application/json'}, method='POST')
        try:
            with self.transport(req, timeout=TIMEOUT_S) as response:
                raw = response.read().decode('utf-8')
                headers = dict(response.headers)
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode('utf-8'))
            except (ValueError, UnicodeError):
                body = {}
            error = body.get('error') or {}
            raise OpenAIError(error.get('message', 'OpenAI HTTP error'), e.code, body, dict(e.headers)) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            raise OpenAIError(f'응답 수신 여부 불명: {type(e).__name__}') from None
        try:
            data = json.loads(raw)
        except ValueError:
            # HTTP 200 body must still be saved by call_with_policy before parsing fails.
            data = {'status': 'invalid_json', 'raw_body': raw}
        if not isinstance(data, dict):
            data = {'status': 'invalid_json', 'raw_body': raw}
        data['_request_id'] = headers.get('x-request-id', headers.get('X-Request-Id', ''))
        return data


def classify(error):
    status = error.status
    details = error.body.get('error') or {}
    code = str(details.get('code') or details.get('type') or '')
    message = redact(error)
    info = llm.ErrorInfo(llm.AMBIGUOUS, type(error).__name__, status=status,
                         error_type=code, message=message)
    if status in (401, 403):
        info.error_class = llm.FATAL_AUTH
    elif status == 402 or code in ('insufficient_quota', 'billing_hard_limit_reached'):
        info.error_class = llm.FATAL_BILLING
    elif status in (429, 503):
        if any(x in message.lower() for x in ('billing', 'credit', 'usage limit', 'spend limit')):
            info.error_class = llm.FATAL_BILLING
        else:
            info.error_class = llm.TRANSIENT_RATE
            try:
                info.retry_after_s = float(error.headers.get('retry-after', error.headers.get('Retry-After', '')))
            except (TypeError, ValueError):
                pass
    elif status is not None and 400 <= status < 500:
        info.error_class = llm.FATAL_REQUEST
    else:
        info.message = llm.USAGE_CHECK_NOTE + '; ' + message
    return info


def interpret(key, raw):
    result = llm.CallResult(key=key, ok=False, raw=deepcopy(raw), http_200=True,
             served_model=raw.get('model') or '', request_id=raw.get('_request_id') or raw.get('id') or '',
             stop_reason=raw.get('status') or '', usage=deepcopy(raw.get('usage') or {}))
    if result.stop_reason != 'completed':
        result.failure = 'OpenAI status=' + result.stop_reason
        return result
    if not re.fullmatch(re.escape(MODEL_ID) + r'(-\d{3})?', result.served_model):
        result.failure = '요청한 모델과 실제 응답 모델이 다름'
        result.abort, result.error_class = True, llm.FATAL_REQUEST
        return result
    parts = [c for item in raw.get('output', []) if item.get('type') == 'message'
             and item.get('role') == 'assistant' for c in item.get('content', [])]
    if any(c.get('type') == 'refusal' for c in parts):
        result.failure = 'OpenAI refusal'
        return result
    result.text = ''.join(c.get('text', '') for c in parts if c.get('type') == 'output_text')
    try:
        result.parsed = json.loads(result.text)
    except ValueError:
        result.failure = 'OpenAI 출력 JSON 파싱 실패'
        return result
    result.ok = True
    return result


class OpenAIFakeClient:
    def __init__(self, folder):
        from pathlib import Path
        self.dir, self.calls = Path(folder), []

    def create(self, request, key):
        index = self.calls.count(key)
        self.calls.append(key)
        data = json.loads((self.dir / (safe_name(key) + '.json')).read_text(encoding='utf-8'))
        if '__sequence__' in data:
            data = data['__sequence__'][min(index, len(data['__sequence__']) - 1)]
        if '__raise__' in data:
            raise OpenAIError(data.get('message', 'mock error'), data.get('status'), data.get('body'), data.get('headers'))
        return data


class OpenAIAdapter:
    name, billing_tier = 'openai', 'paid'
    supports_count_tokens = False
    default_min_interval_s = 1.0
    sdk_errors = (OpenAIError,)
    max_output_tokens = MAX_OUTPUT_TOKENS

    def __init__(self, model=None):
        if model not in (None, MODEL_ID):
            raise ExtractError(f'OpenAI 모델은 {MODEL_ID}로 고정: {model}')
        self.model_id = MODEL_ID

    def build_request(self, system, user_text, schema):
        request = {'model': MODEL_ID, 'instructions': system, 'input': user_text,
                   'reasoning': {'effort': EFFORT}, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                   'store': False, 'service_tier': 'default',
                   'text': {'format': {'type': 'json_schema', 'name': 'imaks_rules', 'strict': True,
                                       'schema': deepcopy(schema)}}}
        if self.request_chars(request) / 3 > 272000:
            raise ExtractError('요청 입력 추정이 272K를 넘음: 장문 요금 적용 전 청크 분할 필요')
        return request

    def settings_sha(self, request):
        body = {k: v for k, v in request.items() if k != 'input'}
        return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def request_chars(self, request):
        return len(request['instructions']) + len(request['input']) + len(json.dumps(request['text'], ensure_ascii=False))

    def outbound_problem(self, chunk, docs):
        doc = chunk.get('doc_id')
        source = (docs.get('manifest', {}).get(doc) or {}).get('file', '')
        return '' if doc in OUTBOUND_DOCS and source.startswith('imaks_data/rules/') else '외부 전송 SOP 허용 목록 밖'

    def outbound_allowlist(self):
        return {'docs': list(OUTBOUND_DOCS), 'source_file_prefix': 'imaks_data/rules/'}

    def parse_raw(self, raw): return deepcopy(raw)
    def raw_dump(self, response): return deepcopy(response)
    def interpret(self, key, response): return interpret(key, response)
    def classify(self, error): return classify(error)
    def make_client(self): return OpenAIClient()
    def make_fake_client(self, folder): return OpenAIFakeClient(folder)
    def key_problem(self): return '' if api_key() else f'{KEY_ENV}가 환경변수 또는 .env에 없음'
    def model_problem(self): return ''
    def price(self):
        return {'billing_tier': 'paid', 'usd_per_mtok_input': 2.0, 'usd_per_mtok_output': 10.0,
                'basis_date': '2026-10-14'}
    def meta(self):
        return {'provider': self.name, 'model': MODEL_ID, 'max_tokens': MAX_OUTPUT_TOKENS,
                'effort': EFFORT, 'structured_output': 'Responses text.format json_schema strict',
                'sdk_client': {'max_retries': 0, 'timeout_s': TIMEOUT_S}, 'service_tier': 'default',
                'store': False, 'fallbacks': None, 'params_not_sent': ['temperature', 'top_p', 'seed'],
                'price_source': 'https://developers.openai.com/api/docs/models/gpt-6.1-sol'}
