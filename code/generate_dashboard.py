#!/usr/bin/env python3
"""Regenerate dashboard.html from the current database state."""

import subprocess, re, json, sys

# Run the data generation script
result = subprocess.run(
    [sys.executable, '-c', open('dashboard_data_gen.py').read()],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("Data generation failed:", result.stderr)
    sys.exit(1)

# Re-inject data into HTML template
with open('dashboard_data.json') as f:
    data = f.read().strip()

with open('dashboard.html') as f:
    html = f.read()

html = re.sub(r'const DATA = \{.*?\};', f'const DATA = {data};', html, flags=re.DOTALL)

with open('dashboard.html', 'w') as f:
    f.write(html)

print(f"Dashboard regenerated — {len(html):,} bytes")
