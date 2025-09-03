"""Assembly4 Router for handling assembly-related API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.schemas.assembly4 import (
    Assembly4Create,
    Assembly4Response,
    Assembly4Update,
    PartAdd,
    ConstraintApply,
    CAMPathGenerate,
    Assembly4Export,
    Assembly4Info
)
from app.services.assembly4_service import assembly4_service
from app.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/assembly4",
    tags=["Assembly4"],
    responses={404: {"description": "Not found"}},
)


@router.post("/", response_model=Assembly4Response)
async def create_assembly(
    request: Assembly4Create,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new Assembly4 assembly.
    
    Creates an assembly with the specified parts and constraints.
    Optionally includes CAM settings for path generation.
    """
    try:
        logger.info(f"User {current_user.email} creating Assembly4: {request.name}")
        
        # Create assembly with proper arguments
        # The service expects parts and constraints as separate arguments
        result = assembly4_service.create_assembly(
            name=request.name,
            parts=request.parts,  # Pass parts directly
            constraints=request.constraints,  # Pass constraints directly
            cam_settings=request.cam_settings
        )
        
        return Assembly4Response(
            id=result.get("id"),
            name=result.get("name"),
            parts_count=len(result.get("parts", [])),
            constraints_count=len(result.get("constraints", [])),
            status="created",
            message="Assembly oluşturuldu"
        )
        
    except ValidationError as e:
        logger.error(f"Validation error in assembly creation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating assembly: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Assembly oluşturma hatası: {str(e)}"
        )


@router.get("/{assembly_id}", response_model=Assembly4Info)
async def get_assembly(
    assembly_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed information about an assembly."""
    try:
        info = assembly4_service.get_assembly_info(assembly_id)
        
        return Assembly4Info(
            id=info.get("id"),
            name=info.get("name"),
            parts=info.get("parts", []),
            constraints=info.get("constraints", []),
            cam_paths=info.get("cam_paths", []),
            created_at=info.get("created_at"),
            updated_at=info.get("updated_at")
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting assembly info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Assembly bilgisi alınamadı: {str(e)}"
        )


@router.put("/{assembly_id}", response_model=Assembly4Response)
async def update_assembly(
    assembly_id: str,
    request: Assembly4Update,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing assembly."""
    try:
        # Implementation would go here
        # For now, return a placeholder response
        return Assembly4Response(
            id=assembly_id,
            name=request.name or "updated_assembly",
            parts_count=0,
            constraints_count=0,
            status="updated",
            message="Assembly güncellendi"
        )
        
    except Exception as e:
        logger.error(f"Error updating assembly: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Assembly güncelleme hatası: {str(e)}"
        )


@router.post("/{assembly_id}/parts", response_model=Assembly4Response)
async def add_part_to_assembly(
    assembly_id: str,
    request: PartAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a part to an existing assembly."""
    try:
        result = assembly4_service.add_part(
            assembly_id=assembly_id,
            part=request.part,
            position=request.position
        )
        
        return Assembly4Response(
            id=assembly_id,
            name=result.get("name", "assembly"),
            parts_count=result.get("parts_count", 0),
            constraints_count=result.get("constraints_count", 0),
            status="part_added",
            message="Parça eklendi"
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error adding part: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Parça ekleme hatası: {str(e)}"
        )


@router.post("/{assembly_id}/constraints", response_model=Assembly4Response)
async def apply_constraint(
    assembly_id: str,
    request: ConstraintApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a constraint to assembly parts."""
    try:
        result = assembly4_service.apply_constraint(
            assembly_id=assembly_id,
            constraint=request.constraint
        )
        
        return Assembly4Response(
            id=assembly_id,
            name=result.get("name", "assembly"),
            parts_count=result.get("parts_count", 0),
            constraints_count=result.get("constraints_count", 0),
            status="constraint_applied",
            message="Kısıt uygulandı"
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error applying constraint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Kısıt uygulama hatası: {str(e)}"
        )


@router.post("/{assembly_id}/cam-paths", response_model=Assembly4Response)
async def generate_cam_paths(
    assembly_id: str,
    request: CAMPathGenerate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate CAM paths for the assembly."""
    try:
        result = assembly4_service.generate_cam_paths(
            assembly_id=assembly_id,
            operation=request.operation,
            settings=request.settings
        )
        
        return Assembly4Response(
            id=assembly_id,
            name=result.get("name", "assembly"),
            parts_count=result.get("parts_count", 0),
            constraints_count=result.get("constraints_count", 0),
            status="paths_generated",
            message=f"CAM yolları oluşturuldu: {result.get('path_count', 0)} yol",
            gcode=result.get("gcode")
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error generating CAM paths: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CAM yolu oluşturma hatası: {str(e)}"
        )


@router.post("/{assembly_id}/export")
async def export_assembly(
    assembly_id: str,
    request: Assembly4Export,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export assembly in specified format."""
    try:
        export_path = assembly4_service.export_assembly(
            assembly_id=assembly_id,
            format=request.format,
            include_paths=request.include_paths
        )
        
        return {
            "status": "exported",
            "path": str(export_path),
            "format": request.format,
            "message": f"Assembly {request.format} formatında dışa aktarıldı"
        }
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error exporting assembly: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dışa aktarma hatası: {str(e)}"
        )


@router.delete("/{assembly_id}")
async def delete_assembly(
    assembly_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an assembly."""
    try:
        # Implementation would go here
        return {
            "status": "deleted",
            "id": assembly_id,
            "message": "Assembly silindi"
        }
        
    except Exception as e:
        logger.error(f"Error deleting assembly: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Silme hatası: {str(e)}"
        )