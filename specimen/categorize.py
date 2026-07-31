"""Assign a category to each transaction."""
from . import util

CATEGORIES = {"coffee": "food", "grocer": "food", "rent": "housing", "gym": "health"}


def assign_category(merchant):
    normalized = util.normalize_merchant(merchant)
    words = set(normalized.split())
    matches = words & set(CATEGORIES)
    if matches:
        return CATEGORIES[sorted(matches)[0]]
    return "other"


def categorize_all(transactions):
    categorized = []
    for item in transactions:
        category = assign_category(item["merchant"])
        item = dict(item)
        item["category"] = category
        categorized.append(item)
    return categorized
