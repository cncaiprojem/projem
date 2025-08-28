"""
AI Adapter Service for Task 7.2 - OpenAI/Azure Support with Turkish FreeCAD Expertise

Ultra-enterprise AI adapter with:
- Provider-agnostic interface supporting OpenAI and Azure OpenAI  
- FreeCAD 1.1 expertise with Turkish language optimization
- PII masking for KVKK compliance
- Exponential backoff with jitter for retries
- Circuit breaker pattern for repeated timeouts
- Rate limiting: 30 requests/minute per user
- Turkish CAD glossary translation
- Structured logging and metrics
"""

from __future__ import annotations

import asyncio
import json
import re
import threading  # CRITICAL FIX: Added for thread safety
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, Field, field_validator, PrivateAttr

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
# from ..core import metrics  # Temporarily disabled due to metric name conflicts
from ..middleware.correlation_middleware import get_correlation_id
from ..models.ai_suggestions import AISuggestion

logger = get_logger(__name__)


class AIProvider(str, Enum):
    """Supported AI providers."""
    OPENAI = "openai"
    AZURE = "azure"


class AIErrorCode(str, Enum):
    """AI adapter error codes."""
    PROVIDER_ERROR = "ERR-AI-500"
    TIMEOUT = "ERR-AI-504"
    RATE_LIMITED = "ERR-AI-429"
    INVALID_RESPONSE = "ERR-AI-422"
    AMBIGUOUS_REQUEST = "ERR-AI-425"
    MISSING_DATA = "ERR-AI-422"
    SECURITY_VIOLATION = "ERR-AI-451"
    CIRCUIT_BREAKER_OPEN = "ERR-AI-503"
    CONFIG_ERROR = "ERR-AI-503"
    VALIDATION_FAILED = "ERR-AI-400"  # Added for script validation failures


