from fastapi import APIRouter, Response, status
import redis
import boto3

from ..config import settings
from ..db import check_db
from ..schemas import HealthStatus

try:
    import structlog
    from ..services.s3 import get_s3_service
    HAS_STRUCTLOG = True
    logger = structlog.get_logger(__name__)
except ImportError:
    HAS_STRUCTLOG = False
    logger = None


router = APIRouter(prefix="/api/v1", tags=["Sağlık"]) 


@router.get("/healthz", response_model=HealthStatus)
def healthz(response: Response) -> HealthStatus:
    deps: dict[str, str] = {}

    db_ok = check_db()
    deps["postgres"] = "ok" if db_ok else "hata"

    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        deps["redis"] = "ok"
    except Exception:
        deps["redis"] = "hata"

    if settings.aws_s3_endpoint:
        try:
            # Test legacy S3 connectivity
            session = boto3.session.Session(
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_s3_region,
            )
            s3 = session.client("s3", endpoint_url=settings.aws_s3_endpoint)
            s3.list_buckets()
            
            # Test new S3 service and bucket availability if available
            if HAS_STRUCTLOG:
                try:
                    s3_service = get_s3_service()
                    required_buckets = ["artefacts", "logs", "reports", "invoices"]
                    bucket_status = {}
                    
                    for bucket in required_buckets:
                        try:
                            bucket_exists = s3_service._ensure_bucket_exists(bucket)
                            bucket_status[bucket] = "ok" if bucket_exists else "eksik"
                        except Exception as e:
                            if logger:
                                logger.warning("Bucket check failed", bucket=bucket, error=str(e))
                            bucket_status[bucket] = "hata"
                    
                    # Overall S3 status
                    all_buckets_ok = all(status == "ok" for status in bucket_status.values())
                    deps["s3"] = "ok" if all_buckets_ok else "partial"
                    deps.update({f"s3_bucket_{bucket}": status for bucket, status in bucket_status.items()})
                except Exception as e:
                    if logger:
                        logger.error("S3 service check failed", error=str(e))
                    deps["s3"] = "ok"  # Fall back to basic connectivity
            else:
                deps["s3"] = "ok"  # Basic S3 connectivity works
            
        except Exception as e:
            deps["s3"] = "hata"
    else:
        deps["s3"] = "atılandı"

    overall = "ok" if all(v == "ok" for v in deps.values()) else "hata"
    response.status_code = status.HTTP_200_OK if overall == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthStatus(status=overall, dependencies=deps)


@router.get("/readyz", response_model=HealthStatus)
def readyz() -> HealthStatus:
    return healthz()


