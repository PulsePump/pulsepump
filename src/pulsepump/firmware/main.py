from machine import ADC
import time
import sys

a0 = ADC(26)
a1 = ADC(27)

SAMPLE_HZ = 500
PERIOD_US = 1_000_000 // SAMPLE_HZ

t0 = time.ticks_us()
next_t = t0

while True:
    now = time.ticks_us()
    if time.ticks_diff(now, next_t) >= 0:
        v0 = a0.read_u16()
        v1 = a1.read_u16()
        sys.stdout.write("{},{},{}\n".format(time.ticks_diff(now, t0), v0, v1))
        next_t = time.ticks_add(next_t, PERIOD_US)
