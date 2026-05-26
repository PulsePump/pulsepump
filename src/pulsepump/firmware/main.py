from machine import ADC, PWM, Pin
import time
import sys
import select

a0 = ADC(26)
a1 = ADC(27)

SAMPLE_HZ = 500
PERIOD_US = 1_000_000 // SAMPLE_HZ

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

t0 = time.ticks_us()
next_t = t0

# Set up servo
SERVO_PIN = 20
servo = PWM(Pin(SERVO_PIN))
servo.freq(50)
# PWM pulse length for servo
def set_servo(fraction):
    """Drive servo. fraction: 0.0 = fully closed, 1.0 = fully open."""
    fraction = max(0.0, min(1.0, fraction))
    pulse_us = 1000 + fraction * 1000
    duty = int((pulse_us / 20_000) * 65535)
    servo.duty_u16(duty)

# Target count for the pressure, PID drives until this is the pressure
SETPOINT = 8000

# Set gains
KP = 0.001
KI = 0.00001
KD = 0.0

integral = 0.0  # Running sum of error
prev_error = 0.0  # Last cycle error
prev_us = None  # Timestamp of last sample
output = 0.5  # Start servo in middle
INTEGRAL_LIMIT = 10_000.0  # Upper bound

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

while True:
    now = time.ticks_us()
    if time.ticks_diff(now, next_t) >= 0:
        v0 = a0.read_u16()  # read current pressure
        v1 = a1.read_u16()
        sys.stdout.write("{},{},{},{}\n".format(time.ticks_diff(now, t0), v0, v1, output))
        next_t = time.ticks_add(next_t, PERIOD_US)
        # Time since last sample
        dt = time.ticks_diff(now, prev_us) / 1_000_000 if prev_us else PERIOD_US / 1_000_000
        # Error in pressure
        # error = v0 - SETPOINT
        error = SETPOINT - v0

        # Integral - corrects steady state offset
        integral = max(-INTEGRAL_LIMIT, min(INTEGRAL_LIMIT, integral + error * dt))
        # Prevents overshoot
        derivative = (error - prev_error) / dt if dt > 0 else 0.0
        # Control output
        correction = KP * error + KI * integral + KD * derivative
        # Changes servo position
        output = max(0.0, min(1.0, 0.5 + correction))

        # Moves servo
        set_servo(output)

        # save state
        prev_error = error
        prev_us = now

        # CSV: elapsed time, raw ADC, servo position
        # sys.stdout.write("{},{},{:.4f}\n".format(
        # v0, output
        # ))
        #print(v0, output * 500 + 8000)

        next_t = time.ticks_add(next_t, PERIOD_US)

    if poll.poll(0):
        line = sys.stdin.readline()
        if line:
            line = line.strip()

            if line.startswith("SET="):
                try:
                    SETPOINT = int(line[4:])
                    integral = 0.0
                except ValueError:
                    pass

            elif line.startswith("RATE="):
                try:
                    hz = int(line[5:])
                    if hz > 0:
                        PERIOD_US = 1_000_000 // hz
                        next_t = time.ticks_us()
                except ValueError:
                    pass

            elif line.startswith("PIN1="):
                try:
                    a0 = ADC(int(line[5:]))
                except (ValueError, Exception):
                    pass

            elif line.startswith("PIN2="):
                try:
                    a1 = ADC(int(line[5:]))
                except (ValueError, Exception):
                    pass

            elif line.startswith("KP="):
                try:
                    KP = float(line[3:])
                except ValueError:
                    pass

            elif line.startswith("KI="):
                try:
                    KI = float(line[3:])
                    integral = 0.0
                except ValueError:
                    pass

            elif line.startswith("KD="):
                try:
                    KD = float(line[3:])
                except ValueError:
                    pass