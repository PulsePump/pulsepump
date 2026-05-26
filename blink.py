from machine import Pin, Timer

led = Pin("LED", Pin.OUT)
timer = Timer()

def blink(t):
    led.toggle()

timer.init(freq=2, mode=Timer.PERIODIC, callback=blink)