"""Core utility helpers used across the Rewizor project."""

import re
from datetime import datetime
from typing import Any, Optional


def normalize_amount(value: Any) -> Optional[float]:
	"""Normalize numeric amounts to 2-decimal floats.

	Preserves negative values (needed for correction documents).
	"""
	if value is None:
		return None
	try:
		return round(float(value), 2)
	except (TypeError, ValueError):
		return None


def normalize_date(value: Any) -> Optional[str]:
	"""Normalize a date to YYYY-MM-DD when possible."""
	if not value:
		return None
	if isinstance(value, str):
		text = value.strip()
	else:
		text = str(value).strip()

	if "T" in text:
		text = text.split("T", 1)[0]
	elif " " in text:
		text = text.split(" ", 1)[0]

	candidates = [
		"%Y-%m-%d",
		"%Y/%m/%d",
		"%Y.%m.%d",
		"%d-%m-%Y",
		"%d/%m/%Y",
		"%d.%m.%Y",
		"%m-%d-%Y",
		"%m/%d/%Y",
		"%m.%d.%Y",
	]

	for fmt in candidates:
		try:
			return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
		except ValueError:
			continue

	match = re.search(
		r"(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})|(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})",
		text,
	)
	if match:
		token = match.group(0)
		for fmt in candidates:
			try:
				return datetime.strptime(token, fmt).strftime("%Y-%m-%d")
			except ValueError:
				continue

	return None
