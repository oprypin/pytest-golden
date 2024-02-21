import re

def find_words(text: str) -> list:
    return re.findall(r"\w+", text)


def add1(x: int) -> int:
    return x + 1
