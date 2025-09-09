"""
Shared quaternion and 3D rotation mathematics utilities for FreeCAD collaboration.
Provides conversion between different rotation representations used in FreeCAD.
"""

import numpy as np
from typing import Tuple


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """
    Convert Euler angles (in degrees) to quaternion.
    
    Args:
        roll: Rotation around X axis in degrees
        pitch: Rotation around Y axis in degrees
        yaw: Rotation around Z axis in degrees
    
    Returns:
        Quaternion as [w, x, y, z] numpy array
    """
    # Convert degrees to radians
    roll = np.radians(roll)
    pitch = np.radians(pitch)
    yaw = np.radians(yaw)
    
    # Calculate quaternion components
    cy = np.cos(yaw * 0.5)
    sy = np.sin(yaw * 0.5)
    cp = np.cos(pitch * 0.5)
    sp = np.sin(pitch * 0.5)
    cr = np.cos(roll * 0.5)
    sr = np.sin(roll * 0.5)
    
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    
    return np.array([w, x, y, z])


def quaternion_to_euler(q: np.ndarray) -> Tuple[float, float, float]:
    """
    Convert quaternion to Euler angles (in degrees).
    
    Args:
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Tuple of (roll, pitch, yaw) in degrees
    """
    w, x, y, z = q
    
    # Roll (x-axis rotation)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = np.arctan2(sinr_cosp, cosr_cosp)
    
    # Pitch (y-axis rotation)
    sinp = 2 * (w * y - z * x)
    if np.abs(sinp) >= 1:
        pitch = np.copysign(np.pi / 2, sinp)  # Use 90 degrees if out of range
    else:
        pitch = np.arcsin(sinp)
    
    # Yaw (z-axis rotation)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = np.arctan2(siny_cosp, cosy_cosp)
    
    # Convert radians to degrees
    return (np.degrees(roll), np.degrees(pitch), np.degrees(yaw))


def quaternion_multiply(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """
    Multiply two quaternions (Hamilton product).
    
    Args:
        q1: First quaternion as [w, x, y, z] numpy array
        q2: Second quaternion as [w, x, y, z] numpy array
    
    Returns:
        Product quaternion as [w, x, y, z] numpy array
    """
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    
    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
    
    return np.array([w, x, y, z])


def axis_angle_to_quaternion(x: float, y: float, z: float, angle: float) -> np.ndarray:
    """
    Convert axis-angle representation to quaternion.
    
    Args:
        x: X component of rotation axis
        y: Y component of rotation axis
        z: Z component of rotation axis
        angle: Rotation angle in degrees
    
    Returns:
        Quaternion as [w, x, y, z] numpy array
    """
    # Normalize the axis
    axis = np.array([x, y, z])
    axis_length = np.linalg.norm(axis)
    
    if axis_length < 1e-10:
        # No rotation
        return np.array([1.0, 0.0, 0.0, 0.0])
    
    axis = axis / axis_length
    
    # Convert angle to radians if needed
    angle_rad = np.radians(angle) if angle > 2 * np.pi else angle
    
    # Calculate quaternion
    half_angle = angle_rad * 0.5
    s = np.sin(half_angle)
    
    w = np.cos(half_angle)
    x = axis[0] * s
    y = axis[1] * s
    z = axis[2] * s
    
    return np.array([w, x, y, z])


def quaternion_to_axis_angle(q: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Convert quaternion to axis-angle representation.
    
    Args:
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Tuple of (axis as [x, y, z] numpy array, angle in degrees)
    """
    w, x, y, z = q
    
    # Calculate angle
    angle_rad = 2 * np.arccos(np.clip(w, -1.0, 1.0))
    
    # Calculate axis
    s = np.sqrt(1 - w * w)
    
    if s < 1e-10:
        # No rotation or very small rotation
        axis = np.array([0.0, 0.0, 1.0])  # Default axis
    else:
        axis = np.array([x / s, y / s, z / s])
    
    # Convert angle to degrees
    angle = np.degrees(angle_rad)
    
    return axis, angle


def quaternion_conjugate(q: np.ndarray) -> np.ndarray:
    """
    Calculate the conjugate of a quaternion.
    
    Args:
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Conjugate quaternion as [w, -x, -y, -z] numpy array
    """
    w, x, y, z = q
    return np.array([w, -x, -y, -z])


def quaternion_inverse(q: np.ndarray) -> np.ndarray:
    """
    Calculate the inverse of a quaternion.
    
    Args:
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Inverse quaternion
    """
    conj = quaternion_conjugate(q)
    norm_sq = np.dot(q, q)
    
    if norm_sq < 1e-10:
        raise ValueError("Cannot invert zero quaternion")
    
    return conj / norm_sq


def quaternion_normalize(q: np.ndarray) -> np.ndarray:
    """
    Normalize a quaternion to unit length.
    
    Args:
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Normalized quaternion
    """
    norm = np.linalg.norm(q)
    
    if norm < 1e-10:
        return np.array([1.0, 0.0, 0.0, 0.0])
    
    return q / norm


def quaternion_slerp(q1: np.ndarray, q2: np.ndarray, t: float) -> np.ndarray:
    """
    Spherical linear interpolation between two quaternions.
    
    Args:
        q1: Start quaternion as [w, x, y, z] numpy array
        q2: End quaternion as [w, x, y, z] numpy array
        t: Interpolation parameter (0.0 to 1.0)
    
    Returns:
        Interpolated quaternion
    """
    # Normalize input quaternions
    q1 = quaternion_normalize(q1)
    q2 = quaternion_normalize(q2)
    
    # Calculate dot product
    dot = np.dot(q1, q2)
    
    # If quaternions are very close, use linear interpolation
    if abs(dot) > 0.9995:
        result = q1 + t * (q2 - q1)
        return quaternion_normalize(result)
    
    # Ensure shortest path
    if dot < 0:
        q2 = -q2
        dot = -dot
    
    # Clamp dot product
    dot = np.clip(dot, -1.0, 1.0)
    
    # Calculate angle and interpolation coefficients
    theta_0 = np.arccos(dot)
    theta = theta_0 * t
    
    # Calculate interpolated quaternion
    q3 = quaternion_normalize(q2 - q1 * dot)
    return q1 * np.cos(theta) + q3 * np.sin(theta)


def rotate_vector_by_quaternion(v: np.ndarray, q: np.ndarray) -> np.ndarray:
    """
    Rotate a 3D vector by a quaternion.
    
    Args:
        v: 3D vector as [x, y, z] numpy array
        q: Quaternion as [w, x, y, z] numpy array
    
    Returns:
        Rotated vector as [x, y, z] numpy array
    """
    # Convert vector to quaternion form [0, x, y, z]
    v_quat = np.array([0, v[0], v[1], v[2]])
    
    # Rotate: q * v * q^-1
    q_conj = quaternion_conjugate(q)
    result_quat = quaternion_multiply(quaternion_multiply(q, v_quat), q_conj)
    
    # Extract vector part
    return result_quat[1:]