class AIException(Exception):
    """AI adapter exception with Turkish support."""
    def __init__(
        self,
        message: str,
        error_code: AIErrorCode,
        turkish_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.turkish_message = turkish_message or message
        self.details = details or {}


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker(BaseModel):
    """Circuit breaker for timeout protection with proper failure rate calculation."""
    state: CircuitBreakerState = Field(default=CircuitBreakerState.CLOSED)
    failure_count: int = Field(default=0)
    success_count: int = Field(default=0)
    total_count: int = Field(default=0)
    last_failure_time: Optional[datetime] = Field(default=None)
    last_success_time: Optional[datetime] = Field(default=None)
    threshold: int = Field(default=3, description="Consecutive failures before opening")
    failure_rate_threshold: float = Field(default=0.5, description="Failure rate threshold (50%)")
    recovery_timeout: int = Field(default=60, description="Seconds before half-open")
    half_open_requests: int = Field(default=1, description="Requests allowed in half-open")
    half_open_backoff_multiplier: float = Field(default=1.5, description="Exponential backoff multiplier")
    consecutive_failures: int = Field(default=0, description="Consecutive failure count")
    window_size: int = Field(default=10, description="Window size for failure rate calculation")
    recent_results: List[bool] = Field(default_factory=list, description="Recent results for rate calculation")
    
    def is_open(self) -> bool:
        """Check if circuit is open with proper half-open state testing."""
        now = datetime.now(timezone.utc)
        
        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time:
                # Use proper timezone-aware comparison
                elapsed = (now - self.last_failure_time).total_seconds()
                if elapsed > self.recovery_timeout:
                    # Move to half-open state for testing
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                    logger.info("Circuit breaker moved to half-open state for testing")
                    return False
            return True
        elif self.state == CircuitBreakerState.HALF_OPEN:
            # Allow limited requests in half-open state
            return False
        return False
    
    def record_success(self):
        """Record successful call with proper state management."""
        now = datetime.now(timezone.utc)
        self.last_success_time = now
        self.total_count += 1
        self.consecutive_failures = 0  # Reset consecutive failures
        
        # Update recent results for failure rate calculation
        self.recent_results.append(True)
        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_requests:
                # Successfully tested in half-open, close the circuit
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                self.recent_results = []  # Reset window
                logger.info("Circuit breaker closed after successful half-open testing")
    
    def record_failure(self):
        """Record failed call with failure rate calculation."""
        now = datetime.now(timezone.utc)
        self.failure_count += 1
        self.total_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = now
        
        # Update recent results for failure rate calculation
        self.recent_results.append(False)
        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)
        
        # Calculate failure rate
        if len(self.recent_results) >= self.window_size // 2:
            failure_rate = sum(1 for r in self.recent_results if not r) / len(self.recent_results)
        else:
            failure_rate = 0.0
        
        # Open circuit based on consecutive failures OR failure rate
        should_open = (
            self.consecutive_failures >= self.threshold or
            (failure_rate >= self.failure_rate_threshold and len(self.recent_results) >= self.window_size // 2)
        )
        
        if should_open:
            if self.state == CircuitBreakerState.HALF_OPEN:
                # Failed in half-open, apply exponential backoff
                self.recovery_timeout = int(self.recovery_timeout * self.half_open_backoff_multiplier)
                logger.warning(f"Circuit breaker re-opened with increased timeout: {self.recovery_timeout}s")
            self.state = CircuitBreakerState.OPEN
            logger.warning(
                f"Circuit breaker opened - consecutive: {self.consecutive_failures}, "
                f"failure rate: {failure_rate:.2%}"
            )


class RateLimiter(BaseModel):
    """Thread-safe per-user rate limiter."""
    requests: Dict[str, List[datetime]] = Field(default_factory=dict)
    limit: int = Field(default=30, description="Requests per minute")
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)  # Thread safety lock
    
    class Config:
        arbitrary_types_allowed = True  # Allow threading.Lock
    
    def check_and_update(self, user_id: str) -> bool:
        """Thread-safe check if user can make request and update counter."""
        with self._lock:  # CRITICAL FIX: Thread-safe operations
            now = datetime.now(timezone.utc)
            minute_ago = now - timedelta(minutes=1)
            
            if user_id not in self.requests:
                self.requests[user_id] = []
            
            # Clean old requests
            self.requests[user_id] = [
                req_time for req_time in self.requests[user_id]
                if req_time > minute_ago
            ]
            
            if len(self.requests[user_id]) >= self.limit:
                return False
            
            self.requests[user_id].append(now)
            return True


# Turkish CAD glossary for translation
TURKISH_CAD_GLOSSARY = {
    "vida": "screw",
    "flanş": "flange", 
    "mil": "shaft",
    "yatak": "bearing",
    "dişli": "gear",
    "somun": "nut",
    "cıvata": "bolt",
    "conta": "gasket",
    "rulman": "bearing",
    "kayış": "belt",
    "kasnak": "pulley",
    "krank": "crankshaft",
    "piston": "piston",
    "valf": "valve",
    "boru": "pipe",
    "dirsek": "elbow",
    "te": "tee",
    "redüksiyon": "reducer",
    "manşon": "coupling",
    "nipel": "nipple"
}


