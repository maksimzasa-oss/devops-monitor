import os
import time

LEAK_MB_PER_SEC = int(os.getenv("LEAK_MB_PER_SEC", "50"))
LEAK_MAX_MB = int(os.getenv("LEAK_MAX_MB", "15000"))

leak = []
total = 0
while True:
    if total < LEAK_MAX_MB:
        leak.append(bytearray(LEAK_MB_PER_SEC * 1024 * 1024))
        total += LEAK_MB_PER_SEC

