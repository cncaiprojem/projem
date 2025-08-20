import os
import re
from pathlib import Path

migrations_dir = Path("apps/api/alembic/versions")
migration_files = list(migrations_dir.glob("*.py"))

# Extract revision info from each file
migrations = []
for file_path in migration_files:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Find revision and down_revision
    revision_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", content, re.MULTILINE)
    down_revision_match = re.search(r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]", content, re.MULTILINE)
    
    # Handle None case
    if not down_revision_match:
        down_revision_match = re.search(r"^down_revision\s*=\s*None", content, re.MULTILINE)
        down_revision = None if down_revision_match else "UNKNOWN"
    else:
        down_revision = down_revision_match.group(1)
    
    if revision_match:
        revision = revision_match.group(1)
        migrations.append({
            'file': file_path.name,
            'revision': revision,
            'down_revision': down_revision
        })

# Sort by filename (which includes timestamps)
migrations.sort(key=lambda x: x['file'])

print("=== MIGRATION CHAIN ANALYSIS ===\n")
print(f"{'File':<60} {'Revision':<50} {'Down Revision':<50}")
print("-" * 160)

for m in migrations:
    print(f"{m['file']:<60} {m['revision']:<50} {str(m['down_revision']):<50}")

print("\n=== ISSUES FOUND ===\n")

# Check for mismatches
revision_ids = {m['revision'] for m in migrations}

for m in migrations:
    if m['down_revision'] and m['down_revision'] != 'None':
        if m['down_revision'] not in revision_ids:
            print(f"ERROR: {m['file']} references non-existent revision: {m['down_revision']}")

# Check for duplicate revisions
seen = set()
for m in migrations:
    if m['revision'] in seen:
        print(f"ERROR: Duplicate revision ID: {m['revision']}")
    seen.add(m['revision'])