class AIAdapterConfig(BaseModel):
    """AI adapter configuration."""
    provider: AIProvider = Field(default=AIProvider.OPENAI)
    api_key: Optional[str] = Field(default=None)
    api_base: Optional[str] = Field(default=None)
    model: str = Field(default="gpt-4")
    max_tokens: int = Field(default=2000)
    timeout: int = Field(default=20)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    
    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Validate API key format."""
        if v and len(v) < 10:
            raise ValueError("API key too short")
        return v


class FreeCADScriptResponse(BaseModel):
    """Structured AI response for FreeCAD script generation."""
    language: str = Field(default="tr")
    units: str = Field(default="mm")
    intent: str = Field(default="freecad_script")
    glossary_used: bool = Field(default=False)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    script_py: str = Field(description="FreeCAD Python script")
    warnings: List[str] = Field(default_factory=list)
    requires_clarification: bool = Field(default=False)
    
    def normalize_units(self):
        """Ensure all dimensions are in mm."""
        if self.units != "mm":
            # Convert common units
            conversions = {
                "cm": 10.0,
                "m": 1000.0,
                "in": 25.4,
                "inch": 25.4,
                "inches": 25.4,
                '"': 25.4,
                "ft": 304.8,
                "feet": 304.8
            }
            
            if self.units in conversions:
                factor = conversions[self.units]
                # Convert numeric parameters
                for key, value in self.parameters.items():
                    if isinstance(value, (int, float)):
                        self.parameters[key] = value * factor
                
                # Add conversion warning
                self.warnings.append(
                    f"Birimler {self.units} → mm dönüştürüldü (×{factor})"
                )
            
            self.units = "mm"


class AIAdapter:
    """Provider-agnostic AI adapter for FreeCAD script generation."""
    
    def __init__(self, config: Optional[AIAdapterConfig] = None):
        """Initialize AI adapter with configuration."""
        self.config = config or self._load_config_from_env()
        self.circuit_breaker = CircuitBreaker()
        self.rate_limiter = RateLimiter()
        self._client = None
        self._initialize_client()
    
    def _load_config_from_env(self) -> AIAdapterConfig:
        """Load configuration from environment variables."""
        provider = AIProvider.OPENAI
        if hasattr(settings, 'AI_PROVIDER'):
            provider = AIProvider(settings.AI_PROVIDER.lower())
        
        config = AIAdapterConfig(provider=provider)
        
        if provider == AIProvider.OPENAI:
            config.api_key = getattr(settings, 'OPENAI_API_KEY', None)
            config.model = getattr(settings, 'OPENAI_MODEL', 'gpt-4')
        elif provider == AIProvider.AZURE:
            config.api_key = getattr(settings, 'AZURE_API_KEY', None)
            config.api_base = getattr(settings, 'AZURE_API_BASE', None)
            config.model = getattr(settings, 'AZURE_DEPLOYMENT_NAME', 'gpt-4')
        
        config.max_tokens = getattr(settings, 'AI_MAX_TOKENS', 2000)
        config.timeout = getattr(settings, 'AI_TIMEOUT_SECONDS', 20)
        config.temperature = getattr(settings, 'AI_TEMPERATURE', 0.3)
        
        return config
    
    def _initialize_client(self):
        """Initialize the AI provider client with proper async support."""
        if not self.config.api_key:
            logger.warning(f"No API key configured for {self.config.provider}")
            return
        
        try:
            if self.config.provider == AIProvider.OPENAI:
                # CRITICAL FIX: Use AsyncOpenAI for native async support
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    timeout=self.config.timeout,
                    max_retries=0  # We handle retries ourselves
                )
            elif self.config.provider == AIProvider.AZURE:
                # CRITICAL FIX: Use async Azure client
                from openai import AsyncAzureOpenAI
                self._client = AsyncAzureOpenAI(
                    api_key=self.config.api_key,
                    azure_endpoint=self.config.api_base,
                    api_version="2024-02-01",
                    timeout=self.config.timeout,
                    max_retries=0  # We handle retries ourselves
                )
        except ImportError as e:
            logger.error(f"Failed to import AI provider library: {e}")
            raise AIException(
                "AI provider library not installed",
                AIErrorCode.CONFIG_ERROR,
                "AI sağlayıcı kütüphanesi yüklü değil"
            )
    
    def _get_system_prompt(self) -> str:
        """Get Turkish FreeCAD expert system prompt."""
        return """Sen FreeCAD 1.1 Python API uzmanısın. Türkçe CAD tasarım isteklerini FreeCAD scriptlerine dönüştür.

KURALLAR:
- Part, PartDesign, Sketcher, Draft modüllerini kullan
- Birimler her zaman mm (milimetre)
- Koordinat sistemi sağ el kuralı
- Assembly4 ve OndselSolver uyumlu kod üret
- Dosya I/O yasak, sadece bellek içi işlemler

