"""Small AWS Bedrock Converse client shared by the report service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"


@dataclass(frozen=True)
class TextInvokeResult:
    text: str
    stop_reason: str
    model_id: str


def _load_env_without_dependency(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_project_env(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_without_dependency(env_path)
        return
    if env_path.exists():
        load_dotenv(env_path, override=False)


def resolve_aws_params(
    *, profile: str | None = None, region: str | None = None,
    model_id: str | None = None,
) -> tuple[str | None, str, str]:
    load_project_env()
    resolved_profile = (profile or os.getenv("AWS_PROFILE", "")).strip() or None
    resolved_region = (
        (region or os.getenv("AWS_REGION", "")).strip()
        or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    )
    resolved_model = (
        model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    ).strip()
    return resolved_profile, resolved_region, resolved_model


def build_bedrock_runtime_client() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "Bedrock analysis requires the optional 'llm' dependencies. "
            "Install the project with: pip install -e '.[llm]'"
        ) from exc
    profile, region, _ = resolve_aws_params()
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("bedrock-runtime")


def invoke_text(
    prompt: str, *, system_prompt: str, model_id: str | None = None,
    max_tokens: int = 3200, client: Any = None,
) -> TextInvokeResult:
    runtime = client or build_bedrock_runtime_client()
    _, _, resolved_model = resolve_aws_params(model_id=model_id)
    response = runtime.converse(
        modelId=resolved_model,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": max_tokens},
    )
    message = response["output"]["message"]
    text = "\n".join(
        block["text"] for block in message.get("content", []) if "text" in block
    )
    return TextInvokeResult(
        text=text,
        stop_reason=response.get("stopReason", ""),
        model_id=resolved_model,
    )
