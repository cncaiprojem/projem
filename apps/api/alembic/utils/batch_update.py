"""
Batch update utilities for Alembic migrations.

This module provides reusable functions for performing efficient batch updates
in database migrations, particularly for PostgreSQL.
"""

from typing import List, Dict, Any
import sqlalchemy as sa


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
    """
    if not updates:
        return
    
    # Process updates in batches
    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        if not batch:
            continue
        
        # Get the fields to update (excluding 'id'), sort for consistency
        fields = sorted([k for k in batch[0].keys() if k != 'id'])
        if not fields:
            continue
        
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
        
    Example:
        batch_updates = [
            {'id': 1, 'hash': 'abc123...'},
            {'id': 2, 'hash': 'def456...'},
        ]
        execute_params_hash_batch_update(connection, batch_updates)
    """
    if not batch_updates:
        return
    
    # Build VALUES clause with proper parameterization to prevent SQL injection
    values_list = []
    params = {}
    for i, update in enumerate(batch_updates):
        hash_param = f"hash_{i}"
        id_param = f"id_{i}"
        values_list.append(f"(:{hash_param}, :{id_param})")
        params[hash_param] = update.get('hash')
        params[id_param] = update.get('id')
    
    values_clause = ", ".join(values_list)
    
    # Execute batch update using parameterized query for security
    sql = sa.text(f"""
        UPDATE jobs 
        SET params_hash = batch_data.hash
        FROM (VALUES {values_clause}) AS batch_data(hash, id)
        WHERE jobs.id = batch_data.id
    """)
    
    connection.execute(sql, params)