TÜRKÇE CAD TERİMLERİ:
vida→screw, flanş→flange, mil→shaft, yatak→bearing, dişli→gear, somun→nut, cıvata→bolt, conta→gasket, rulman→bearing, kayış→belt, kasnak→pulley

BOYUT SINIRLAMALARI:
- Minimum: 0.1 mm
- Maximum: 1000 mm
- Kalınlık varsayılan: 5 mm
- M8 vida boşluğu: 8.5 mm

ÇIKTI FORMATI:
Yalnızca JSON döndür (markdown yok). Zorunlu alanlar:
{
  "language": "tr",
  "units": "mm",
  "intent": "freecad_script",
  "glossary_used": true|false,
  "parameters": {...},
  "script_py": "<FreeCAD Python kodu>",
  "warnings": [],
  "requires_clarification": true|false
}

GÜVENLIK:
- exec, eval, open, os, subprocess kullanma
- Sadece beyaz listedeki modüller: FreeCAD, Part, PartDesign, Sketcher, Draft, Import, Mesh, math, numpy
- Import.export yasak (dışarıda yapılır)"""
    
    def _get_few_shot_examples(self) -> List[Dict[str, str]]:
        """Get few-shot examples for Turkish FreeCAD generation."""
        return [
            {
                "role": "user",
                "content": "M8 vida deliği olan 20mm flanş"
            },
            {
                "role": "assistant",
                "content": json.dumps({
                    "language": "tr",
                    "units": "mm",
                    "intent": "freecad_script",
                    "glossary_used": True,
                    "parameters": {
                        "outer_diameter": 20.0,
                        "hole_diameter": 8.5,
                        "thickness": 5.0
                    },
                    "script_py": """import FreeCAD as App
import Part

doc = App.newDocument("flange")
outer_d = 20.0
thickness = 5.0
hole_d = 8.5  # M8 clearance

body = Part.makeCylinder(outer_d/2.0, thickness)
hole = Part.makeCylinder(hole_d/2.0, thickness)
result = body.cut(hole)

