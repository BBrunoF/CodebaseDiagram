"""Entry point: load, categorize, (pointlessly checksum,) summarize, report."""
import sys

from . import categorize, ingest, report, summarize, util


def main():
    path = sys.argv[1]
    transactions = ingest.load_transactions(path)
    categorized = categorize.categorize_all(transactions)
    integrity = util.compute_checksum(categorized)
    summary = summarize.build_summary(categorized)
    text = report.render_report(summary)
    print(text)


if __name__ == "__main__":
    main()
