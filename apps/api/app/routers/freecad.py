from fastapi import APIRouter, Depends, HTTPException, status

from ..freecad.service import detect_freecad
from ..services.freecad_service import freecad_service
from ..schemas import FreeCADDetectResponse
from ..core.security import get_current_user
from ..models.user import User


router = APIRouter(prefix="/api/v1/freecad", tags=["FreeCAD"]) 


@router.get("/detect", response_model=FreeCADDetectResponse)
def detect() -> FreeCADDetectResponse:
    """Legacy FreeCAD detection endpoint for backward compatibility."""
    return detect_freecad()


@router.get("/health")
def health_check():
    """
    Ultra-enterprise FreeCAD service health check endpoint.
    
    Returns comprehensive health status including:
    - FreeCAD availability and version
    - Circuit breaker state
    - Active processes count
    - Resource pool status
    """
    try:
        health_status = freecad_service.health_check()
        
        if not health_status['healthy']:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "FreeCAD service unhealthy",
                    "turkish_error": "FreeCAD servisi sağlıksız",
                    "health_status": health_status
                }
            )
        
        return health_status
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": f"Health check failed: {str(e)}",
                "turkish_error": f"Sağlık kontrolü başarısız: {str(e)}"
            }
        )


@router.get("/metrics")
def get_metrics(
    current_user: User = Depends(get_current_user)
):
    """
    Get FreeCAD service metrics summary.
    
    Requires authentication. Returns:
    - Active processes count
    - Circuit breaker state
    - Recent performance metrics
    """
    try:
        metrics_summary = freecad_service.get_metrics_summary()
        return metrics_summary
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": f"Failed to retrieve metrics: {str(e)}",
                "turkish_error": f"Metrik alınamadı: {str(e)}"
            }
        )


@router.post("/circuit-breaker/reset")
def reset_circuit_breaker(
    current_user: User = Depends(get_current_user)
):
    """
    Reset the FreeCAD service circuit breaker.
    
    Requires authentication. This is an administrative operation
    that should be used carefully to reset the circuit breaker
    after resolving underlying issues.
    """
    try:
        # Use the service's reset method
        freecad_service.reset_circuit_breaker()
        
        return {
            "success": True,
            "message": "Circuit breaker reset successfully",
            "turkish_message": "Devre kesici başarıyla sıfırlandı",
            "new_state": "CLOSED"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": f"Failed to reset circuit breaker: {str(e)}",
                "turkish_error": f"Devre kesici sıfırlanamadı: {str(e)}"
            }
        )


