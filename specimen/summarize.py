"""Aggregate categorized transactions."""


def total_by_category(transactions):
    categories = {item["category"] for item in transactions}
    return {
        c: sum(t["amount"] for t in transactions if t["category"] == c)
        for c in sorted(categories)
    }


def grand_total(totals):
    return sum(totals.values())


def build_summary(transactions):
    totals = total_by_category(transactions)
    overall = grand_total(totals)
    return {"totals": totals, "overall": overall, "count": len(transactions)}
