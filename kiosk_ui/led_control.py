# Ruta: kiosk_ui/led_control.py
from gpiozero import LED

# Pines GPIO en la Raspberry Pi 5
led_tarjeta = LED(17)
led_huella = LED(27)
led_rostro = LED(22)

def encender_tarjeta():
    led_tarjeta.on()

def encender_huella():
    led_huella.on()

def encender_rostro():
    led_rostro.on()

def apagar_todos():
    led_tarjeta.off()
    led_huella.off()
    led_rostro.off()
