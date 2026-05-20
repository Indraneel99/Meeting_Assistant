class TranscriptNormalizer:
    def __init__(self, chunk_size_words: int) -> None:
        self.chunk_size_words = chunk_size_words

    def normalize(self, transcript_text: str) -> str:
        replacements = {
            " um ": " ",
            " uh ": " ",
            " you know ": " ",
            " like ": " ",
        }
        cleaned = f" {transcript_text.strip()} "
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        return " ".join(cleaned.split())

    def chunk(self, transcript_text: str) -> list[str]:
        words = transcript_text.split()
        return [
            " ".join(words[index : index + self.chunk_size_words])
            for index in range(0, len(words), self.chunk_size_words)
        ] or [""]
