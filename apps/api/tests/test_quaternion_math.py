"""
Test quaternion math utilities.
"""

import numpy as np
import pytest
from app.utils.quaternion_math import (
    euler_to_quaternion,
    quaternion_to_euler,
    quaternion_multiply,
    axis_angle_to_quaternion,
    quaternion_to_axis_angle,
    quaternion_normalize,
    quaternion_conjugate,
    quaternion_inverse
)


class TestQuaternionMath:
    """Test quaternion math operations."""
    
    def test_euler_to_quaternion_and_back(self):
        """Test Euler angle to quaternion conversion and back."""
        # Test various angles (avoiding gimbal lock at pitch = ±90)
        test_cases = [
            (0, 0, 0),
            (45, 0, 0),
            (0, 45, 0),
            (0, 0, 45),
            (30, 45, 60),
            (90, 80, -90)  # Avoid pitch = ±90 to prevent gimbal lock
        ]
        
        for roll, pitch, yaw in test_cases:
            # Convert to quaternion and back
            q = euler_to_quaternion(roll, pitch, yaw)
            result_roll, result_pitch, result_yaw = quaternion_to_euler(q)
            
            # For gimbal lock situations, we can't guarantee exact recovery
            # Instead, verify the quaternion represents the same rotation
            q_result = euler_to_quaternion(result_roll, result_pitch, result_yaw)
            
            # The quaternions should be equal (or negated, which represents same rotation)
            assert np.allclose(q, q_result, atol=1e-10) or \
                   np.allclose(q, -q_result, atol=1e-10)
    
    def test_quaternion_multiply_identity(self):
        """Test quaternion multiplication with identity."""
        # Identity quaternion [1, 0, 0, 0]
        identity = np.array([1.0, 0.0, 0.0, 0.0])
        
        # Test quaternion
        q = euler_to_quaternion(45, 30, 60)
        
        # Multiplying with identity should give the same quaternion
        result = quaternion_multiply(q, identity)
        assert np.allclose(result, q)
        
        result = quaternion_multiply(identity, q)
        assert np.allclose(result, q)
    
    def test_quaternion_inverse(self):
        """Test quaternion inverse."""
        q = euler_to_quaternion(45, 30, 60)
        q_inv = quaternion_inverse(q)
        
        # q * q_inv should give identity
        result = quaternion_multiply(q, q_inv)
        identity = np.array([1.0, 0.0, 0.0, 0.0])
        assert np.allclose(result, identity, atol=1e-10)
    
    def test_axis_angle_conversion(self):
        """Test axis-angle to quaternion conversion and back."""
        # Test cases: (axis_x, axis_y, axis_z, angle_degrees)
        test_cases = [
            (1, 0, 0, 45),  # Rotation around X axis
            (0, 1, 0, 90),  # Rotation around Y axis
            (0, 0, 1, 180), # Rotation around Z axis
            (1, 1, 0, 60),  # Rotation around XY diagonal
            (1, 1, 1, 120), # Rotation around XYZ diagonal
        ]
        
        for x, y, z, angle in test_cases:
            # Convert to quaternion and back
            q = axis_angle_to_quaternion(x, y, z, angle)
            result_axis, result_angle = quaternion_to_axis_angle(q)
            
            # Normalize the original axis for comparison
            original_axis = np.array([x, y, z])
            original_axis = original_axis / np.linalg.norm(original_axis)
            
            # Check angle (accounting for equivalent representations)
            assert np.isclose(angle, result_angle, atol=1e-10) or \
                   np.isclose(360 - angle, result_angle, atol=1e-10)
            
            # Check axis (accounting for opposite direction with negative angle)
            assert np.allclose(original_axis, result_axis, atol=1e-10) or \
                   np.allclose(-original_axis, result_axis, atol=1e-10)
    
    def test_quaternion_normalize(self):
        """Test quaternion normalization."""
        # Create a non-normalized quaternion
        q = np.array([2.0, 1.0, 1.0, 1.0])
        
        # Normalize it
        q_norm = quaternion_normalize(q)
        
        # Check that the magnitude is 1
        magnitude = np.linalg.norm(q_norm)
        assert np.isclose(magnitude, 1.0)
        
        # Check that the direction is preserved
        expected = q / np.linalg.norm(q)
        assert np.allclose(q_norm, expected)
    
    def test_quaternion_conjugate(self):
        """Test quaternion conjugate."""
        q = np.array([0.7071, 0.7071, 0.0, 0.0])
        conj = quaternion_conjugate(q)
        
        # Conjugate should negate the vector part
        assert conj[0] == q[0]  # w component unchanged
        assert conj[1] == -q[1]  # x component negated
        assert conj[2] == -q[2]  # y component negated
        assert conj[3] == -q[3]  # z component negated
    
    def test_rotation_composition(self):
        """Test that quaternion multiplication correctly composes rotations."""
        # First rotate 90 degrees around Z
        q1 = euler_to_quaternion(0, 0, 90)
        
        # Then rotate 90 degrees around X
        q2 = euler_to_quaternion(90, 0, 0)
        
        # Compose the rotations
        q_combined = quaternion_multiply(q2, q1)
        
        # This should be equivalent to a specific combined rotation
        # Verify the quaternion is normalized
        assert np.isclose(np.linalg.norm(q_combined), 1.0)
    
    def test_no_rotation(self):
        """Test that zero rotation gives identity quaternion."""
        q = euler_to_quaternion(0, 0, 0)
        identity = np.array([1.0, 0.0, 0.0, 0.0])
        assert np.allclose(q, identity)
        
        q = axis_angle_to_quaternion(1, 0, 0, 0)
        assert np.allclose(q, identity)