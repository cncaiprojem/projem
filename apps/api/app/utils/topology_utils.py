"""
Shared topology utilities for Task 7.24

This module provides common topology analysis functions used by both
geometric_validator.py and quality_metrics.py to avoid code duplication.
"""

from typing import Any, Dict, List, Tuple, Optional
from collections import defaultdict

from ..core.logging import get_logger

logger = get_logger(__name__)

# Performance optimization constants
MAX_EDGE_CONTINUITY_CHECKS = 500  # Limit total checks
MAX_EDGES_FOR_FULL_CHECK = 50  # Skip detailed check for very complex models


def build_vertex_edge_map(edges: List[Any]) -> Dict[Any, List[Tuple[Any, float]]]:
    """
    Build a map from vertex positions to edges for efficient connectivity checking.
    
    Args:
        edges: List of edge objects with Curve and ParameterRange attributes
        
    Returns:
        Dictionary mapping vertex coordinates to list of (edge, parameter) tuples
    """
    vertex_to_edges = {}
    
    for edge in edges:
        try:
            if not hasattr(edge, 'Curve') or not hasattr(edge, 'ParameterRange'):
                continue
                
            param_range = edge.ParameterRange
            curve = edge.Curve
            
            # Store edge endpoints in the vertex map
            for t in [param_range[0], param_range[1]]:
                try:
                    point = curve.value(t)
                    # Round coordinates to avoid floating point issues
                    if hasattr(point, 'x'):
                        key = (round(point.x, 3), round(point.y, 3), round(point.z, 3))
                    else:
                        key = str(point)
                    
                    if key not in vertex_to_edges:
                        vertex_to_edges[key] = []
                    vertex_to_edges[key].append((edge, t))
                except Exception as e:
                    logger.debug(f"Failed to process edge vertex: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Failed to process edge in vertex-edge map: {e}")
            continue
    
    return vertex_to_edges


