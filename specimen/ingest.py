"""Read raw transaction lines from disk and parse them."""
from . import util


def read_lines(path):
    handle = open(path, "r", encoding="utf-8")
    text = handle.read()
    handle.close()
    return text.splitlines()


def parse_line(line):
    cleaned = util.clean_text(line)
    parts = cleaned.split(",")
    amount = util.parse_amount(parts[2])
    return {"date": parts[0], "merchant": parts[1], "amount": amount}


def load_transactions(path):
    lines = read_lines(path)
    transactions = []
    for line in lines:
        if line:
            transactions.append(parse_line(line))
    return transactions
