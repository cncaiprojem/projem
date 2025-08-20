#!/usr/bin/env python3
import os
import re
from pathlib import Path

def analyze_migrations():
    versions_dir = Path('apps/api/alembic/versions')
    files = [f for f in versions_dir.glob('*.py') if f.name != '__init__.py']
    migrations = []
    
    for f in sorted(files):
        with open(f, 'r') as file:
            content = file.read()
            revision = re.search(r'^revision = ["\']([^"\']+)["\']', content, re.MULTILINE)
            down_revision = re.search(r'^down_revision = ([^\n]+)', content, re.MULTILINE)
            if revision:
                rev = revision.group(1)
                down = down_revision.group(1).strip().strip('"').strip("'") if down_revision else None
                if down == 'None':
                    down = None
                migrations.append((f.name, rev, down))
    
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