def check_edge_continuity(
    edges: List[Any],
    sample_subset: bool = True
) -> Dict[str, int]:
    """
    Check edge continuity (G0, G1, G2) for a set of edges.
    
    Args:
        edges: List of edge objects to check
        sample_subset: If True and edges > MAX_EDGES_FOR_FULL_CHECK, sample a subset
        
    Returns:
        Dictionary with discontinuity counts for 'g0', 'g1', 'g2'
    """
    discontinuities = {
        'g0': 0,  # Position discontinuity
        'g1': 0,  # Tangent discontinuity
        'g2': 0   # Curvature discontinuity
    }
    
    num_edges = len(edges)
    
    # Sample edges if too many
    if sample_subset and num_edges > MAX_EDGES_FOR_FULL_CHECK:
        import random
        sample_size = min(20, num_edges // 5)  # Check ~20% or max 20 edges
        sampled_edges = random.sample(edges, sample_size)
        logger.debug(f"Complex model with {num_edges} edges - sampling {sample_size} edges")
    else:
        sampled_edges = edges
    
    # Build vertex-to-edge map for efficient connectivity checking
    vertex_to_edges = build_vertex_edge_map(sampled_edges)
    
    checks_performed = 0
    
    # Check continuity only between connected edges
    for vertex_key, edge_list in vertex_to_edges.items():
        if checks_performed >= MAX_EDGE_CONTINUITY_CHECKS:
            logger.debug(f"Reached maximum edge continuity checks ({MAX_EDGE_CONTINUITY_CHECKS})")
            break
            
        # Only check edges that share this vertex
        if len(edge_list) < 2:
            continue
            
        for i, (edge1, t1) in enumerate(edge_list):
            for j, (edge2, t2) in enumerate(edge_list[i+1:], i+1):
                if checks_performed >= MAX_EDGE_CONTINUITY_CHECKS:
                    break
                    
                checks_performed += 1
                
                try:
                    curve1 = edge1.Curve
                    curve2 = edge2.Curve
                    
                    # Check G1 continuity (tangent)
                    if hasattr(curve1, 'tangent') and hasattr(curve2, 'tangent'):
                        tan1 = curve1.tangent(t1)
                        tan2 = curve2.tangent(t2)
                        
                        if tan1 and tan2:
                            # Check if tangents are parallel
                            dot_product = abs(tan1[0].dot(tan2[0])) if hasattr(tan1[0], 'dot') else 1.0
                            if dot_product < 0.95:  # Not parallel
                                discontinuities['g1'] += 1
                    
                    # Check G2 continuity (curvature)
                    if hasattr(curve1, 'curvature') and hasattr(curve2, 'curvature'):
                        curv1 = curve1.curvature(t1)
                        curv2 = curve2.curvature(t2)
                        
                        if curv1 is not None and curv2 is not None:
                            curv_diff = abs(curv1 - curv2)
                            if curv_diff > 0.1:  # Curvature discontinuity
                                discontinuities['g2'] += 1
                                
                except Exception as e:
                    logger.debug(f"Continuity check error: {e}")
                    continue
    
    return discontinuities


def calculate_continuity_score(
    edges: List[Any],
    discontinuities: Optional[Dict[str, int]] = None
) -> float:
    """
    Calculate a continuity score based on discontinuities found.
    
    Args:
        edges: List of edges that were checked
        discontinuities: Pre-calculated discontinuities, or None to calculate
        
    Returns:
        Continuity score between 0.0 and 1.0
    """
    if discontinuities is None:
        discontinuities = check_edge_continuity(edges)
    
    # Calculate continuity score based on discontinuities
    total_checks = len(edges) * 3  # 3 types of continuity per edge
    
    if total_checks > 0:
        # Penalize based on discontinuity severity
        g0_penalty = discontinuities.get('g0', 0) * 0.5 / total_checks
        g1_penalty = discontinuities.get('g1', 0) * 0.3 / total_checks
        g2_penalty = discontinuities.get('g2', 0) * 0.2 / total_checks
        
        continuity_score = max(0.0, 1.0 - g0_penalty - g1_penalty - g2_penalty)
    else:
        continuity_score = 1.0
    
    return continuity_score


def find_edge_face_connections(shape: Any) -> Dict[Any, List[int]]:
    """
    Build a mapping of edges to the faces that share them.
    
    Args:
        shape: Shape object with Edges and Faces attributes
        
    Returns:
        Dictionary mapping edge keys to list of face indices
    """
    edge_face_map = defaultdict(list)
    
    try:
        if hasattr(shape, 'Faces'):
            for face_idx, face in enumerate(shape.Faces):
                if hasattr(face, 'Edges'):
                    for edge in face.Edges:
                        # Use edge vertices as unique identifier
                        if hasattr(edge, 'Vertexes') and len(edge.Vertexes) >= 2:
                            v1 = edge.Vertexes[0].Point
                            v2 = edge.Vertexes[-1].Point
                            # Make edge key canonical by sorting vertices
                            vert1 = (round(v1.x, 4), round(v1.y, 4), round(v1.z, 4))
                            vert2 = (round(v2.x, 4), round(v2.y, 4), round(v2.z, 4))
                            edge_key = tuple(sorted([vert1, vert2]))
                            edge_face_map[edge_key].append(face_idx)
    except Exception as e:
        logger.warning(f"Error building edge-face connections: {e}")
    
    return dict(edge_face_map)


def detect_non_manifold_edges(
    shape: Any,
    edge_face_map: Optional[Dict[Any, List[int]]] = None
) -> List[Dict[str, Any]]:
    """
    Detect non-manifold edges in a shape.
    
    Non-manifold edges are those shared by != 2 faces.
    
    Args:
        shape: Shape object with Edges attribute
        edge_face_map: Pre-computed edge-face mapping, or None to compute
        
    Returns:
        List of non-manifold edge information
    """
    non_manifold = []
    
    try:
        if edge_face_map is None:
            edge_face_map = find_edge_face_connections(shape)
        
        if hasattr(shape, 'Edges'):
            for edge_idx, edge in enumerate(shape.Edges):
                if hasattr(edge, 'Vertexes') and len(edge.Vertexes) >= 2:
                    v1 = edge.Vertexes[0].Point
                    v2 = edge.Vertexes[-1].Point
                    # Make edge key canonical by sorting vertices
                    vert1 = (round(v1.x, 4), round(v1.y, 4), round(v1.z, 4))
                    vert2 = (round(v2.x, 4), round(v2.y, 4), round(v2.z, 4))
                    edge_key = tuple(sorted([vert1, vert2]))
                    
                    face_count = len(edge_face_map.get(edge_key, []))
                    
                    if face_count != 2 and face_count > 0:
                        non_manifold.append({
                            "edge_index": edge_idx,
                            "face_count": face_count,
                            "faces": edge_face_map[edge_key],
                            "length": edge.Length if hasattr(edge, 'Length') else 0.0
                        })
    except Exception as e:
        logger.warning(f"Non-manifold edge detection error: {e}")
    
    return non_manifold


def detect_open_edges(shape: Any) -> List[Dict[str, Any]]:
    """
    Detect open edges in a shape.
    
    Open edges are those shared by exactly one face.
    
    Args:
        shape: Shape object
        
    Returns:
        List of open edge information
    """
    open_edges = []
    
    try:
        edge_face_map = find_edge_face_connections(shape)
        
        if hasattr(shape, 'Edges'):
            for edge_idx, edge in enumerate(shape.Edges):
                if hasattr(edge, 'Vertexes') and len(edge.Vertexes) >= 2:
                    v1 = edge.Vertexes[0].Point
                    v2 = edge.Vertexes[-1].Point
                    # Make edge key canonical by sorting vertices
                    vert1 = (round(v1.x, 4), round(v1.y, 4), round(v1.z, 4))
                    vert2 = (round(v2.x, 4), round(v2.y, 4), round(v2.z, 4))
                    edge_key = tuple(sorted([vert1, vert2]))
                    
                    face_count = len(edge_face_map.get(edge_key, []))
                    
                    if face_count == 1:
                        open_edges.append({
                            "edge_index": edge_idx,
                            "faces": edge_face_map[edge_key],
                            "length": edge.Length if hasattr(edge, 'Length') else 0.0
                        })
    except Exception as e:
        logger.warning(f"Open edge detection error: {e}")
    
    return open_edges