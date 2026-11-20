# 13 · Glosario

| Término | Significado en este proyecto |
| --- | --- |
| Actuador | Dispositivo que transforma una señal de control en una acción física. Los LED emiten luz y los buzzers producen sonido. |
| Adaptador | Código que conecta al controlador con un servicio real o simulado mediante una interfaz compartida. |
| API | Conjunto de operaciones que un programa ofrece a otro. FastAPI recibe órdenes de sesión, huella y voto. |
| Atestación | Declaración firmada de la urna sobre lo que obtuvo en la comparación facial de una sesión. |
| Base de datos | Almacenamiento organizado de registros. El despliegue previsto usa PostgreSQL y las pruebas usan SQLite. |
| Bitácora técnica | Eventos con tipo, estado, origen lógico y fecha. El panel los usa para series y alertas. |
| Boleta | Lista de candidaturas elegibles. En el modelo `ballot`, cada fila representa una selección individual. |
| Clave primaria y foránea | La primera identifica una fila. La segunda referencia una fila de otra tabla. |
| Cookie de sesión | Dato enviado por el navegador que el servidor usa para reconocer una sesión administrativa vigente. |
| Desafío | Valor temporal que vincula una verificación facial a una sesión y se consume al responder correctamente al protocolo. |
| Embedding o vector facial | Lista de valores numéricos que representa rasgos faciales para una comparación. Se almacena cifrado. |
| Endpoint | Operación que identifica un método HTTP y una ruta, como `GET /api/v1/kiosk/lock`. |
| ESP32 | Microcontrolador con Wi-Fi que ejecuta uno de los programas de lector. |
| Firmware | Programa que se carga y se ejecuta en el microcontrolador. |
| GPIO | Pin de entrada/salida programable. BCM es la numeración lógica empleada para los LED de la Pi. |
| HMAC | Firma simétrica que permite comprobar integridad y origen usando una clave compartida. |
| HTTP y JSON | HTTP transporta peticiones y respuestas. JSON organiza el contenido en objetos, campos y listas. |
| Latido | Mensaje periódico de un equipo para indicar que sigue comunicándose. |
| NFC y UID | NFC es comunicación de campo cercano. UID es el identificador que el lector obtiene de una tarjeta. |
| Nonce y secuencia | El nonce identifica un mensaje de un solo uso. La secuencia aumenta para descartar repeticiones o mensajes fuera de orden. |
| NTP | Protocolo de sincronización del reloj usado por los ESP32 para validar vigencia. |
| ORM | Mapeo entre objetos del programa y tablas. Los modelos SQLModel describen los registros. |
| Padrón | Registro de votantes, región, habilitación y estado de participación. |
| PWM | Variación de la fracción de tiempo en que una señal permanece activa. La variante Tec de huella usa una salida de este tipo para el buzzer. |
| Raspberry Pi | Computadora anfitriona prevista de la interfaz de la urna, la cámara y el backend. |
| Sensor | Dispositivo que adquiere información física, como la impresión de un dedo o una imagen. |
| Slot | Número de posición de una plantilla de huella dentro del sensor. |
| SPI y UART | Interfaces de comunicación por cable. SPI conecta el PN532 y UART el lector de huella con su ESP32. |
| TLS | Protección del transporte que se usa para la conexión de base PostgreSQL configurada con TLS y puede aplicarse al panel mediante HTTPS. |
| Transacción | Grupo de operaciones que se confirma como unidad, como marcar participación, guardar selecciones y cerrar la sesión. |
| UTC | Referencia temporal usada por la API, la base y los dispositivos al comparar marcas y expiraciones. |
