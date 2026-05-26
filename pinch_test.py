import machine
import utime

# Set the GPIO pin number 
SERVO_PIN = 20
PWM_FREQUENCY = 50

# Create PWM object 
pwm = machine.PWM(machine.Pin(SERVO_PIN))
pwm.freq(PWM_FREQUENCY)

# Function to set the servo angle
def set_angle(angle):
    # 0° = 1,000,000 ns (1ms), 180° = 2,000,000 ns (2ms)
    duty_ns = int((angle / 180) * 1_000_000 + 1_000_000)
    pwm.duty_ns(duty_ns)
    
#Loop 1 spins 180 deg, pauses and spins back
# while True:
#     try:
#     # Move the servo from 0 to 180 degrees
#         for angle in range(0, 181, 10):
#             set_angle(angle)
#             utime.sleep_ms(5)
#             
#         utime.sleep_ms(1000)
#     # Move the servo back from 180 to 0 degrees
#         for angle in range(180, -1, -10):
#             set_angle(angle)
#             utime.sleep_ms(5)
#             
#         utime.sleep_ms(1000)
#     except Exception as e:
#         print("Error:", e)
#         utime.sleep_ms(500)
        
# Loop 2 varies the speed
while True:
    try:
    # Move the servo from 0 to 180 degrees, decreasing speed halfway
        for angle in range(0, 181, 2):
            set_angle(angle)
            utime.sleep_ms(10)

        utime.sleep_ms(2000)
       
    # Move the servo back from 180 to 0 degrees
        for angle in range(180, -1, -1):
            set_angle(angle)
            utime.sleep_ms(5)
            
        utime.sleep_ms(2000)
    except Exception as e:
        print("Error:", e)
        utime.sleep_ms(500)