"""Small pure helpers."""
import hashlib


def clean_text(text):
    return text.strip().replace("\ufeff", "")


def parse_amount(raw):
    return float(raw.strip())


def normalize_merchant(name):
    return " ".join(name.lower().split())


def compute_checksum(records):
    digest = hashlib.sha256()
    for record in records:
        digest.update(repr(sorted(record.items())).encode("utf-8"))
    return digest.hexdigest()
