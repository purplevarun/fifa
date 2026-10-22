"""Conservative spacing repair for OCR prose; never used for record identities."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

VOCAB_PATH = Path(__file__).resolve().parents[1] / "vocab.json"
TOKEN = re.compile(r"\w+(?:['’-]\w+)*")
WORD = re.compile(r"[a-z]+(?:['’-][a-z]+)*", re.IGNORECASE | re.ASCII)
MAX_TOKEN_LENGTH = 160


class Vocabulary:
    def __init__(self, words):
        if not isinstance(words, (list, tuple)) or any(
            not isinstance(word, str) or not WORD.fullmatch(word) for word in words
        ):
            raise ValueError("vocab.json words must be an array of English words")
        self.words = frozenset(word.lower() for word in words)
        self.max_word_length = max(map(len, self.words), default=0)

    def _segments(self, token):
        """Return boundaries only when the ENTIRE token has one possible split."""
        if not re.fullmatch(r"[A-Za-z]+", token) or len(token) > MAX_TOKEN_LENGTH:
            return None
        lowered = token.lower()
        if lowered in self.words:
            return [len(token)]
        ways = [0] * (len(token) + 1)
        previous = [0] * (len(token) + 1)
        ways[0] = 1
        for end in range(1, len(token) + 1):
            for start in range(max(0, end - self.max_word_length), end):
                if ways[start] and lowered[start:end] in self.words:
                    ways[end] = min(2, ways[end] + ways[start])
                    previous[end] = start
                    if ways[end] == 2:
                        break
        if ways[-1] != 1:
            return None
        boundaries = []
        end = len(token)
        while end:
            boundaries.append(end)
            end = previous[end]
        return list(reversed(boundaries))

    def _split_token(self, token):
        if token.lower() in self.words:
            return token
        # A missing space after a known possessive, e.g. Kubo'simpressive.
        possessive = re.fullmatch(r"([A-Za-z]+)(['’]s)([A-Za-z]{2,})", token)
        if possessive and possessive[1].lower() in self.words:
            prefix = possessive[1] + possessive[2]
            remainder = possessive[3]
            if self._segments(remainder):
                return prefix + " " + self._split_token(remainder)
        boundaries = self._segments(token)
        if not boundaries:
            return token
        parts = []
        start = 0
        for end in boundaries:
            parts.append(token[start:end])
            start = end
        return " ".join(parts)

    def split_text(self, text):
        def repair(match):
            # Python's \w excludes combining marks. Never repair a substring of
            # a Unicode word just because its adjoining mark isn't in \w.
            neighbours = (
                text[max(0, match.start() - 1) : match.start()]
                + text[match.end() : match.end() + 1]
            )
            if any(unicodedata.category(char).startswith("M") for char in neighbours):
                return match[0]
            return self._split_token(match[0])

        return TOKEN.sub(repair, text)


@lru_cache(maxsize=1)
def default_vocabulary():
    with VOCAB_PATH.open(encoding="utf-8") as source:
        payload = json.load(source)
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported vocab.json schema_version")
    return Vocabulary(payload.get("words"))


def split_joined_words(text):
    return default_vocabulary().split_text(text)
