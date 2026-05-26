from machine import Pin, Timer, PWM
import time

pins = [16, 17, 18]
leds = [Pin(p, Pin.OUT) for p in pins]
pwms = [PWM(Pin(p)) for p in pins]
     
for pwm in pwms:
    pwm.freq(1000)
    
# Chase effect
while True:
#     for led in leds:
#         led.on()
#         time.sleep(0.2)
#         led.off()
    for pwm in pwms:
        for duty in range(0, 54000, 512):
            pwm.duty_u16(duty)
            time.sleep_ms(10)
        for duty in range(54000, 0, -512):
            pwm.duty_u16(duty)
            time.sleep_ms(10)
        
        

# 
# while True:
#     for duty in range(0, 54000, 512):
#         pwm1.duty_u16(duty)
#         time.sleep_ms(10)
#     for duty in range(54000, 0, -512):
#         pwm1.duty_u16(duty)
#         time.sleep_ms(10)
# 
# while True:
#     led1.toggle()
#     time.sleep(0.5)
#     led2.toggle()
#     time.sleep(0.5)
#     led3.toggle()
#     time.sleep(0.5) 