#!/usr/bin/env python3
"""Structural guard for alphax_audit_ledger. Run before every push: python3 verify_tree.py"""
import json
import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).parent
APP = ROOT / "alphax_audit_ledger"
REPORT = APP / "alphax_audit_ledger" / "report" / "audit_general_ledger"

REQUIRED = [
	ROOT / "pyproject.toml",
	APP / "__init__.py",
	APP / "hooks.py",
	APP / "modules.txt",
	APP / "patches.txt",
	APP / "api.py",
	APP / "utils.py",
	APP / "translations" / "ar.csv",
	APP / "alphax_audit_ledger" / "__init__.py",
	APP / "alphax_audit_ledger" / "report" / "__init__.py",
	REPORT / "__init__.py",
	REPORT / "audit_general_ledger.json",
	REPORT / "audit_general_ledger.py",
	REPORT / "audit_general_ledger.js",
]

errors = [f"missing: {p.relative_to(ROOT)}" for p in REQUIRED if not p.exists()]

for py in ROOT.rglob("*.py"):
	try:
		py_compile.compile(str(py), doraise=True)
	except py_compile.PyCompileError as e:
		errors.append(f"syntax: {py.relative_to(ROOT)}: {e.msg}")

try:
	rep = json.loads((REPORT / "audit_general_ledger.json").read_text())
	if rep.get("name") != "Audit General Ledger" or rep.get("module") != "AlphaX Audit Ledger":
		errors.append("report json: name/module mismatch")
	if rep.get("report_type") != "Script Report":
		errors.append("report json: must be Script Report")
except Exception as e:
	errors.append(f"report json: {e}")

if (APP / "modules.txt").read_text().strip() != "AlphaX Audit Ledger":
	errors.append("modules.txt must contain 'AlphaX Audit Ledger'")

for i, line in enumerate((APP / "translations" / "ar.csv").read_text(encoding="utf-8").splitlines(), 1):
	if line and line.count(",") < 1:
		errors.append(f"ar.csv line {i}: malformed")

if errors:
	print("verify_tree FAILED"); [print(" -", e) for e in errors]; sys.exit(1)
print("verify_tree OK")
