"""
FreeCAD utility functions for model validation.

This module provides common FreeCAD-related utilities used across
different validation services.
"""

from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


def get_shape_from_document(doc_handle: Any) -> Optional[Any]:
    """
    Extract shape from FreeCAD document.
    
    Args:
        doc_handle: FreeCAD document object
        
    Returns:
        The first valid shape found in the document, or None if no valid shape found
    """
    try:
        # Import FreeCAD modules
        import FreeCAD
        import Part
        
        if not doc_handle:
            return None
        
        # Find the first solid or compound shape in the document
        for obj in doc_handle.Objects:
            if hasattr(obj, 'Shape'):
                shape = obj.Shape
                # Return the first valid shape found
                if shape and (shape.ShapeType in ['Solid', 'Compound', 'CompSolid', 'Shell']):
                    return shape
        
        # If no solid found, try to create a compound of all shapes
        shapes = []
        for obj in doc_handle.Objects:
            if hasattr(obj, 'Shape') and obj.Shape:
                shapes.append(obj.Shape)
        
        if shapes:
            if len(shapes) == 1:
                return shapes[0]
            else:
                # Create a compound shape from all shapes
                compound = Part.makeCompound(shapes)
                return compound
        
        return None
        
    except Exception as e:
        logger.error(f"Error extracting shape from document: {e}")
        return None