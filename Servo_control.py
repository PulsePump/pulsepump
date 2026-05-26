import machine
import utime
from machine import ADC
import time
import sys
import select

# Set the GPIO pin number 
SERVO_PIN = 20
# Set the PWM frequency
PWM_FREQUENCY = 50
# Create a PWM object with the specified pin and frequency
pwm = machine.PWM(machine.Pin(SERVO_PIN))
pwm.freq(PWM_FREQUENCY)
# Function to set the servo angle
def set_angle(angle):
    # 0° = 500,000 ns (0.5ms), 180° = 2,500,000 ns (2.5ms)
    duty_ns = int((angle / 180) * 2_000_000 + 500_000)
    pwm.duty_ns(duty_ns)

def set_angle(angle):
    # 0° = 1,000,000 ns (1ms), 180° = 2,000,000 ns (2ms)
    duty_ns = int((angle / 180) * 1_000_000 + 1_000_000)
    pwm.duty_ns(duty_ns)

a0 = ADC(26)
a1 = ADC(27)

SAMPLE_HZ = 500
PERIOD_US = 1_000_000 // SAMPLE_HZ

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

t0 = time.ticks_us()
next_t = t0

while True:
    now = time.ticks_us()
    if time.ticks_diff(now, next_t) >= 0:
        v0 = a0.read_u16()
        v1 = a1.read_u16()
        sys.stdout.write("{},{},{}\n".format(time.ticks_diff(now, t0), v0, v1))
        next_t = time.ticks_add(next_t, PERIOD_US)

    if poll.poll(0):
        line = sys.stdin.readline()
        if line:
            line = line.strip()
            if line.startswith("RATE="):
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
# Loop 2 varies the speed
while True:
    try:
    # Move the servo from 0 to 180 degrees, decreasing speed halfway
        for angle in range(0, 181, 5):
            set_angle(angle)
            utime.sleep_ms(100)

        utime.sleep_ms(2000)
       
    # Move the servo back from 180 to 0 degrees
        for angle in range(180, -1, -1):
            set_angle(angle)
            utime.sleep_ms(5)
            
        utime.sleep_ms(2000)
    except Exception as e:
        print("Error:", e)
        utime.sleep_ms(500)
        