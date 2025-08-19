from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/sim", tags=["Simülasyon Olayları"])


@router.get("/{job_id}/events")
def sse_events(job_id: int):
    # Basit SSE jeneratörü; gerçek implementasyonda Redis pub/sub veya queue ile push edilir
    async def eventgen():
        yield b"event: message\n"
        yield "data: {\"progress\": 0, \"message\": \"Başlatıldı\"}\n\n".encode()
    return StreamingResponse(eventgen(), media_type="text/event-stream")


