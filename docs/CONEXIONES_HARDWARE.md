# Cableado de la urna electrónica

Las variantes normal y `_Tec` usan los mismos GPIO para cada lector. Los números de las tablas de ESP32 son los GPIO rotulados en la placa, por ejemplo `IO18`. En la Raspberry Pi se indica también el número físico del conector de 40 pines.

## ESP32 NFC con PN532

Selecciona **SPI** en los interruptores o puentes del PN532 antes de encenderlo. La posición depende de la versión del módulo.

| ESP32 NFC | PN532 o buzzer | Dirección |
| --- | --- | --- |
| GPIO18 | SCK o SCLK | ESP32 → PN532, reloj SPI |
| GPIO19 | MISO | PN532 → ESP32, datos |
| GPIO23 | MOSI | ESP32 → PN532, datos |
| GPIO5 | SS, CS o NSS | ESP32 → PN532, selección del módulo |
| GND | GND del PN532 | Tierra de referencia |
| Alimentación según el módulo | VCC o VIN del PN532 | Comprueba el voltaje en la ficha de la placa concreta |
| GPIO4 | Señal del buzzer | El firmware genera pulsos, adecuados para un piezo pasivo compatible |
| GND | Retorno del buzzer o GND de su controlador | Tierra de referencia |

El sketch usa SPI por hardware. No asigna GPIO a IRQ ni a reset. Si el módulo requiere fijar el nivel de reset, sigue su ficha técnica. El comentario «lado VIN» ubica el buzzer en la placa. La señal va en **GPIO4**.

Código: [NFC normal](../firmware/nfc_esp32/nfc_esp32.ino) · [NFC Tec](../firmware/nfc_esp32_Tec/nfc_esp32_Tec.ino) · [Referencia de un módulo Adafruit PN532](https://learn.adafruit.com/adafruit-pn532-rfid-nfc/python-circuitpython)

## ESP32 de huellas con R307 o AS608

La UART del sensor es **UART2 a 57 600 baudios, 8N1**. Cruza TX y RX según la tabla y guíate por las etiquetas o el diagrama del conector. Los colores de los cables pueden variar entre módulos.

| ESP32 de huellas | Sensor o buzzer | Dirección |
| --- | --- | --- |
| GPIO16 (RX2) | TX o TXD del sensor | Sensor → ESP32 |
| GPIO17 (TX2) | RX o RXD del sensor | ESP32 → sensor |
| GND | GND del sensor | Tierra de referencia |
| Alimentación según el módulo | VCC del sensor | Comprueba voltaje y corriente en la ficha del modelo |
| GPIO4 | Señal del buzzer | Normal: nivel digital. Tec: PWM mediante `analogWrite`. Comprueba que el buzzer sea compatible con la variante. |
| GND | Retorno del buzzer o GND de su controlador | Tierra de referencia |

Comprueba que GPIO16 y GPIO17 estén disponibles en tu placa. Algunas variantes de ESP32 reservan GPIO para la PSRAM. Si el lector tiene pines adicionales, el sketch solo utiliza TX y RX para comunicarse.

Código: [Huellas normal](../firmware/fingerprint_esp32/fingerprint_esp32.ino) · [Huellas Tec](../firmware/fingerprint_esp32_Tec/fingerprint_esp32_Tec.ino) · [Guía de hardware de Espressif](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/)

## Raspberry Pi 5

Cada LED lleva su propia resistencia en serie. Para un LED indicador común, puedes empezar con **330 Ω**. Conecta el ánodo hacia el GPIO a través de la resistencia y el cátodo a GND.

| Indicador | GPIO BCM | Pin físico | Conexión |
| --- | --- | --- | --- |
| Tarjeta validada | GPIO17 | 11 | GPIO → resistencia → ánodo del LED |
| Huella verificada | GPIO27 | 13 | GPIO → resistencia → ánodo del LED |
| Rostro verificado | GPIO22 | 15 | GPIO → resistencia → ánodo del LED |
| Tierra | GND | 14, por ejemplo | Cátodo de cada LED → GND de la Pi |

La cámara va en USB o en el conector de cámara compatible con la Pi. El código la abre por índice con OpenCV. La pantalla usa su propia conexión de video y táctil. Las dos ESP32 se comunican con la Raspberry Pi por Wi‑Fi. El cableado de SPI y UART queda entre cada ESP32 y su lector.

Código: [Control de los LED](../kiosk_ui/led_control.py) · [Captura de cámara](../face_local.py) · [Pinout oficial de Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)

## Antes de encender

1. Cablea con las placas apagadas. Verifica VCC, GND y la orientación de cada conector.
2. Los GPIO usan lógica de 3.3 V. Comprueba el nivel de las señales del lector además de su tensión de alimentación. Si alguna salida del lector entrega 5 V, usa un adaptador de nivel apropiado antes de conectarla al ESP32.
3. Conecta directamente un buzzer de dos patas entre GPIO4 y GND solo si es compatible con 3.3 V y su consumo está dentro de lo que admite el GPIO. Para un buzzer que requiera más tensión o corriente, usa un controlador adecuado y tierra común con la ESP32.
4. Prueba cada lector por separado con el monitor serie a **115 200 baudios**. Luego prueba en la urna que se encienda el LED correspondiente al validar tarjeta, huella y rostro.
