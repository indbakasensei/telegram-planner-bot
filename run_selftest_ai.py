#!/usr/bin/env python
"""Run AI category selftests."""
from core.selftest.runner import run

report = run(categories={'AI'})
print(f'Passed: {report.passed}, Failed: {report.failed}, Warnings: {report.warnings}, Skipped: {report.skipped}')
for r in report.results:
    if r.status.name != 'PASS':
        print(f'  {r.name}: {r.status.name} - {r.error}')