"""
Batch update utilities for Alembic migrations.

This module provides reusable functions for performing efficient batch updates
in database migrations, particularly for PostgreSQL.
"""

from typing import List, Dict, Any
import re
import sqlalchemy as sa


def _validate_sql_identifier(identifier: str) -> None:
    """
    Validate that SQL identifier (table/column name) is safe.
    
    Prevents SQL injection by ensuring identifiers only contain
    allowed characters and are not SQL keywords.
    
    Args:
        identifier: SQL identifier to validate
        
    Raises:
        ValueError: If identifier is invalid
    """
    # Check for valid SQL identifier pattern
    # Allow: letters, numbers, underscores, but must start with letter or underscore
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        raise ValueError(
            f"Geçersiz SQL tanımlayıcı: '{identifier}'. "
            f"Sadece harf, rakam ve alt çizgi kullanılabilir."
        )
    
    # Block common SQL keywords that should never be table/column names
    sql_keywords = {
        'select', 'insert', 'update', 'delete', 'drop', 'create',
        'alter', 'truncate', 'exec', 'execute', 'union', 'from',
        'where', 'having', 'group', 'order', 'by', 'join',
        'inner', 'outer', 'left', 'right', 'cross', 'full'
    }
    
    if identifier.lower() in sql_keywords:
        raise ValueError(
            f"SQL anahtar kelime tablo/sütun adı olarak kullanılamaz: '{identifier}'"
        )


def execute_batch_update(
    connection,
    table_name: str,
    updates: List[Dict[str, Any]],
    batch_size: int = 1000
) -> None:
    """
    Execute batch updates efficiently using PostgreSQL's UPDATE ... FROM (VALUES ...) syntax.
    
    This significantly improves performance compared to individual UPDATE statements,
    especially for large tables.
    
    Args:
        connection: SQLAlchemy database connection
        table_name: Name of the table to update
        updates: List of dictionaries with 'id' and fields to update
        batch_size: Number of rows to update in each batch (default: 1000)
        
    Example:
        updates = [
            {'id': 1, 'params_hash': 'abc123...'},
            {'id': 2, 'params_hash': 'def456...'},
        ]
        execute_batch_update(connection, 'jobs', updates)
        
    Raises:
        ValueError: If table_name or field names are invalid
        KeyError: If required 'id' field is missing
    """
    if not updates:
        return
    
    # Validate table name to prevent SQL injection
    _validate_sql_identifier(table_name)
    
    # Validate that all updates have the 'id' field
    for idx, update in enumerate(updates):
        if 'id' not in update:
            raise KeyError(
                f"Güncelleme #{idx} 'id' alanını içermiyor. "
                f"Her güncelleme bir 'id' alanına sahip olmalıdır."
            )
    
    # Process updates in batches
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        if not batch:
            continue
        
        # Get the fields to update (excluding 'id'), sort for consistency
        fields = sorted([k for k in batch[0].keys() if k != 'id'])
        if not fields:
            continue
        
        # Validate all field names to prevent SQL injection
        for field in fields:
            _validate_sql_identifier(field)
        
        # Build SET clause
        set_clause = ', '.join([f"{field} = batch_data.{field}" for field in fields])
        columns_clause = ', '.join(['id'] + fields)
        
        # Build VALUES clause with proper parameterization
        values_list = []
        params = {}
        for j, update in enumerate(batch):
            param_prefix = f"r{i + j}"  # Unique prefix for each row
            
            # Create parameter names
            id_param = f"id_{param_prefix}"
            row_placeholders = [f":{id_param}"]
            params[id_param] = update['id']
            
            # Add parameters for each field
            for field in fields:
                field_param = f"{field}_{param_prefix}"
                row_placeholders.append(f":{field_param}")
                params[field_param] = update.get(field)
            
            values_list.append(f"({', '.join(row_placeholders)})")
        
        values_clause = ', '.join(values_list)
        
        # Execute batch update using parameterized query
        sql = sa.text(f"""
            UPDATE {table_name}
            SET {set_clause}
            FROM (VALUES {values_clause}) AS batch_data({columns_clause})
            WHERE {table_name}.id = batch_data.id
        """)
        
        connection.execute(sql, params)


def execute_params_hash_batch_update(connection, batch_updates: List[Dict[str, Any]]) -> None:
    """
    Specialized batch update for params_hash column in jobs table.
    
    This is a convenience function specifically for updating params_hash values,
    which is a common operation in migrations.
    
    Args:
        connection: SQLAlchemy database connection
        batch_updates: List of dictionaries with 'id' and 'hash' keys
        
    Raises:
        ValueError: If batch_updates contains invalid data
        KeyError: If required 'id' or 'hash' fields are missing
        
    Example:
        batch_updates = [
            {'id': 1, 'hash': 'abc123...'},
            {'id': 2, 'hash': 'def456...'},
        ]
        execute_params_hash_batch_update(connection, batch_updates)
    """
    if not batch_updates:
        return
    
    # Validate input structure
    for idx, update in enumerate(batch_updates):
        if not isinstance(update, dict):
            raise ValueError(
                f"Güncelleme #{idx} bir sözlük değil. "
                f"Her güncelleme bir sözlük olmalıdır."
            )
        
        if 'hash' not in update:
            raise KeyError(
                f"Güncelleme #{idx} 'hash' alanını içermiyor. "
                f"params_hash güncellemesi için 'hash' alanı gereklidir."
            )
        
        if 'id' not in update:
            raise KeyError(
                f"Güncelleme #{idx} 'id' alanını içermiyor. "
                f"Her güncelleme bir 'id' alanına sahip olmalıdır."
            )
    
    # Build VALUES clause with proper parameterization to prevent SQL injection
    values_list = []
    params = {}
    for i, update in enumerate(batch_updates):
        hash_param = f"hash_{i}"
        id_param = f"id_{i}"
        values_list.append(f"(:{hash_param}, :{id_param})")
        params[hash_param] = update['hash']  # Use dict access since we validated
        params[id_param] = update['id']  # Use dict access since we validated
    
    values_clause = ", ".join(values_list)
    
    # Execute batch update using parameterized query for security
    sql = sa.text(f"""
        UPDATE jobs 
        SET params_hash = batch_data.hash
        FROM (VALUES {values_clause}) AS batch_data(hash, id)
        WHERE jobs.id = batch_data.id
    """)
    
    connection.execute(sql, params)