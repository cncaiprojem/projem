"""
Ultra Enterprise RBAC Service for Task 3.4

Business logic layer for Role-Based Access Control with:
- Permission validation and role management
- Security event tracking and audit logging
- Performance optimized database queries
- Turkish KVKV compliance considerations
- Integration with existing authentication system
"""

from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import and_, or_, func, desc

from ..models.user import User
from ..models.security_event import SecurityEvent
from ..models.audit_log import AuditLog
from ..models.enums import UserRole, AuditAction
from ..schemas.rbac_schemas import (
    PermissionCheckResponse,
    UserPermissionSummary,
    SecurityEventResponse,
    RoleUpdateResponse,
    SystemPermissionsResponse,
    RolePermissions as RolePermissionsSchema,
    PermissionScope,
)
from ..middleware.rbac_middleware import RolePermissions
from ..core.logging import get_logger

logger = get_logger(__name__)


class RBACBusinessService:
    """Core business logic for RBAC operations."""

    def __init__(self):
        self.permissions = RolePermissions()

    def check_user_permission(
        self,
        db: DBSession,
        user_id: int,
        resource: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PermissionCheckResponse:
        """
        Check if user has permission for specific resource/action.

        Args:
            db: Database session
            user_id: User ID to check
            resource: Resource to check access for
            action: Action to check permission for
            context: Additional context for permission check

        Returns:
            PermissionCheckResponse with permission decision
        """
        start_time = datetime.now(timezone.utc)

        # Get user from database
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return PermissionCheckResponse(
                user_id=user_id,
                resource=resource,
                action=action,
                allowed=False,
                reason="Kullanıcı bulunamadı",
                user_role=UserRole.VIEWER,  # Default role for missing user
                required_scope=f"{resource}:{action}",
                check_timestamp=datetime.now(timezone.utc),
            )

        # Check if user account is active
        if not user.is_active or user.is_account_locked():
            return PermissionCheckResponse(
                user_id=user_id,
                resource=resource,
                action=action,
                allowed=False,
                reason="Kullanıcı hesabı aktif değil veya kilitli",
                user_role=user.role,
                required_scope=f"{resource}:{action}",
                check_timestamp=datetime.now(timezone.utc),
            )

        # Construct required scope
        required_scope = f"{resource}:{action}"

        # Check if user role has required scope
        has_permission = self.permissions.role_has_scope(user.role, required_scope)

        # Admin always has permission
        if user.role == UserRole.ADMIN:
            has_permission = True

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        # Log permission check
        logger.info(
            "Permission check completed",
            extra={
                "operation": "check_user_permission",
                "user_id": user_id,
                "user_role": user.role.value,
                "resource": resource,
                "action": action,
                "required_scope": required_scope,
                "allowed": has_permission,
                "elapsed_ms": elapsed_ms,
            },
        )

        return PermissionCheckResponse(
            user_id=user_id,
            resource=resource,
            action=action,
            allowed=has_permission,
            reason="İzin verildi" if has_permission else f"Gerekli kapsam: {required_scope}",
            user_role=user.role,
            required_scope=required_scope,
            check_timestamp=datetime.now(timezone.utc),
        )

    def get_user_permissions(self, db: DBSession, user_id: int) -> Optional[UserPermissionSummary]:
        """
        Get comprehensive permission summary for user.

        Args:
            db: Database session
            user_id: User ID to get permissions for

        Returns:
            UserPermissionSummary or None if user not found
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        # Get scopes for user role
        user_scopes = list(self.permissions.get_scopes_for_role(user.role))

        return UserPermissionSummary(
            user_id=user.id,
            role=user.role,
            scopes=user_scopes,
            is_admin=self.permissions.is_admin_role(user.role),
            is_active=user.is_active and not user.is_account_locked(),
            last_permission_check=datetime.now(timezone.utc),
        )

    def update_user_role(
        self, db: DBSession, user_id: int, new_role: UserRole, updated_by_user_id: int, reason: str
    ) -> Optional[RoleUpdateResponse]:
        """
        Update user role with audit logging.

        Args:
            db: Database session
            user_id: User ID to update
            new_role: New role to assign
            updated_by_user_id: Admin user making the change
            reason: Reason for role change

        Returns:
            RoleUpdateResponse or None if user not found
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        old_role = user.role

        # Update user role
        user.role = new_role
        user.updated_at = datetime.now(timezone.utc)

        # Create audit log entry
        audit_log = AuditLog(
            action=AuditAction.USER_UPDATE,
            resource_type="User",
            resource_id=str(user_id),
            actor_user_id=updated_by_user_id,
            changes={"role": {"old": old_role.value, "new": new_role.value}},
            reason=reason,
            created_at=datetime.now(timezone.utc),
        )

        db.add(audit_log)
        db.commit()

        logger.info(
            "User role updated",
            extra={
                "operation": "update_user_role",
                "user_id": user_id,
                "old_role": old_role.value,
                "new_role": new_role.value,
                "updated_by": updated_by_user_id,
                "reason": reason,
            },
        )

        return RoleUpdateResponse(
            user_id=user_id,
            old_role=old_role,
            new_role=new_role,
            updated_by=updated_by_user_id,
            updated_at=datetime.now(timezone.utc),
            reason=reason,
        )

    def create_security_event(
        self,
        db: DBSession,
        event_type: str,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> SecurityEventResponse:
        """
        Create security event for audit trail.

        Args:
            db: Database session
            event_type: Type of security event
            user_id: Associated user ID
            ip_address: Source IP address
            user_agent: User agent string

        Returns:
            SecurityEventResponse
        """
        security_event = SecurityEvent(
            user_id=user_id,
            type=event_type,
            ip=ip_address,
            ua=user_agent[:1000] if user_agent else None,
            created_at=datetime.now(timezone.utc),
        )

        db.add(security_event)
        db.commit()
        db.refresh(security_event)

        logger.info(
            "Security event created",
            extra={
                "operation": "create_security_event",
                "event_id": security_event.id,
                "event_type": event_type,
                "user_id": user_id,
                "ip_address": ip_address,
            },
        )

        return SecurityEventResponse(
            id=security_event.id,
            event_type=security_event.type,
            user_id=security_event.user_id,
            ip_address=security_event.ip,
            created_at=security_event.created_at,
        )

    def get_security_events(
        self,
        db: DBSession,
        user_id: Optional[int] = None,
        event_types: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SecurityEventResponse]:
        """
        Get security events with filtering.

        Args:
            db: Database session
            user_id: Filter by user ID
            event_types: Filter by event types
            start_date: Filter events after this date
            end_date: Filter events before this date
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List of SecurityEventResponse
        """
        query = db.query(SecurityEvent)

        # Apply filters
        if user_id:
            query = query.filter(SecurityEvent.user_id == user_id)

        if event_types:
            query = query.filter(SecurityEvent.type.in_(event_types))

        if start_date:
            query = query.filter(SecurityEvent.created_at >= start_date)

        if end_date:
            query = query.filter(SecurityEvent.created_at <= end_date)

        # Order by most recent first
        query = query.order_by(desc(SecurityEvent.created_at))

        # Apply pagination
        events = query.offset(offset).limit(limit).all()

        return [
            SecurityEventResponse(
                id=event.id,
                event_type=event.type,
                user_id=event.user_id,
                ip_address=event.ip,
                created_at=event.created_at,
            )
            for event in events
        ]

    def get_role_statistics(self, db: DBSession) -> Dict[str, int]:
        """
        Get user count statistics by role.

        Args:
            db: Database session

        Returns:
            Dictionary mapping role names to user counts
        """
        result = (
            db.query(User.role, func.count(User.id))
            .filter(User.is_active == True)
            .group_by(User.role)
            .all()
        )

        stats = {}
        for role, count in result:
            stats[role.value] = count

        # Include zero counts for all roles
        for role in UserRole:
            if role.value not in stats:
                stats[role.value] = 0

        return stats

    def get_system_permissions(self, db: DBSession) -> SystemPermissionsResponse:
        """
        Get comprehensive system permission information.

        Args:
            db: Database session

        Returns:
            SystemPermissionsResponse with all permission data
        """
        # Build available roles
        available_roles = []
        for role in UserRole:
            scopes = self.permissions.get_scopes_for_role(role)
            hierarchy_level = self.permissions.ROLE_HIERARCHY.get(role, 0)

            available_roles.append(
                RolePermissionsSchema(role=role, scopes=scopes, hierarchy_level=hierarchy_level)
            )

        # Build available scopes
        all_scopes = set()
        for role_scopes in self.permissions.ROLE_SCOPES.values():
            all_scopes.update(role_scopes)

        available_scopes = []
        for scope in sorted(all_scopes):
            if ":" in scope:
                resource, action = scope.split(":", 1)
                available_scopes.append(
                    PermissionScope(
                        scope=scope,
                        description=f"{action.title()} access to {resource}",
                        resource=resource,
                        action=action,
                    )
                )

        # Get role hierarchy
        role_hierarchy = {
            role.value: level for role, level in self.permissions.ROLE_HIERARCHY.items()
        }

        # Get user statistics by role
        user_stats = self.get_role_statistics(db)

        return SystemPermissionsResponse(
            available_roles=available_roles,
            available_scopes=available_scopes,
            role_hierarchy=role_hierarchy,
            total_users_by_role=user_stats,
            last_updated=datetime.now(timezone.utc),
        )

    def get_recent_security_events_summary(self, db: DBSession, hours: int = 24) -> Dict[str, Any]:
        """
        Get summary of recent security events for monitoring.

        Args:
            db: Database session
            hours: Number of hours to look back

        Returns:
            Dictionary with security event summary
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Get event counts by type
        event_counts = (
            db.query(SecurityEvent.type, func.count(SecurityEvent.id))
            .filter(SecurityEvent.created_at >= cutoff_time)
            .group_by(SecurityEvent.type)
            .all()
        )

        # Get unique users with security events
        unique_users = (
            db.query(func.count(func.distinct(SecurityEvent.user_id)))
            .filter(
                and_(SecurityEvent.created_at >= cutoff_time, SecurityEvent.user_id.isnot(None))
            )
            .scalar()
        )

        # Get unique IPs with security events
        unique_ips = (
            db.query(func.count(func.distinct(SecurityEvent.ip)))
            .filter(and_(SecurityEvent.created_at >= cutoff_time, SecurityEvent.ip.isnot(None)))
            .scalar()
        )

        # Get top event types
        top_events = dict(event_counts)

        return {
            "time_window_hours": hours,
            "total_events": sum(top_events.values()),
            "unique_users_affected": unique_users or 0,
            "unique_source_ips": unique_ips or 0,
            "events_by_type": top_events,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# Global service instance
rbac_business_service = RBACBusinessService()
