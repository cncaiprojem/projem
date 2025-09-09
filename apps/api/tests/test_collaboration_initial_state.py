"""
Test suite for CollaborationProtocol _send_initial_state method implementation.
Tests the fix for PR #547 HIGH PRIORITY issue.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, UTC
import asyncio


class TestCollaborationInitialState:
    """Test the _send_initial_state method sends complete document state."""
    
    @pytest.mark.asyncio
    async def test_send_initial_state_with_existing_document(self):
        """Test that initial state includes document objects and properties."""
        from app.services.collaboration_protocol import (
            CollaborationProtocol,
            CollaborationSession
        )
        
        # Create protocol instance
        protocol = CollaborationProtocol()
        
        # Create mock WebSocket manager
        mock_websocket_manager = AsyncMock()
        protocol.websocket_manager = mock_websocket_manager
        
        # Create mock session
        session = CollaborationSession(
            document_id="doc_test123",
            session_id="session_456"
        )
        session.operation_version = 5
        session.participants.add("user1")
        session.participants.add("user2")
        
        # Mock FreeCAD document manager
        with patch('app.services.collaboration_protocol.document_manager') as mock_doc_manager:
            # Create mock document handle
            mock_doc_handle = Mock()
            mock_doc_manager._doc_handles = {"doc_test123": mock_doc_handle}
            
            # Create mock adapter with snapshot data
            mock_adapter = Mock()
            mock_snapshot = {
                "objects": [
                    {
                        "Name": "Box001",
                        "Label": "Box",
                        "TypeId": "Part::Box",
                        "Properties": {
                            "Length": 10.0,
                            "Width": 5.0,
                            "Height": 3.0
                        }
                    },
                    {
                        "Name": "Cylinder001",
                        "Label": "Cylinder",
                        "TypeId": "Part::Cylinder",
                        "Properties": {
                            "Radius": 2.5,
                            "Height": 8.0
                        }
                    }
                ],
                "properties": {
                    "Author": "TestUser",
                    "Company": "TestCompany",
                    "License": "CC-BY-SA"
                },
                "metadata": {
                    "Name": "TestDocument",
                    "FileName": "/tmp/test.FCStd",
                    "Label": "Test Document",
                    "Uid": "12345-67890"
                }
            }
            mock_adapter.take_snapshot.return_value = mock_snapshot
            mock_doc_manager.adapter = mock_adapter
            
            # Call the method
            connection_id = "conn_789"
            await protocol._send_initial_state(connection_id, session)
            
            # Verify the message was sent
            mock_websocket_manager.send_to_connection.assert_called_once()
            call_args = mock_websocket_manager.send_to_connection.call_args
            
            assert call_args[0][0] == connection_id
            message = call_args[0][1]
            
            # Verify message structure
            assert message["type"] == "initial_state"
            assert message["document_id"] == "doc_test123"
            assert message["version"] == 5
            assert set(message["participants"]) == {"user1", "user2"}
            assert message["pending_conflicts"] == 0
            
            # Verify document state
            assert "document_state" in message
            assert message["document_state"]["object_count"] == 2
            assert message["document_state"]["properties"] == mock_snapshot["properties"]
            assert message["document_state"]["metadata"] == mock_snapshot["metadata"]
            
            # Verify objects are included
            assert "objects" in message
            assert len(message["objects"]) == 2
            assert message["objects"][0]["Name"] == "Box001"
            assert message["objects"][1]["Name"] == "Cylinder001"
            
            # Verify timestamp is included
            assert "timestamp" in message
    
    @pytest.mark.asyncio
    async def test_send_initial_state_with_operation_history(self):
        """Test that initial state includes operation history."""
        from app.services.collaboration_protocol import (
            CollaborationProtocol,
            CollaborationSession
        )
        from app.services.operational_transform import ModelOperation, OperationType
        
        # Create protocol instance
        protocol = CollaborationProtocol()
        
        # Create mock WebSocket manager
        mock_websocket_manager = AsyncMock()
        protocol.websocket_manager = mock_websocket_manager
        
        # Create session with operation history
        session = CollaborationSession(document_id="doc_test456")
        
        # Add some operations to history
        for i in range(150):  # More than 100 to test limiting
            op = ModelOperation(
                id=f"op_{i}",
                type=OperationType.MODIFY,
                object_id=f"obj_{i}",
                parameters={"value": i}
            )
            session.operation_history.append(op)
        
        # Mock document manager
        with patch('app.services.collaboration_protocol.document_manager') as mock_doc_manager:
            mock_doc_manager._doc_handles = {}  # No document handle
            
            # Call the method
            connection_id = "conn_999"
            await protocol._send_initial_state(connection_id, session)
            
            # Verify the message was sent
            mock_websocket_manager.send_to_connection.assert_called_once()
            message = mock_websocket_manager.send_to_connection.call_args[0][1]
            
            # Verify operation history is included and limited to 100
            assert "operation_history" in message
            assert len(message["operation_history"]) == 100
            
            # Verify we got the last 100 operations (50-149)
            assert message["operation_history"][0]["id"] == "op_50"
            assert message["operation_history"][-1]["id"] == "op_149"
    
    @pytest.mark.asyncio
    async def test_send_initial_state_creates_document_if_not_exists(self):
        """Test that document is created/opened if not in handles."""
        from app.services.collaboration_protocol import (
            CollaborationProtocol,
            CollaborationSession
        )
        
        # Create protocol instance
        protocol = CollaborationProtocol()
        
        # Create mock WebSocket manager
        mock_websocket_manager = AsyncMock()
        protocol.websocket_manager = mock_websocket_manager
        
        # Create session
        session = CollaborationSession(document_id="doc_newjob")
        
        # Mock document manager
        with patch('app.services.collaboration_protocol.document_manager') as mock_doc_manager:
            # Initially no document handle
            mock_doc_manager._doc_handles = {}
            
            # Mock open_document to simulate document creation
            mock_metadata = Mock()
            mock_doc_manager.open_document = Mock(return_value=mock_metadata)
            
            # After open_document, add handle
            def side_effect_open(*args, **kwargs):
                mock_doc_manager._doc_handles["doc_newjob"] = Mock()
                return mock_metadata
            
            mock_doc_manager.open_document.side_effect = side_effect_open
            
            # Mock adapter
            mock_adapter = Mock()
            mock_adapter.take_snapshot.return_value = {
                "objects": [],
                "properties": {},
                "metadata": {}
            }
            mock_doc_manager.adapter = mock_adapter
            
            # Call the method
            await protocol._send_initial_state("conn_123", session)
            
            # Verify open_document was called with correct job_id
            mock_doc_manager.open_document.assert_called_once()
            call_args = mock_doc_manager.open_document.call_args
            assert call_args[1]["job_id"] == "newjob"  # Extracted from doc_newjob
            assert call_args[1]["create_if_not_exists"] == True
    
    @pytest.mark.asyncio
    async def test_send_initial_state_handles_errors_gracefully(self):
        """Test that errors are handled and empty state is sent."""
        from app.services.collaboration_protocol import (
            CollaborationProtocol,
            CollaborationSession
        )
        
        # Create protocol instance
        protocol = CollaborationProtocol()
        
        # Create mock WebSocket manager
        mock_websocket_manager = AsyncMock()
        protocol.websocket_manager = mock_websocket_manager
        
        # Create session
        session = CollaborationSession(document_id="doc_error")
        
        # Mock document manager to raise exception
        with patch('app.services.collaboration_protocol.document_manager') as mock_doc_manager:
            mock_doc_manager._doc_handles = {"doc_error": Mock()}
            mock_doc_manager.adapter.take_snapshot.side_effect = Exception("Snapshot failed")
            
            # Call the method - should not raise
            await protocol._send_initial_state("conn_456", session)
            
            # Verify message was still sent
            mock_websocket_manager.send_to_connection.assert_called_once()
            message = mock_websocket_manager.send_to_connection.call_args[0][1]
            
            # Verify basic structure is there even with error
            assert message["type"] == "initial_state"
            assert message["document_id"] == "doc_error"
            assert message["document_state"] == {}
            assert message["objects"] == []
            assert message["operation_history"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])