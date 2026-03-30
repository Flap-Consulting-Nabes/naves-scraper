import random
import time


def random_delay(min_s: float = 2.5, max_s: float = 6.5) -> None:
    """Espera un tiempo aleatorio entre min_s y max_s segundos para simular comportamiento humano."""
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)
