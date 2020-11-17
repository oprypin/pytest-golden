import re

def find_words(text: str) -> list:
    return re.findall(r"\w+", text)
