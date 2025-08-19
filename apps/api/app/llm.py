from __future__ import annotations

import json
from typing import Any

from openai import OpenAI


def get_openai_client() -> OpenAI:
    return OpenAI()


FREECAD_SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "description": "FreeCADCmd ortamında çalışacak Python scripti"},
        "notes": {"type": "string"}
    },
    "required": ["script"],
    "additionalProperties": False,
}


def build_planetary_prompt(spec_json: str) -> str:
    return (
        "Aşağıdaki planetary şanzıman spesifikasyonu için FreeCADCmd altında çalışacak Python script üret.\n"
        "Kurallar: Sadece App/Part/Sketcher/Asm4 modülleri; FreeCADGui/Qt yok. Tek recompute ve FCStd kaydı üst seviye tarafından yapılacak.\n"
        "Script gövdesi: yeni belge oluşturulmuş varsay; parçaları/özellikleri üret. İsimlendirme: 'Planet','Sun','Ring','Stage-1',...\n"
        f"Spec JSON: {spec_json}\n"
    )


def generate_freecad_script_for_planetary(spec: dict[str, Any]) -> dict[str, str]:
    client = get_openai_client()
    prompt = build_planetary_prompt(json.dumps(spec, ensure_ascii=False))
    resp = client.responses.create(
        model="o4-mini",
        reasoning={"effort": "high"},
        temperature=0.1,
        max_output_tokens=4000,
        input=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        text_format=FREECAD_SCRIPT_SCHEMA,
    )
    out = resp.output[0].content[0].text  # type: ignore[attr-defined]
    data = json.loads(out)
    return {"script": data["script"], "notes": data.get("notes", "")}


