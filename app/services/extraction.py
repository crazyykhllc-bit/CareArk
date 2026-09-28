import base64
import copy
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.schemas import ExtractionDraft
from app.services.preprocess import PreparedDocument


SYSTEM_PROMPT = """你负责从个人医疗资料中忠实提取结构化信息。
只记录资料明确出现的内容；看不清或无法确认时使用 null，并加入 review_items。
资料类型“门诊病历”用于记录本次门诊病情、病史、诊断或诊疗意见的病历；仅有挂号或就诊登记信息的单据仍归为“挂号单 / 就诊单”。不要仅凭“门诊”字样推断类型。
门诊病历的主要日期优先取明确的本次就诊日期；没有明确日期时保留空值并提示核对。
检验结果、单位、参考范围和箭头保持原文，不进行医学判断。
检验项目尽量记录明确的分析物、标本、实际采集条件、观察日期和试验时点；不要因为目录名称带“空腹”就把无条件证据的结果标为空腹。
检查报告把检查名称、方法、所见和意见分别写入 details.exam；票据把总额、支付拆分、币种和明细写入 details.receipt，未知金额保持 null，真实 0 保持 0。
只有资料本身能确认属于当前本人时才把 patient_scope 写为 self；存在其他患者或不能确认时写 other 或 unconfirmed。
包装用法只写入原始说明，不生成个人实际用药计划。
每个可定位的重要字段尽量给出页码和短原文。"""


def strict_json_schema(schema: dict) -> dict:
    normalized = copy.deepcopy(schema)

    def visit(node) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if '(?' in node.get('pattern', ''):
                node.pop('pattern')
            properties = node.get("properties")
            if node.get("type") == "object":
                if not isinstance(properties, dict):
                    properties = {}
                    node["properties"] = properties
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized


class ExtractionError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelEndpoint:
    base_url: str
    api_key: str
    name: str
    strict_json_schema: bool = True


def model_endpoints(settings: Settings) -> list[ModelEndpoint]:
    endpoints = [ModelEndpoint(settings.model_base_url, settings.model_api_key, settings.model_name, settings.model_strict_json_schema)]
    if all((settings.model_fallback_base_url, settings.model_fallback_api_key, settings.model_fallback_name)):
        endpoints.append(ModelEndpoint(settings.model_fallback_base_url,
                                       settings.model_fallback_api_key, settings.model_fallback_name, settings.model_strict_json_schema))
    if all((settings.model_fallback2_base_url, settings.model_fallback2_api_key, settings.model_fallback2_name)):
        endpoints.append(ModelEndpoint(settings.model_fallback2_base_url,
                                       settings.model_fallback2_api_key, settings.model_fallback2_name,
                                       settings.model_fallback2_strict_json_schema))
    return endpoints



def model_request_options(endpoint: ModelEndpoint) -> dict:
    # Faithful extraction does not need DeepSeek's default thinking mode.
    # Other compatible providers must not receive a provider-specific parameter.
    if urlsplit(endpoint.base_url).hostname == 'api.deepseek.com':
        return {'thinking': {'type': 'disabled'}}
    return {}


def can_use_fallback(error: ExtractionError) -> bool:
    return error.code in {'model_rate_limited', 'model_insufficient_balance', 'model_unavailable'} or (
        error.code == 'model_request_failed' and error.retryable)


def model_http_error(response: httpx.Response) -> ExtractionError:
    # Interpret known codes only; provider messages may contain private request details.
    try:
        data = response.json()
        error = data.get('error', data) if isinstance(data, dict) else {}
        code = error.get('code', '') if isinstance(error, dict) else ''
    except ValueError:
        code = ''
    if code in {'INSUFFICIENT_BALANCE', 'insufficient_quota', 'insufficient_balance'}:
        return ExtractionError('模型服务账户余额不足或额度已用完，请补充额度后重试识别',
                               code='model_insufficient_balance', retryable=False)
    code = 'model_rate_limited' if response.status_code == 429 else 'model_request_failed'
    return ExtractionError(f'模型服务请求失败（HTTP {response.status_code}）', code=code,
                           retryable=response.status_code in {408, 409, 429} or response.status_code >= 500)


class Extractor(Protocol):
    async def extract(self, document: PreparedDocument) -> ExtractionDraft: ...


class FakeExtractor:
    def __init__(self, payload: dict):
        self.payload = payload

    async def extract(self, document: PreparedDocument) -> ExtractionDraft:
        return ExtractionDraft.model_validate(self.payload)


class OpenAICompatibleExtractor:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self.last_model_name: str | None = None

    def _content(self, document: PreparedDocument) -> list[dict]:
        content = [{"type": "text", "text": "请按给定 JSON Schema 提取这份医疗资料。"}]
        for part in document.text_parts:
            content.append({"type": "text", "text": f"[{part.label}]\n{part.content}"})
        for image in document.image_parts:
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image.mime_type};base64,{encoded}",
                    "detail": self.settings.model_image_detail,
                },
            })
        return content

    async def extract(self, document: PreparedDocument) -> ExtractionDraft:
        self.last_model_name = None
        if not self.settings.model_api_key or not self.settings.model_name:
            raise ExtractionError("解析服务未配置", code="model_not_configured", retryable=False)
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._content(document)},
            ],
            "temperature": 0,
        }
        schema = strict_json_schema(ExtractionDraft.model_json_schema())
        endpoints = model_endpoints(self.settings)
        for index, endpoint in enumerate(endpoints):
            payload['model'] = endpoint.name
            payload.pop('thinking', None)
            payload.update(model_request_options(endpoint))
            payload['messages'][0]['content'] = SYSTEM_PROMPT
            if endpoint.strict_json_schema:
                payload['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': 'health_archive_extraction', 'strict': True, 'schema': schema,
                }}
            else:
                payload['response_format'] = {'type': 'json_object'}
                payload['messages'][0]['content'] += '\nJSON Schema: ' + json.dumps(schema, ensure_ascii=False)
            try:
                try:
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=self.settings.model_timeout_seconds,
                    ) as client:
                        response = await client.post(
                            f"{endpoint.base_url.rstrip('/')}/chat/completions",
                            headers={"Authorization": f"Bearer {endpoint.api_key}"},
                            json=payload,
                        )
                except httpx.TransportError as error:
                    raise ExtractionError("模型服务暂时无法连接", code="model_unavailable", retryable=True) from error
                if response.status_code >= 400:
                    raise model_http_error(response)
            except ExtractionError as error:
                if index + 1 < len(endpoints) and can_use_fallback(error):
                    continue
                raise
            break
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(item.get("text", "") for item in content)
            draft = ExtractionDraft.model_validate(json.loads(content))
            self.last_model_name = endpoint.name
            return draft
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as error:
            raise ExtractionError("模型输出不符合健康档案结构", code="invalid_model_output", retryable=False) from error
