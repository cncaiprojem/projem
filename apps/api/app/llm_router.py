from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any, Dict, List, Tuple

from openai import OpenAI
import os

from .config import settings


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    # Anahtar env veya settings ile verilebilir
    key = os.getenv("OPENAI_API_KEY") or settings.openai_api_key
    if key:
        return OpenAI(api_key=key)
    return OpenAI()


def _has_responses_api() -> bool:
    try:
        return hasattr(_client(), "responses")
    except Exception:
        return False


_health_cache: Dict[str, Tuple[float, bool]] = {}


def health_check(model: str) -> bool:
    now = time.time()
    hit = _health_cache.get(model)
    if hit and (now - hit[0]) < 60:
        return hit[1]
    ok = True
    try:
        _client().responses.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
            max_output_tokens=1,
        )
    except Exception:
        ok = False
    _health_cache[model] = (now, ok)
    return ok


def choose_model(brief: Dict[str, Any], policy: str | None = None) -> Tuple[str, str]:
    policy = policy or settings.model_policy
    default = settings.default_model
    fallback = settings.fallback_model
    if policy == "cost_first":
        return fallback, default
    return default, fallback


def generate_structured(brief: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    primary, fallback = choose_model(brief)
    schema = {
        "type": "object",
        "properties": {
            "script": {"type": "string"},
            "params": {"type": "object"},
            "bom": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "part_no": {"type": "string"},
                        "name": {"type": "string"},
                        "material": {"type": "string"},
                        "qty": {"type": "number"},
                    },
                    "required": ["part_no", "name", "material", "qty"],
                },
            },
            "notes": {"type": "string"},
        },
        "required": ["script"],
        "additionalProperties": False,
    }
    models_tried: List[str] = []
    escalated = False
    for mdl in (primary, fallback):
        models_tried.append(mdl)
        try:
            if _has_responses_api():
                resp = _client().responses.create(
                    model=mdl,
                    reasoning={"effort": "high"},
                    temperature=0.1,
                    max_output_tokens=4000,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": json.dumps(brief, ensure_ascii=False)}
                            ],
                        }
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "design", "schema": schema},
                    },
                )
                try:
                    out = resp.output_text  # type: ignore[attr-defined]
                except Exception:
                    out = resp.output[0].content[0].text  # type: ignore[index, attr-defined]
                data = json.loads(out)
            else:
                msgs = [
                    {
                        "role": "system",
                        "content": "Yalnız JSON döndür; şema: script(params,bom[],notes)",
                    },
                    {"role": "user", "content": json.dumps(brief, ensure_ascii=False)},
                ]
                cmpl = _client().chat.completions.create(model=mdl, temperature=0.1, messages=msgs)
                content = cmpl.choices[0].message.content or "{}"
                data = json.loads(content)
            # basit sanitize
            if any(
                x in data.get("script", "")
                for x in ["FreeCADGui", "subprocess", "os.system", "requests", "shutil"]
            ):
                raise ValueError("yasak import")
            meta = {
                "model_name": mdl,
                "token_input": getattr(resp, "usage", {}).get("input_tokens", None),
                "token_output": getattr(resp, "usage", {}).get("output_tokens", None),
                "escalated": escalated,
            }
            return data, meta
        except Exception:
            escalated = True
            continue
    raise RuntimeError("Model yanıt üretemedi")


# Plan odaklı yardımcılar (M13)
MODEL_PLAN = os.getenv("MODEL_PLAN", settings.default_model)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "is_cnc_related": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["part", "assembly"]},
        "missing": {"type": "array", "items": {"type": "string"}},
        "plan": {"type": "object"},
    },
    "required": ["is_cnc_related", "kind", "missing", "plan"],
    "additionalProperties": False,
}


def _ensure_plan_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    plan_in = data if isinstance(data, dict) else {}
    plan = plan_in.get("plan") if isinstance(plan_in.get("plan"), dict) else {}
    cad = plan.get("cad") if isinstance(plan.get("cad"), dict) else {}
    cam = plan.get("cam") if isinstance(plan.get("cam"), dict) else {}
    plan["cad"] = cad
    plan["cam"] = cam
    # missing alanı yoksa errors.critical_points'tan türet
    missing = plan_in.get("missing") if isinstance(plan_in.get("missing"), list) else []
    if not missing:
        errs = plan_in.get("errors")
        if isinstance(errs, list) and errs:
            cp = errs[0].get("critical_points") if isinstance(errs[0], dict) else None
            if isinstance(cp, list):
                missing = [str(x) for x in cp][:3]
    if not missing:
        missing = ["malzeme", "parça ölçüleri", "makine türü"]
    kind = plan_in.get("kind") if plan_in.get("kind") in ("part", "assembly") else "part"
    is_cnc_related = plan_in.get("is_cnc_related")
    if not isinstance(is_cnc_related, bool):
        is_cnc_related = True
    return {"is_cnc_related": is_cnc_related, "kind": kind, "missing": missing, "plan": plan}


def analyze_and_plan(prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
    if not (os.getenv("OPENAI_API_KEY") or settings.openai_api_key):
        raise RuntimeError("LLM servisi yapılandırılmamış: OPENAI_API_KEY eksik.")
    sys = (
        "Sen CNC/CAD-CAM planlayıcısın. Çıktın KESİNLİKLE JSON ve şemaya uymalı. "
        "Eksikleri EN FAZLA 3 kritik maddede bildir. plan.cad ve plan.cam özetlerini doldur."
    )
    inst = {"prompt": prompt, "context": context}
    if _has_responses_api():
        resp = _client().responses.create(
            model=MODEL_PLAN,
            reasoning={"effort": "high"},
            input=[
                {"role": "system", "content": [{"type": "text", "text": sys}]},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": json.dumps(inst, ensure_ascii=False)}],
                },
            ],
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "plan", "schema": PLAN_SCHEMA},
            },
        )
        try:
            out = resp.output_text  # type: ignore[attr-defined]
        except Exception:
            out = resp.output[0].content[0].text  # type: ignore[index, attr-defined]
        return _ensure_plan_shape(json.loads(out))
    # Fallback: Chat Completions
    msgs = [
        {"role": "system", "content": sys + " Sadece JSON döndür, başına/sonuna açıklama ekleme."},
        {"role": "user", "content": json.dumps(inst, ensure_ascii=False)},
    ]
    cmpl = _client().chat.completions.create(
        model=MODEL_PLAN,
        temperature=0.2,
        messages=msgs,
    )
    content = cmpl.choices[0].message.content or "{}"
    return _ensure_plan_shape(json.loads(content))


def refine_plan(current: Dict[str, Any], answers: Dict[str, Any]) -> Dict[str, Any]:
    missing = [m for m in current.get("missing", []) if m not in answers]
    plan = current.get("plan", {})
    plan.setdefault("answers", {}).update(answers)
    current["missing"] = missing
    current["plan"] = plan
    return current
