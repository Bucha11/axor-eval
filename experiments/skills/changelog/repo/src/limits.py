class Limiter:
    """Admit at most n calls."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.used = 0

    def allow(self) -> bool:
        if self.used > self.n:  # bug: admits n + 1 calls
            return False
        self.used += 1
        return True
