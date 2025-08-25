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
        
        # Get the fields to update (excluding 'id')
        if batch:
            fields = [k for k in batch[0].keys() if k != 'id']
            
            # Build VALUES clause
            values_parts = []
            for update in batch:
                value_items = [f"'{update.get(field, '')}'" if isinstance(update.get(field), str) 
                              else str(update.get(field, 'NULL')) 
                              for field in fields]
                values_parts.append(f"({update['id']}, {', '.join(value_items)})")
            
            values_clause = ', '.join(values_parts)
            
            # Build SET clause
            set_parts = [f"{field} = batch_data.{field}" for field in fields]
            set_clause = ', '.join(set_parts)
            
            # Build column names for VALUES alias
            columns = ['id'] + fields
            columns_clause = ', '.join(columns)
            
            # Execute batch update
            sql = sa.text(f"""
                UPDATE {table_name}
                SET {set_clause}
                FROM (VALUES {values_clause}) AS batch_data({columns_clause})
                WHERE {table_name}.id = batch_data.id
            """)
            
            connection.execute(sql)


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
    
    # Build VALUES clause for batch update
    values_parts = []
    for update in batch_updates:
        # Escape single quotes in hash values
        hash_value = update['hash'].replace("'", "''") if update['hash'] else ''
        values_parts.append(f"('{hash_value}', {update['id']})")
    
    values_clause = ', '.join(values_parts)
    
    # Execute batch update using PostgreSQL's efficient syntax
    sql = sa.text(f"""
        UPDATE jobs 
        SET params_hash = batch_data.hash
        FROM (VALUES {values_clause}) AS batch_data(hash, id)
        WHERE jobs.id = batch_data.id
    """)
    
    connection.execute(sql)