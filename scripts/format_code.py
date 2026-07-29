#!/usr/bin/env python3
"""
Simple code formatter to fix common Black formatting issues.
This fixes:
1. Missing newlines at end of files
2. f-string concatenation inconsistencies
3. Extra blank lines
"""

import os
import re
from pathlib import Path


def fix_file(filepath: Path) -> bool:
    """Fix formatting issues in a single file. Returns True if changes were made."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original = content
    
    # Fix 1: Ensure file ends with exactly one newline
    content = content.rstrip('\n') + '\n'
    
    # Fix 2: Fix f-string concatenation (e.g., f"..." f"..." -> f"...")
    # This pattern matches: f"..." f"..." or f'...' f'...'
    content = re.sub(
        r'f"([^"]*)"\s+f"([^"]*)"',
        r'f"\1\2"',
        content
    )
    content = re.sub(
        r"f'([^']*)'\s+f'([^']*)'",
        r"f'\1\2'",
        content
    )
    
    # Fix 3: Remove multiple consecutive blank lines (more than 2)
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    return False


def main():
    """Format all Python files in src/ and tests/."""
    base_dir = Path('.')
    
    files_to_format = []
    for subdir in ['src', 'tests']:
        path = base_dir / subdir
        if path.exists():
            files_to_format.extend(path.rglob('*.py'))
    
    print(f"Formatting {len(files_to_format)} Python files...")
    
    changed = 0
    for filepath in files_to_format:
        if fix_file(filepath):
            changed += 1
            print(f"  ✓ {filepath}")
    
    print(f"\n✓ Formatted {changed} files")
    return 0


if __name__ == '__main__':
    exit(main())