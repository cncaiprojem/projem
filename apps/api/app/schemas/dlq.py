"""
Pydantic Schemas for DLQ Management (Task 6.9)

Data validation and serialization schemas for Dead Letter Queue operations.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, validator


class DLQQueueInfo(BaseModel):
    """Information about a single DLQ queue."""
    
    name: str = Field(..., description="Queue name (e.g., 'default_dlq')")
    message_count: int = Field(..., ge=0, description="Total messages in queue")
    messages_ready: int = Field(..., ge=0, description="Messages ready for consumption")
    messages_unacknowledged: int = Field(..., ge=0, description="Messages being processed")
    consumers: int = Field(..., ge=0, description="Number of consumers")
    idle_since: Optional[str] = Field(None, description="ISO timestamp of last activity")
    memory: int = Field(..., ge=0, description="Memory usage in bytes")
    state: str = Field(..., description="Queue state (running, stopped, etc.)")
    type: str = Field(..., description="Queue type (classic, quorum, stream)")
    origin_queue: str = Field(..., description="Original queue name")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "default_dlq",
                "message_count": 42,
                "messages_ready": 40,
                "messages_unacknowledged": 2,
                "consumers": 0,
                "idle_since": "2024-01-15T10:30:00Z",
                "memory": 8192,
                "state": "running",
                "type": "classic",
                "origin_queue": "default"
            }
        }


class DLQListResponse(BaseModel):
    """Response for listing all DLQ queues."""
    
    queues: List[DLQQueueInfo] = Field(..., description="List of DLQ queues")
    total_messages: int = Field(..., ge=0, description="Total messages across all DLQs")
    timestamp: datetime = Field(..., description="Response timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "queues": [
                    {
                        "name": "default_dlq",
                        "message_count": 42,
                        "messages_ready": 40,
                        "messages_unacknowledged": 2,
                        "consumers": 0,
                        "idle_since": "2024-01-15T10:30:00Z",
                        "memory": 8192,
                        "state": "running",
                        "type": "classic",
                        "origin_queue": "default"
                    }
                ],
                "total_messages": 42,
                "timestamp": "2024-01-15T12:00:00Z"
            }
        }


class DLQMessagePreview(BaseModel):
    """Preview of a message in DLQ without consuming it."""
    
    message_id: Optional[str] = Field(None, description="Message ID if available")
    job_id: Optional[int] = Field(None, description="Associated job ID if available")
    routing_key: str = Field(..., description="Current routing key")
    exchange: str = Field(..., description="Current exchange")
    original_routing_key: Optional[str] = Field(None, description="Original routing key from x-death")
    original_exchange: Optional[str] = Field(None, description="Original exchange from x-death")
    death_count: int = Field(..., ge=0, description="Number of times message was dead-lettered")
    first_death_reason: Optional[str] = Field(None, description="Reason for first dead-lettering")
    timestamp: Optional[int] = Field(None, description="Message timestamp")
    headers: Dict[str, Any] = Field(default_factory=dict, description="Message headers")
    payload: Any = Field(..., description="Message payload (truncated if large)")
    payload_bytes: int = Field(..., ge=0, description="Payload size in bytes")
    redelivered: bool = Field(..., description="Whether message was redelivered")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "msg-123",
                "job_id": 456,
                "routing_key": "default_dlq",
                "exchange": "default.dlx",
                "original_routing_key": "jobs.ai",
                "original_exchange": "jobs",
                "death_count": 1,
                "first_death_reason": "rejected",
                "timestamp": 1705320000,
                "headers": {
                    "x-death": [
                        {
                            "reason": "rejected",
                            "queue": "default",
                            "time": "2024-01-15T10:00:00Z",
                            "exchange": "jobs",
                            "routing-keys": ["jobs.ai"]
                        }
                    ],
                    "job_id": 456
                },
                "payload": {"job_id": 456, "task": "generate_model"},
                "payload_bytes": 128,
                "redelivered": False
            }
        }


class DLQReplayRequest(BaseModel):
    """Request to replay messages from DLQ."""
    
    mfa_code: str = Field(..., regex="^[0-9]{6}$", description="6-digit TOTP MFA code")
    max_messages: int = Field(10, ge=1, le=100, description="Maximum messages to replay")
    backoff_ms: int = Field(100, ge=0, le=5000, description="Backoff between messages in ms")
    justification: str = Field(..., min_length=10, max_length=500, description="Justification for replay")
    
    @validator("justification")
    def validate_justification(cls, v):
        """Ensure justification is meaningful."""
        if len(v.strip()) < 10:
            raise ValueError("Justification must be at least 10 characters")
        if v.strip().lower() in ["test", "testing", "asdf", "qwerty"]:
            raise ValueError("Please provide a meaningful justification")
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "mfa_code": "123456",
                "max_messages": 10,
                "backoff_ms": 100,
                "justification": "Replaying messages after fixing database connection issue #1234"
            }
        }


class DLQReplayResponse(BaseModel):
    """Response after replaying messages from DLQ."""
    
    queue_name: str = Field(..., description="DLQ queue name")
    messages_replayed: int = Field(..., ge=0, description="Number of messages successfully replayed")
    messages_failed: int = Field(..., ge=0, description="Number of messages that failed to replay")
    justification: str = Field(..., description="Provided justification")
    timestamp: datetime = Field(..., description="Replay timestamp")
    details: Optional[List[Dict[str, Any]]] = Field(None, description="Details of replayed messages")
    
    class Config:
        json_schema_extra = {
            "example": {
                "queue_name": "default_dlq",
                "messages_replayed": 8,
                "messages_failed": 2,
                "justification": "Replaying messages after fixing database connection issue #1234",
                "timestamp": "2024-01-15T12:00:00Z",
                "details": [
                    {
                        "message_id": "msg-123",
                        "replayed_to": "jobs/jobs.ai",
                        "timestamp": "2024-01-15T12:00:01Z"
                    }
                ]
            }
        }