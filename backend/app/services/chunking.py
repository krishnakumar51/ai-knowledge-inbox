import re


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """Recursively split text, preferring paragraphs, then sentences, then words."""
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text)]
    paragraphs = [part for part in paragraphs if part]
    if not paragraphs:
        return []
    atoms: list[tuple[str, int, str]] = []
    previous_paragraph = -1
    for paragraph_index, paragraph in enumerate(paragraphs):
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            if len(sentence) <= chunk_size:
                separator = (
                    "\n\n"
                    if previous_paragraph != paragraph_index and previous_paragraph >= 0
                    else " "
                    if atoms
                    else ""
                )
                atoms.append((sentence, paragraph_index, separator))
                previous_paragraph = paragraph_index
                continue
            for word_index, word in enumerate(re.findall(r"\S+", sentence)):
                segments = [word[start : start + chunk_size] for start in range(0, len(word), chunk_size)]
                for segment_index, segment in enumerate(segments):
                    if segment_index:
                        separator = ""
                    elif word_index:
                        separator = " "
                    elif previous_paragraph != paragraph_index and previous_paragraph >= 0:
                        separator = "\n\n"
                    else:
                        separator = " " if atoms else ""
                    atoms.append((segment, paragraph_index, separator))
            previous_paragraph = paragraph_index

    output: list[str] = []
    current = ""
    for atom, _, separator in atoms:
        if len(current) + len(separator) + len(atom) <= chunk_size:
            current += separator + atom
            continue
        if current:
            output.append(current)
            available_overlap = min(overlap, chunk_size - len(atom) - len(separator)) if separator else 0
            suffix = current[-available_overlap:] if available_overlap > 0 else ""
            current = f"{suffix}{separator}{atom}" if suffix else f"{separator}{atom}"
        else:
            current = f"{separator}{atom}"
    if current:
        output.append(current)
    return output
