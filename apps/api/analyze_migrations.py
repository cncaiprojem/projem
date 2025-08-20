#!/usr/bin/env python3
"""Analyze migration chain for integrity and provide detailed report."""

import os
import re
import sys
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure UTF-8 encoding
import codecs
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def analyze_migrations() -> Tuple[List[Tuple[str, str, Optional[str]]], List[Tuple[str, str, str]]]:
    versions_dir = Path('apps/api/alembic/versions')
    files = [f for f in versions_dir.glob('*.py') if f.name != '__init__.py']
    migrations = []
    
    for f in sorted(files):
        try:
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
                
            # More robust regex patterns for revision extraction
            revision = re.search(r'^revision[:\s]*(?:str\s*)?=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            down_revision = re.search(r'^down_revision[:\s]*(?:Union\[str,\s*None\]\s*)?=\s*([^\n]+)', content, re.MULTILINE)
            
            if revision:
                rev = revision.group(1)
                down_raw = down_revision.group(1).strip() if down_revision else 'None'
                # Handle various formats
                down = down_raw.strip('"').strip("'")
                if down in ('None', 'null', 'NULL'):
                    down = None
                migrations.append((f.name, rev, down))
            else:
                logger.warning(f"Could not extract revision from {f.name}")
        except Exception as e:
            logger.error(f"Error processing {f.name}: {e}")
            continue
    
    # Print migration chain
    print('Migration Chain Analysis:')
    print('=' * 100)
    print(f'{"File":<50} | {"Revision":<30} | {"Down Revision":<30}')
    print('=' * 100)
    
    # Create revision map
    rev_map = {m[1]: m for m in migrations}
    
    for fname, rev, down in migrations:
        status = ""
        if down and down not in rev_map:
            status = " ❌ BROKEN LINK!"
        print(f'{fname[:48]:<50} | {rev[:28]:<30} | {str(down)[:28]:<30}{status}')
    
    print('\n' + '=' * 100)
    print('Chain Validation:')
    print('=' * 100)
    
    # Find base migrations (no down_revision)
    base_migrations = [m for m in migrations if m[2] is None]
    print(f'Base migrations (down_revision=None): {len(base_migrations)}')
    for m in base_migrations:
        print(f'  - {m[0]} (revision: {m[1]})')
    
    # Find broken links
    broken_links = []
    for fname, rev, down in migrations:
        if down and down not in rev_map:
            broken_links.append((fname, rev, down))
    
    if broken_links:
        print(f'\n❌ Broken Links Found: {len(broken_links)}')
        for fname, rev, down in broken_links:
            print(f'  - {fname} references non-existent: {down}')
    else:
        print('\n✅ No broken links found')
    
    # Find heads (migrations not referenced by others)
    all_downs = {m[2] for m in migrations if m[2]}
    heads = [m for m in migrations if m[1] not in all_downs]
    print(f'\nHead migrations (not referenced by others): {len(heads)}')
    for m in heads:
        print(f'  - {m[0]} (revision: {m[1]})')
    
    return migrations, broken_links

if __name__ == '__main__':
    migrations, broken_links = analyze_migrations()