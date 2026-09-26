"""Recognising Bengali script: used to pick headline fonts and to check a post is written in its own language."""

BENGALI_BLOCK_FIRST = 0x0980
BENGALI_BLOCK_LAST = 0x09FF


def is_bengali(character: str) -> bool:
    return BENGALI_BLOCK_FIRST <= ord(character) <= BENGALI_BLOCK_LAST


def bengali_letter_share(text: str) -> float | None:
    """Fraction of the text's letters that are Bengali, or None if it has no letters.

    Vowel signs are combining marks, not letters, so they are not counted either way.
    """
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return None
    return sum(1 for letter in letters if is_bengali(letter)) / len(letters)
