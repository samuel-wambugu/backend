import json
import random
import time
from urllib import error, parse, request

from django.conf import settings


class ProviderConfigurationError(RuntimeError):
    """Raised when a requested provider lacks required configuration."""


class ProviderRequestError(RuntimeError):
    """Raised when a configured provider request fails at runtime."""

    def __init__(self, message, *, status_code=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class BaseAIProvider:
    name = 'base'

    def is_configured(self):
        raise NotImplementedError()

    def get_status(self):
        raise NotImplementedError()

    def invoke(self, messages, metadata):
        raise NotImplementedError()

    def _post_json(self, url, body, headers, timeout=20):
        req = request.Request(
            url=url,
            data=json.dumps(body).encode('utf-8'),
            headers=headers,
            method='POST',
        )
        max_retries = max(getattr(settings, 'AI_PROVIDER_429_MAX_RETRIES', 2), 0)
        base_delay = max(float(getattr(settings, 'AI_PROVIDER_429_BACKOFF_BASE_SECONDS', 0.8)), 0.0)
        jitter = max(float(getattr(settings, 'AI_PROVIDER_429_JITTER_SECONDS', 0.6)), 0.0)

        for attempt in range(max_retries + 1):
            try:
                with request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode('utf-8'))
                    return {
                        'status_code': getattr(resp, 'status', 200),
                        'body': payload,
                        'headers': dict(getattr(resp, 'headers', {})),
                    }
            except error.HTTPError as exc:
                body = ''
                try:
                    body = exc.read().decode('utf-8')
                except Exception:
                    body = ''

                retryable_status = exc.code in {429, 500, 502, 503, 504}
                if exc.code == 429 and attempt < max_retries:
                    sleep_seconds = (base_delay * (2 ** attempt)) + random.uniform(0, jitter)
                    time.sleep(sleep_seconds)
                    continue

                message = f"HTTP Error {exc.code}: {exc.reason}"
                if body:
                    message = f"{message} - {body[:300]}"
                raise ProviderRequestError(
                    message,
                    status_code=exc.code,
                    retryable=retryable_status,
                ) from exc
            except error.URLError as exc:
                raise ProviderRequestError(
                    f"Network error while calling provider: {exc.reason}",
                    status_code=None,
                    retryable=True,
                ) from exc


class OpenAIProvider(BaseAIProvider):
    name = 'openai'

    def is_configured(self):
        return bool(settings.AI_OPENAI_API_KEY and self._model_name())

    def get_status(self):
        return {
            'provider': self.name,
            'configured': self.is_configured(),
            'model': self._model_name(),
            'api_base_url': settings.AI_OPENAI_API_BASE_URL,
        }

    def invoke(self, messages, metadata):
        if not self.is_configured():
            raise ProviderConfigurationError('OpenAI provider is not fully configured')

        response = self._post_json(
            url=f"{settings.AI_OPENAI_API_BASE_URL.rstrip('/')}/v1/chat/completions",
            body={
                'model': self._model_name(),
                'messages': messages,
                'temperature': metadata.get('temperature', 0.2),
                'response_format': {'type': 'json_object'},
            },
            headers={
                'Authorization': f"Bearer {settings.AI_OPENAI_API_KEY}",
                'Content-Type': 'application/json',
            },
        )
        text = response['body']['choices'][0]['message']['content']
        return {
            'provider': self.name,
            'model_name': self._model_name(),
            'status_code': response['status_code'],
            'raw_response': response['body'],
            'text': text,
            'external_request_id': response['body'].get('id', ''),
        }

    def _model_name(self):
        return settings.AI_OPENAI_MODEL or settings.AI_MODEL


class AzureOpenAIProvider(BaseAIProvider):
    name = 'azure-openai'

    def is_configured(self):
        return bool(
            settings.AI_AZURE_OPENAI_API_KEY and
            settings.AI_AZURE_OPENAI_ENDPOINT and
            settings.AI_AZURE_OPENAI_DEPLOYMENT
        )

    def get_status(self):
        return {
            'provider': self.name,
            'configured': self.is_configured(),
            'model': settings.AI_AZURE_OPENAI_DEPLOYMENT,
            'api_base_url': settings.AI_AZURE_OPENAI_ENDPOINT,
        }

    def invoke(self, messages, metadata):
        if not self.is_configured():
            raise ProviderConfigurationError('Azure OpenAI provider is not fully configured')

        api_version = settings.AI_AZURE_OPENAI_API_VERSION
        query = parse.urlencode({'api-version': api_version})
        url = (
            f"{settings.AI_AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
            f"{settings.AI_AZURE_OPENAI_DEPLOYMENT}/chat/completions?{query}"
        )
        response = self._post_json(
            url=url,
            body={
                'messages': messages,
                'temperature': metadata.get('temperature', 0.2),
                'response_format': {'type': 'json_object'},
            },
            headers={
                'api-key': settings.AI_AZURE_OPENAI_API_KEY,
                'Content-Type': 'application/json',
            },
        )
        text = response['body']['choices'][0]['message']['content']
        return {
            'provider': self.name,
            'model_name': settings.AI_AZURE_OPENAI_DEPLOYMENT,
            'status_code': response['status_code'],
            'raw_response': response['body'],
            'text': text,
            'external_request_id': response['headers'].get('x-request-id', ''),
        }


class AnthropicProvider(BaseAIProvider):
    name = 'anthropic'

    def is_configured(self):
        return bool(settings.AI_ANTHROPIC_API_KEY and settings.AI_ANTHROPIC_MODEL)

    def get_status(self):
        return {
            'provider': self.name,
            'configured': self.is_configured(),
            'model': settings.AI_ANTHROPIC_MODEL,
            'api_base_url': settings.AI_ANTHROPIC_API_BASE_URL,
        }

    def invoke(self, messages, metadata):
        if not self.is_configured():
            raise ProviderConfigurationError('Anthropic provider is not fully configured')

        system_prompt = ''
        anthropic_messages = []
        for message in messages:
            if message['role'] == 'system':
                system_prompt = message['content']
            else:
                anthropic_messages.append({
                    'role': message['role'],
                    'content': message['content'],
                })

        response = self._post_json(
            url=f"{settings.AI_ANTHROPIC_API_BASE_URL.rstrip('/')}/v1/messages",
            body={
                'model': settings.AI_ANTHROPIC_MODEL,
                'system': system_prompt,
                'messages': anthropic_messages,
                'temperature': metadata.get('temperature', 0.2),
                'max_tokens': metadata.get('max_tokens', 600),
            },
            headers={
                'x-api-key': settings.AI_ANTHROPIC_API_KEY,
                'anthropic-version': settings.AI_ANTHROPIC_VERSION,
                'Content-Type': 'application/json',
            },
        )
        text = ''.join(part.get('text', '') for part in response['body'].get('content', []))
        return {
            'provider': self.name,
            'model_name': settings.AI_ANTHROPIC_MODEL,
            'status_code': response['status_code'],
            'raw_response': response['body'],
            'text': text,
            'external_request_id': response['body'].get('id', ''),
        }


def build_provider_registry():
    return {
        OpenAIProvider.name: OpenAIProvider(),
        AzureOpenAIProvider.name: AzureOpenAIProvider(),
        AnthropicProvider.name: AnthropicProvider(),
    }