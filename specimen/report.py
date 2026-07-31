"""Render the category summary as text."""


def format_header(title):
    line = "=" * len(title)
    return title + "\n" + line


def format_rows(totals):
    rows = []
    for category in sorted(totals):
        rows.append("%-12s %10.2f" % (category, totals[category]))
    return "\n".join(rows)


def format_footer(overall, count):
    return "%d transactions, %.2f total" % (count, overall)


def render_report(summary):
    header = format_header("Spending by category")
    body = format_rows(summary["totals"])
    footer = format_footer(summary["overall"], summary["count"])
    return header + "\n" + body + "\n" + footer