Part.show(result)
doc.recompute()""",
                    "warnings": ["Varsayılan kalınlık 5mm kullanıldı"],
                    "requires_clarification": False
                }, ensure_ascii=False)
            }
        ]
    
    def _apply_glossary(self, prompt: str) -> Tuple[str, bool]:
        """Apply Turkish CAD glossary to prompt."""
        modified_prompt = prompt
        glossary_used = False
        
        for turkish_term, english_term in TURKISH_CAD_GLOSSARY.items():
            if turkish_term in prompt.lower():
                # Add hint for AI without modifying original prompt
                modified_prompt += f" ({turkish_term}={english_term})"
                glossary_used = True
        
        return modified_prompt, glossary_used
    
    async def suggest_params(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        retries: int = 3,
        user_id: Optional[str] = None
    ) -> FreeCADScriptResponse:
        """
        Generate FreeCAD script parameters from Turkish prompt.
        
        Args:
            prompt: User prompt in Turkish
            context: Additional context for generation
            max_tokens: Maximum tokens for response (<=2000)
            timeout: Timeout in seconds (<=20)
            retries: Number of retries with exponential backoff
            user_id: User ID for rate limiting
            
        Returns:
            FreeCADScriptResponse with generated script and parameters
            
        Raises:
            AIException: On provider errors, timeouts, or invalid responses
        """
        correlation_id = get_correlation_id()
        request_id = str(uuid4())
        
        with create_span("ai_adapter_suggest_params", correlation_id=correlation_id) as span:
            span.set_attribute("ai.provider", self.config.provider.value)
            span.set_attribute("ai.model", self.config.model)
            span.set_attribute("ai.request_id", request_id)
            
            # Check circuit breaker
            if self.circuit_breaker.is_open():
                raise AIException(
                    "Circuit breaker is open due to repeated failures",
                    AIErrorCode.CIRCUIT_BREAKER_OPEN,
                    "Tekrarlanan hatalar nedeniyle devre kesici açık"
                )
            
            # Rate limiting
            if user_id and not self.rate_limiter.check_and_update(user_id):
                raise AIException(
                    "Rate limit exceeded (30 requests/minute)",
                    AIErrorCode.RATE_LIMITED,
                    "Hız limiti aşıldı (dakikada 30 istek)"
                )
            
            # Apply glossary
            enhanced_prompt, glossary_used = self._apply_glossary(prompt)
            
            # Validate user_id and fail fast if invalid
            if not user_id:
                # If anonymous suggestions are required, use a dedicated anonymous user ID
                # Otherwise, reject the request
                raise AIException(
                    "A valid user_id is required for AI suggestions.",
                    AIErrorCode.VALIDATION_FAILED,
                    "AI önerileri için geçerli bir kullanıcı kimliği gereklidir."
                )
            
            # Validate user_id format
            try:
                validated_user_id = int(user_id) if isinstance(user_id, str) else user_id
                if validated_user_id <= 0:
                    raise ValueError("User ID must be positive")
            except (ValueError, TypeError) as e:
                raise AIException(
                    f"Invalid user_id format: {e}",
                    AIErrorCode.VALIDATION_FAILED,
                    f"Geçersiz kullanıcı kimliği formatı: {e}"
                )
            
            # Mask PII before storage
            ai_suggestion = AISuggestion(
                request_id=request_id,
                prompt="",  # Will be set after masking
                response={},  # Will be set after generation
                user_id=validated_user_id
            )
            masked_prompt = ai_suggestion.mask_pii(enhanced_prompt)
            ai_suggestion.prompt = masked_prompt
            
            # Prepare messages
            messages = [
                {"role": "system", "content": self._get_system_prompt()}
            ]
            messages.extend(self._get_few_shot_examples())
            messages.append({
                "role": "user",
                "content": enhanced_prompt
            })
            
            # Set limits
            actual_max_tokens = min(max_tokens or self.config.max_tokens, 2000)
            actual_timeout = min(timeout or self.config.timeout, 20)
            
            # Retry loop with exponential backoff
            last_exception = None
            for attempt in range(retries):
                try:
                    start_time = time.time()
                    
                    # Call AI provider
                    response = await self._call_provider(
                        messages,
                        actual_max_tokens,
                        actual_timeout
                    )
                    
                    # Parse and validate response
                    script_response = self._parse_response(response)
                    script_response.glossary_used = glossary_used
                    
                    # Normalize units to mm
                    script_response.normalize_units()
                    
                    # Validate script security
                    self._validate_script_security(script_response.script_py)
                    
                    # Record success
                    self.circuit_breaker.record_success()
                    
                    # Store in database
                    ai_suggestion.response = script_response.dict()
                    ai_suggestion.model_name = self.config.model
                    ai_suggestion.prompt_tokens = response.get("usage", {}).get("prompt_tokens")
                    ai_suggestion.response_tokens = response.get("usage", {}).get("completion_tokens")
                    
                    # Calculate cost using Decimal for precision (example rates)
                    if ai_suggestion.prompt_tokens and ai_suggestion.response_tokens:
                        # GPT-4 rates (adjust as needed) - using Decimal for financial accuracy
                        prompt_tokens_decimal = Decimal(str(ai_suggestion.prompt_tokens))
                        response_tokens_decimal = Decimal(str(ai_suggestion.response_tokens))
                        
                        # Cost per 1000 tokens in dollars
                        prompt_rate = Decimal('0.03')  # $0.03 per 1k tokens
                        completion_rate = Decimal('0.06')  # $0.06 per 1k tokens
                        
                        # Calculate costs in dollars
                        prompt_cost = (prompt_tokens_decimal * prompt_rate) / Decimal('1000')
                        completion_cost = (response_tokens_decimal * completion_rate) / Decimal('1000')
                        total_cost_dollars = prompt_cost + completion_cost
                        
                        # Convert to cents and round properly
                        total_cost_cents_decimal = (total_cost_dollars * Decimal('100')).quantize(
                            Decimal('1'), rounding=ROUND_HALF_UP
                        )
                        ai_suggestion.total_cost_cents = int(total_cost_cents_decimal)
                    
                    # Set retention period (90 days for KVKK)
                    ai_suggestion.set_retention_period(90)
                    
                    # Log metrics
                    elapsed = time.time() - start_time
                    # metrics.ai_adapter_requests_total.labels(
                    #     provider=self.config.provider.value,
                    #     status="success"
                    # ).inc()
                    # metrics.ai_adapter_request_duration.labels(
                    #     provider=self.config.provider.value
                    # ).observe(elapsed)
                    
                    logger.info(
                        "AI suggestion generated successfully",
                        request_id=request_id,
                        provider=self.config.provider.value,
                        model=self.config.model,
                        elapsed=elapsed,
                        correlation_id=correlation_id
                    )
                    
                    return script_response
                    
                except asyncio.TimeoutError:
                    self.circuit_breaker.record_failure()
                    last_exception = AIException(
                        f"Request timeout after {actual_timeout} seconds",
                        AIErrorCode.TIMEOUT,
                        f"{actual_timeout} saniye sonra zaman aşımı"
                    )
                    
                    if attempt < retries - 1:
                        # Exponential backoff with jitter
                        wait_time = (2 ** attempt) + (0.1 * (2 ** attempt) * (0.5 - time.time() % 1))
                        await asyncio.sleep(wait_time)
                        logger.warning(
                            f"Retrying after timeout (attempt {attempt + 1}/{retries})",
                            wait_time=wait_time
                        )
                    
                except Exception as e:
                    self.circuit_breaker.record_failure()
                    last_exception = e
                    
                    if attempt < retries - 1:
                        wait_time = (2 ** attempt) + (0.1 * (2 ** attempt) * (0.5 - time.time() % 1))
                        await asyncio.sleep(wait_time)
                        logger.warning(
                            f"Retrying after error (attempt {attempt + 1}/{retries}): {str(e)}",
                            wait_time=wait_time
                        )
            
            # All retries failed
            # metrics.ai_adapter_requests_total.labels(
            #     provider=self.config.provider.value,
            #     status="failed"
            # ).inc()
            
            if isinstance(last_exception, AIException):
                raise last_exception
            else:
                raise AIException(
                    f"Failed after {retries} attempts: {str(last_exception)}",
                    AIErrorCode.PROVIDER_ERROR,
                    f"{retries} denemeden sonra başarısız: {str(last_exception)}"
                )
    
    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        timeout: int
    ) -> Dict[str, Any]:
        """Call the AI provider with native async and proper error handling."""
        if not self._client:
            raise AIException(
                "AI client not initialized",
                AIErrorCode.CONFIG_ERROR,
                "AI istemcisi başlatılmadı"
            )
        
        try:
            # Use asyncio timeout for network timeout control
            async with asyncio.timeout(timeout):
                # CRITICAL FIX: Use native async API - no asyncio.to_thread needed
                completion = await self._client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self.config.temperature,
                    response_format={"type": "json_object"},  # Force JSON response
                    # Stream handling for partial responses
                    stream=False  # Set to True if we want to handle partial responses
                )
                
                # Handle response
                if not completion.choices:
                    raise AIException(
                        "No response choices from AI provider",
                        AIErrorCode.INVALID_RESPONSE,
                        "AI sağlayıcıdan yanıt seçeneği yok"
                    )
                
                return {
                    "content": completion.choices[0].message.content,
                    "usage": {
                        "prompt_tokens": completion.usage.prompt_tokens if completion.usage else 0,
                        "completion_tokens": completion.usage.completion_tokens if completion.usage else 0,
                        "total_tokens": completion.usage.total_tokens if completion.usage else 0
                    },
                    "model": completion.model,
                    "finish_reason": completion.choices[0].finish_reason
                }
                
        except asyncio.TimeoutError:
            # Network timeout - different from API timeout
            logger.error(f"Network timeout after {timeout} seconds")
            raise AIException(
                f"Network timeout after {timeout} seconds",
                AIErrorCode.TIMEOUT,
                f"Ağ zaman aşımı: {timeout} saniye"
            )
        except asyncio.CancelledError:
            # Stream interruption
            logger.error("Request was cancelled/interrupted")
            raise AIException(
                "Request was cancelled or interrupted",
                AIErrorCode.TIMEOUT,
                "İstek iptal edildi veya kesintiye uğradı"
            )
        except Exception as e:
            # Distinguish different error types
            error_msg = str(e)
            
            # Token limit exceeded
            if "maximum context length" in error_msg.lower() or "token" in error_msg.lower():
                raise AIException(
                    f"Token limit exceeded: {error_msg}",
                    AIErrorCode.INVALID_RESPONSE,
                    f"Token limiti aşıldı: {error_msg}"
                )
            
            # Rate limiting from provider
            if "rate limit" in error_msg.lower() or "429" in error_msg:
                raise AIException(
                    f"Provider rate limit: {error_msg}",
                    AIErrorCode.RATE_LIMITED,
                    f"Sağlayıcı hız limiti: {error_msg}"
                )
            
            # API deprecation warnings
            if "deprecated" in error_msg.lower():
                logger.warning(f"API deprecation warning: {error_msg}")
                # Continue but log the warning
            
            # API timeout (different from network timeout)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise AIException(
                    f"API processing timeout: {error_msg}",
                    AIErrorCode.TIMEOUT,
                    f"API işleme zaman aşımı: {error_msg}"
                )
            
            # Generic provider error
            logger.error(f"Provider API call failed: {e}")
            raise AIException(
                f"Provider error: {error_msg}",
                AIErrorCode.PROVIDER_ERROR,
                f"Sağlayıcı hatası: {error_msg}"
            )
    
    def _parse_response(self, response: Dict[str, Any]) -> FreeCADScriptResponse:
        """Parse and validate AI response."""
        try:
            content = response.get("content", "")
            
            # Strip markdown if present
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            
            # Parse JSON
            data = json.loads(content)
            
            # Validate required fields
            if "script_py" not in data:
                raise AIException(
                    "Missing script_py in response",
                    AIErrorCode.MISSING_DATA,
                    "Yanıtta script_py eksik"
                )
            
            # Create response object
            return FreeCADScriptResponse(**data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            raise AIException(
                "Invalid JSON response from AI",
                AIErrorCode.INVALID_RESPONSE,
                "AI'dan geçersiz JSON yanıtı"
            )
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            raise AIException(
                f"Response parsing failed: {str(e)}",
                AIErrorCode.INVALID_RESPONSE,
                f"Yanıt ayrıştırma başarısız: {str(e)}"
            )
    
    def _validate_script_security(self, script: str):
        """Validate script for security violations using shared security validator."""
        from ..core.security_validator import security_validator, SecurityValidationError
        
        try:
            is_valid, violations = security_validator.validate_script(script, raise_on_error=False)
            
            if not is_valid:
                # Log all violations
                for violation in violations:
                    logger.warning(f"Script security violation: {violation}")
                
                # Raise exception with combined violations
                raise AIException(
                    f"Security violations detected: {'; '.join(violations[:3])}",  # Show first 3
                    AIErrorCode.SECURITY_VIOLATION,
                    f"Güvenlik ihlalleri tespit edildi: {'; '.join(violations[:3])}"
                )
        except SecurityValidationError as e:
            # Security validator raised an error
            raise AIException(
                str(e),
                AIErrorCode.SECURITY_VIOLATION,
                f"Güvenlik doğrulama hatası: {str(e)}"
            )


# Global adapter instance
ai_adapter = AIAdapter()