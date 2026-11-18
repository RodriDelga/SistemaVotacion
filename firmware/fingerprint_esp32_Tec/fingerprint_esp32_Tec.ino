// Description: ESP32 con sensor R307/AS608 compatible. Consulta ordenes de huella de la API,
// activa la lectura real sin comandos Serial y entrega cada resultado una sola vez logica.
// Student ID: A00000000
// Date: 2026-10-25
//
// Conexiones del sensor:
//   Sensor TX -> ESP32 GPIO16 (RX2)
//   Sensor RX -> ESP32 GPIO17 (TX2)
//   Sensor VCC -> la alimentacion indicada por tu modelo; GND -> GND comun.
//   Revisa la hoja de datos: no todos los modelos admiten 3V3 ni tienen los mismos colores.

#include <Adafruit_Fingerprint.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>
#include <esp_wifi.h>
#include <esp_eap_client.h>
#include <time.h>
#include "secrets.h"  // Copie secrets.h.example como secrets.h; no lo versione.

const int SENSOR_RX_PIN = 16;
const int SENSOR_TX_PIN = 17;
const uint32_t SENSOR_BAUD_RATE = 57600;

// Buzzer de 2 patas en lado VIN (GPIO 4)
const int BUZZER_PIN = 4;

// Buzzer ACTIVO (oscilador interno): suena mientras el pin este en HIGH.
// No se le debe mandar una onda rapida; solo nivel fijo durante la duracion.
void buzzerBeep(int durationMs) {
    //digitalWrite(BUZZER_PIN, HIGH);
    analogWrite(BUZZER_PIN, 120);
    delay(durationMs);
    //digitalWrite(BUZZER_PIN, LOW);
    analogWrite(BUZZER_PIN, 0);
}

void buzzerInit() {
    pinMode(BUZZER_PIN, OUTPUT);
    analogWrite(BUZZER_PIN, 120);
    //digitalWrite(BUZZER_PIN, LOW);
    // Beep corto de inicio (60 ms) para comprobar que el buzzer funciona fisicamente
    buzzerBeep(60);
}

void buzzerOrderReceived() {
    // Un pitido corto al pedir el dedo
    buzzerBeep(100);
}

void buzzerSuccess() {
    // Doble pitido de confirmacion
    buzzerBeep(80);
    delay(60);
    buzzerBeep(120);
}

void buzzerError() {
    // Tres pitidos cortos = error / huella no coincide
    for (int i = 0; i < 3; i++) {
        buzzerBeep(100);
        delay(80);
    }
}

const unsigned long WIFI_TIMEOUT_MS = 15000;
const unsigned long FINGER_WAIT_MS = 10000;
const int HTTP_TIMEOUT_MS = 5000;
const unsigned long COMMAND_POLL_MS = 2000;
const unsigned long RESULT_RETRY_MS = 3000;
const unsigned long WIFI_RETRY_MS = 10000;
const unsigned long SENSOR_QUERY_MS = 50;

HardwareSerial sensorSerial(2);
Adafruit_Fingerprint finger(&sensorSerial);
Preferences securityPreferences;

const uint8_t AUTO_IDLE = 0;
const uint8_t AUTO_WAIT_FINGER = 1;
const uint8_t AUTO_SEND_RESULT = 2;
const uint8_t AUTO_WAIT_REMOVE = 3;

uint8_t autoState = AUTO_IDLE;
String autoCommandId = "";
String autoSessionId = "";
int autoResultSlot = 0;
bool sensorReady = false;
bool pollingPaused = false;
unsigned long autoStartedAt = 0;
unsigned long lastSensorQueryAt = 0;
unsigned long lastCommandPollAt = 0;
unsigned long lastResultAttemptAt = 0;
unsigned long lastWifiRetryAt = 0;

// ---------- Utilidades generales ----------

String readLine() {
    while (!Serial.available()) {
        delay(10);
    }
    String lineText = Serial.readStringUntil('\n');
    lineText.trim();
    return lineText;
}

int askSlot(const char* promptText) {
    Serial.println(promptText);
    int slot = readLine().toInt();
    if (slot < 1 || slot > finger.capacity) {
        Serial.println("Slot invalido.");
        return 0;
    }
    return slot;
}

void synchronizeSequence(uint64_t serverLastSequence) {
    securityPreferences.begin("fp-security", false);
    securityPreferences.putULong64("lastSeq", serverLastSequence);
    securityPreferences.end();
    Serial.printf("Contador sincronizado correctamente a %llu. La siguiente solicitud usara %llu.\n",
                  (unsigned long long)serverLastSequence,
                  (unsigned long long)(serverLastSequence + 1));
}

bool waitForFinger(bool present, unsigned long timeoutMs) {
    unsigned long startTime = millis();
    uint8_t expectedResult = present ? FINGERPRINT_OK : FINGERPRINT_NOFINGER;
    bool reached = false;
    while (!reached && millis() - startTime < timeoutMs) {
        reached = (finger.getImage() == expectedResult);
        if (!reached) {
            delay(50);
        }
    }
    if (!reached) {
        Serial.println("Tiempo agotado.");
    }
    return reached;
}

bool captureToBuffer(uint8_t bufferNumber) {
    if (!waitForFinger(true, FINGER_WAIT_MS)) {
        return false;
    }
    if (finger.image2Tz(bufferNumber) != FINGERPRINT_OK) {
        Serial.println("No se pudo procesar la imagen, intenta de nuevo.");
        return false;
    }
    return true;
}

// Lee una cadena JSON aunque haya espacios alrededor de los dos puntos.
String readJsonString(const String& json, const char* key) {
    String quotedKey = String("\"") + key + "\"";
    int keyPosition = json.indexOf(quotedKey);
    if (keyPosition < 0) {
        return "";
    }
    int colonPosition = json.indexOf(':', keyPosition + quotedKey.length());
    if (colonPosition < 0) {
        return "";
    }
    int cursor = colonPosition + 1;
    while (cursor < (int)json.length() && isspace(json[cursor])) {
        cursor++;
    }
    if (cursor >= (int)json.length() || json[cursor] != '"') {
        return "";
    }
    int end = json.indexOf('"', cursor + 1);
    if (end < 0) {
        return "";
    }
    return json.substring(cursor + 1, end);
}

bool readJsonBool(const String& json, const char* key) {
    String quotedKey = String("\"") + key + "\"";
    int keyPosition = json.indexOf(quotedKey);
    if (keyPosition < 0) {
        return false;
    }
    int colonPosition = json.indexOf(':', keyPosition + quotedKey.length());
    if (colonPosition < 0) {
        return false;
    }
    int cursor = colonPosition + 1;
    while (cursor < (int)json.length() && isspace(json[cursor])) {
        cursor++;
    }
    return json.substring(cursor, cursor + 4) == "true";
}

// ---------- HMAC-SHA256, nonce, secuencia persistente y respuestas ----------

String bytesToHex(const uint8_t* bytes, size_t length) {
  static const char hexChars[] = "0123456789abcdef";
  String result;
  result.reserve(length * 2);
  for (size_t i = 0; i < length; i++) {
    result += hexChars[bytes[i] >> 4];
    result += hexChars[bytes[i] & 15];
  }
  return result;
}

bool decodeHmacKey(uint8_t* output) {
  String encoded = String(FINGERPRINT_HMAC_KEY_HEX);
  if (encoded.length() != 64) return false;
  for (uint8_t i = 0; i < 32; i++) {
    char part[3] = {encoded[i * 2], encoded[i * 2 + 1], 0};
    char* end = nullptr;
    unsigned long value = strtoul(part, &end, 16);
    if (end == part || *end != 0) return false;
    output[i] = (uint8_t)value;
  }
  return true;
}

String hmacSha256(const String& message) {
  uint8_t key[32];
  uint8_t output[32];
  if (!decodeHmacKey(key)) return "";
  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  int result = mbedtls_md_hmac(info, key, sizeof(key), (const uint8_t*)message.c_str(),
                               message.length(), output);
  memset(key, 0, sizeof(key));
  return result == 0 ? bytesToHex(output, sizeof(output)) : "";
}

String sha256Hex(const String& body) {
  uint8_t output[32];
  const mbedtls_md_info_t* mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (mdInfo == NULL) return "";
  
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mdInfo, 0);
  mbedtls_md_starts(&ctx);
  mbedtls_md_update(&ctx, (const uint8_t*)body.c_str(), body.length());
  mbedtls_md_finish(&ctx, output);
  mbedtls_md_free(&ctx);

  return bytesToHex(output, sizeof(output));
}

bool constantTimeEqual(const String& a, const String& b) {
  if (a.length() != b.length()) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < a.length(); i++) difference |= (uint8_t)a[i] ^ (uint8_t)b[i];
  return difference == 0;
}

String randomNonce() {
  uint8_t bytes[16];
  for (uint8_t i = 0; i < 16; i += 4) {
    uint32_t value = esp_random();
    memcpy(bytes + i, &value, 4);
  }
  return bytesToHex(bytes, sizeof(bytes));
}

bool validClock() {
  return time(nullptr) > 1700000000;
}

bool configureClock() {
  configTime(0, 0, NTP_SERVER);
  unsigned long started = millis();
  while (!validClock() && millis() - started < 15000) delay(250);
  return validClock();
}

// ---------- Diagnostico: sensor, WiFi y API ----------

bool checkSensor() {
    Serial.println("[1/3] Probando el sensor de huella...");
    sensorSerial.begin(SENSOR_BAUD_RATE, SERIAL_8N1, SENSOR_RX_PIN, SENSOR_TX_PIN);
    finger.begin(SENSOR_BAUD_RATE);
    if (!finger.verifyPassword()) {
        Serial.println("  FALLO: el sensor no responde.");
        Serial.println("  Revisa TX/RX, alimentacion y GND comun segun la hoja de datos.");
        return false;
    }
    finger.getParameters();
    if (finger.capacity == 0) {
        finger.capacity = 127;
    }
    finger.getTemplateCount();
    Serial.printf("  OK: capacidad %d huellas; guardadas %d.\n", finger.capacity, finger.templateCount);
    return true;
}

bool connectWifi() {
    Serial.println("[2/3] Conectando a WiFi empresarial WPA2-Enterprise...");

    WiFi.disconnect(true);
    delay(500);

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);

    // Configuración de identidad y credenciales PEAP
    esp_eap_client_set_identity(
        (uint8_t*)WIFI_IDENTITY,
        strlen(WIFI_IDENTITY)
    );

    esp_eap_client_set_username(
        (uint8_t*)WIFI_USERNAME,
        strlen(WIFI_USERNAME)
    );

    esp_eap_client_set_password(
        (uint8_t*)WIFI_PASSWORD,
        strlen(WIFI_PASSWORD)
    );

    // Activar autenticación WPA2-Enterprise
    esp_wifi_sta_enterprise_enable();

    Serial.println("  Autenticación PEAP configurada.");
    Serial.print("  SSID: ");
    Serial.println(WIFI_SSID);

    WiFi.begin(WIFI_SSID);

    unsigned long startTime = millis();

    while (WiFi.status() != WL_CONNECTED &&
           millis() - startTime < WIFI_TIMEOUT_MS) {

        delay(500);
        Serial.print(".");
    }

    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.printf(
            "  FALLO WiFi. Estado: %d\n",
            WiFi.status()
        );

        return false;
    }

    Serial.println("  CONEXION EMPRESARIAL EXITOSA.");

    Serial.print("  IP del ESP32: ");
    Serial.println(WiFi.localIP());

    Serial.print("  Gateway: ");
    Serial.println(WiFi.gatewayIP());

    Serial.printf("  Señal: %d dBm\n", WiFi.RSSI());

    // Sincronización de reloj para las firmas HMAC
    if (!configureClock()) {
        Serial.println("  FALLO: no se pudo sincronizar NTP.");
        return false;
    }

    Serial.println("  Reloj NTP sincronizado.");

    return true;
}

int signedHttpRequest(const char* method, const String& path, const String& jsonBody,
                      String& responseBody) {
    if (!validClock()) return -900;
    securityPreferences.begin("fp-security", false);
    uint64_t sequence = securityPreferences.getULong64("lastSeq", 0) + 1;
    securityPreferences.putULong64("lastSeq", sequence);
    securityPreferences.end();

    Serial.printf(
        "[DIAGNOSTICO HMAC] Secuencia ESP32: %llu\n",
        (unsigned long long)sequence
    );

    String nonce = randomNonce();
    String timestamp = String((unsigned long long)time(nullptr));
    String sequenceText = String((unsigned long long)sequence);
    String canonical = String("esp32-request-v1\n") + method + "\n" + path + "\n" +
                       sha256Hex(jsonBody) + "\n" + FINGERPRINT_DEVICE_ID + "\n" +
                       timestamp + "\n" + nonce + "\n" + sequenceText;
    String signature = hmacSha256(canonical);
    if (signature.length() != 64) return -901;

    HTTPClient http;
    const char* responseHeaders[] = {"X-Device-Id", "X-Timestamp", "X-Nonce", "X-Signature"};
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.begin(String(API_BASE_URL) + path);
    http.collectHeaders(responseHeaders, 4);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-Id", FINGERPRINT_DEVICE_ID);
    http.addHeader("X-Timestamp", timestamp);
    http.addHeader("X-Nonce", nonce);
    http.addHeader("X-Sequence", sequenceText);
    http.addHeader("X-Signature", signature);
    int statusCode = strcmp(method, "GET") == 0 ? http.GET() : http.POST(jsonBody);
    responseBody = statusCode < 0 ? HTTPClient::errorToString(statusCode) : http.getString();
    if (statusCode > 0) {
      String responseNonce = http.header("X-Nonce");
      String responseTimestamp = http.header("X-Timestamp");
      String responseDevice = http.header("X-Device-Id");
      String responseSignature = http.header("X-Signature");
      String responseCanonical = String("esp32-response-v1\n") + responseDevice + "\n" +
                                 responseTimestamp + "\n" + nonce + "\n" + responseNonce +
                                 "\n" + sha256Hex(responseBody);
      String expected = hmacSha256(responseCanonical);
      long responseTime = responseTimestamp.toInt();
      if (responseDevice != FINGERPRINT_DEVICE_ID || responseNonce.length() < 16 ||
          labs((long)time(nullptr) - responseTime) > 120 ||
          !constantTimeEqual(responseSignature, expected)) {
        responseBody = "Respuesta sin autenticacion valida";
        statusCode = -902;
      }
    }
    http.end();
    return statusCode;
}

int httpGet(const String& path, String& responseBody) {
    return signedHttpRequest("GET", path, "", responseBody);
}

int httpPostJson(const String& path, const String& jsonBody, String& responseBody) {
    return signedHttpRequest("POST", path, jsonBody, responseBody);
}

bool checkApi() {
    Serial.println("[3/3] Probando la API...");
    String responseBody = "";
    int statusCode = httpGet("/api/v1/device/fingerprint-command/pending", responseBody);
    if (statusCode == 200) {
        Serial.println("  OK: API, HMAC, reloj y respuesta autenticada correctos.");
        return true;
    }
    if (statusCode == 401) {
        Serial.println("  FALLO 401: identidad HMAC, reloj o credencial rechazada.");
        return false;
    }
    if (statusCode < 0) {
        Serial.println("  FALLO de red con " + String(API_BASE_URL) + ": " + responseBody);
        Serial.println("  Revisa IP/puerto, uvicorn --host 0.0.0.0, firewall y que ambos esten en la misma red.");
        return false;
    }
    Serial.printf("  FALLO: API HTTP %d: %s\n", statusCode, responseBody.c_str());
    return false;
}

// ---------- Lectura local para enrolamiento y diagnostico por Serial ----------

void enrollFinger(int slot) {
    Serial.println("Pon el dedo...");
    if (!captureToBuffer(1)) {
        return;
    }
    Serial.println("Quita el dedo.");
    delay(1000);
    if (!waitForFinger(false, FINGER_WAIT_MS)) {
        return;
    }
    Serial.println("Pon el MISMO dedo otra vez...");
    if (!captureToBuffer(2)) {
        return;
    }
    if (finger.createModel() != FINGERPRINT_OK) {
        Serial.println("Las dos lecturas no coinciden, intenta de nuevo.");
        return;
    }
    if (finger.storeModel(slot) != FINGERPRINT_OK) {
        Serial.println("No se pudo guardar la huella en el sensor.");
        return;
    }
    buzzerSuccess();
    Serial.printf("Huella guardada en slot %d. Usalo como fingerprintSlot del votante.\n", slot);
}

int searchFinger() {
    Serial.println("Pon el dedo...");
    if (!captureToBuffer(1)) {
        return 0;
    }
    uint8_t searchResult = finger.fingerSearch();
    if (searchResult == FINGERPRINT_OK) {
        buzzerSuccess();
        Serial.printf("Huella reconocida: slot %d (confianza %d)\n", finger.fingerID, finger.confidence);
        return finger.fingerID;
    }
    if (searchResult == FINGERPRINT_NOTFOUND) {
        Serial.println("Huella NO registrada en el sensor.");
    } else {
        Serial.println("Error al buscar la huella.");
    }
    return 0;
}

// ---------- Lectura automatica no bloqueante y entrega confiable ----------

void resetAutomaticOperation() {
    autoState = AUTO_IDLE;
    autoCommandId = "";
    autoSessionId = "";
    autoResultSlot = 0;
    lastCommandPollAt = millis() - COMMAND_POLL_MS;
}

void finishAutomaticDelivery() {
    autoCommandId = "";
    autoSessionId = "";
    autoResultSlot = 0;
    if (finger.getImage() == FINGERPRINT_NOFINGER) {
        resetAutomaticOperation();
        return;
    }
    autoState = AUTO_WAIT_REMOVE;
    lastSensorQueryAt = millis() - SENSOR_QUERY_MS;
    Serial.println("Retira el dedo. La siguiente orden se atendera cuando el sensor quede libre.");
}

void queueAutomaticResult(int slot) {
    autoResultSlot = slot;
    autoState = AUTO_SEND_RESULT;
    lastResultAttemptAt = millis() - RESULT_RETRY_MS;
    Serial.printf("Lectura terminada; slot reportado: %d. Enviando resultado a la API.\n", slot);
}

void serviceAutomaticFingerRead() {
    if (autoState != AUTO_WAIT_FINGER && autoState != AUTO_WAIT_REMOVE) {
        return;
    }
    unsigned long now = millis();
    if (now - lastSensorQueryAt < SENSOR_QUERY_MS) {
        return;
    }
    lastSensorQueryAt = now;

    uint8_t imageResult = finger.getImage();
    if (autoState == AUTO_WAIT_REMOVE) {
        if (imageResult == FINGERPRINT_NOFINGER) {
            Serial.println("Sensor libre; se reanuda la consulta de ordenes.");
            resetAutomaticOperation();
        }
        return;
    }
    if (imageResult == FINGERPRINT_NOFINGER) {
        if (now - autoStartedAt >= FINGER_WAIT_MS) {
            Serial.println("No se detecto dedo antes del timeout; se reportara un intento fallido.");
            buzzerError();
            queueAutomaticResult(0);
        }
        return;
    }
    if (imageResult != FINGERPRINT_OK) {
        Serial.printf("Error de captura 0x%02X; se reintentara hasta el timeout.\n", imageResult);
        if (now - autoStartedAt >= FINGER_WAIT_MS) {
            buzzerError();
            queueAutomaticResult(0);
        }
        return;
    }

    uint8_t convertResult = finger.image2Tz(1);
    if (convertResult != FINGERPRINT_OK) {
        Serial.printf("No se pudo convertir la imagen (0x%02X).\n", convertResult);
        buzzerError();
        queueAutomaticResult(0);
        return;
    }

    uint8_t searchResult = finger.fingerSearch();
    if (searchResult == FINGERPRINT_OK) {
        Serial.printf("Huella encontrada: slot %d, confianza %d.\n", finger.fingerID, finger.confidence);
        queueAutomaticResult(finger.fingerID);
    } else {
        if (searchResult == FINGERPRINT_NOTFOUND) {
            Serial.println("Huella no registrada en el sensor.");
        } else {
            Serial.printf("Error de busqueda 0x%02X.\n", searchResult);
        }
        buzzerError();
        queueAutomaticResult(0);
    }
}

void serviceAutomaticResultDelivery() {
    if (autoState != AUTO_SEND_RESULT || WiFi.status() != WL_CONNECTED) {
        return;
    }
    unsigned long now = millis();
    if (now - lastResultAttemptAt < RESULT_RETRY_MS) {
        return;
    }
    lastResultAttemptAt = now;

    String postBody = "{\"commandId\":\"" + autoCommandId + "\",\"fingerprintSlot\":" + String(autoResultSlot) + "}";
    String responseBody = "";
    String path = "/api/v1/session/" + autoSessionId + "/fingerprint";
    int statusCode = httpPostJson(path, postBody, responseBody);

    if (statusCode == 200) {
        Serial.println("API: huella VERIFICADA para el votante de la sesion.");
        buzzerSuccess(); // Sonido de confirmación al verificar la huella
        finishAutomaticDelivery();
        return;
    }
    if (statusCode == 401 && responseBody.indexOf("Huella no coincide") >= 0) {
        Serial.println("API: intento fallido registrado. Espera otra orden si quedan intentos.");
        buzzerError();
        finishAutomaticDelivery();
        return;
    }
    if (statusCode == 409) {
        Serial.println("API: orden ya procesada/cerrada; no se duplicara el resultado.");
        finishAutomaticDelivery();
        return;
    }
    if (statusCode == 410 || statusCode == 404 || statusCode == 423) {
        Serial.println("API: orden o sesion vencida/cancelada; se descarta el resultado tardio.");
        finishAutomaticDelivery();
        return;
    }
    if (statusCode == 400 || statusCode == 422) {
        Serial.printf("API rechazo el formato (HTTP %d): %s\n", statusCode, responseBody.c_str());
        finishAutomaticDelivery();
        return;
    }

    // Fallos de red, autenticacion o servidor: conserva el mismo resultado y reintenta.
    Serial.printf("Entrega pendiente (HTTP %d): %s. Reintentare sin leer otra vez.\n", statusCode, responseBody.c_str());
}

void pollFingerprintCommand() {
    if (pollingPaused || autoState != AUTO_IDLE || WiFi.status() != WL_CONNECTED) {
        return;
    }
    unsigned long now = millis();
    if (now - lastCommandPollAt < COMMAND_POLL_MS) {
        return;
    }
    lastCommandPollAt = now;

    String responseBody = "";
    int statusCode = httpGet("/api/v1/device/fingerprint-command/pending", responseBody);
    if (statusCode != 200) {
        Serial.printf("Consulta de orden fallo (HTTP %d): %s\n", statusCode, responseBody.c_str());
        return;
    }
    if (!readJsonBool(responseBody, "active")) {
        return;
    }

    String commandId = readJsonString(responseBody, "commandId");
    String sessionId = readJsonString(responseBody, "sessionId");
    if (commandId.length() == 0 || sessionId.length() == 0) {
        Serial.println("Orden recibida con JSON incompleto; se ignorara esta respuesta.");
        return;
    }
    if (!sensorReady) {
        Serial.println("Hay una orden, pero el sensor no esta disponible. No se consumira un intento.");
        return;
    }

    autoCommandId = commandId;
    autoSessionId = sessionId;
    autoStartedAt = now;
    lastSensorQueryAt = now - SENSOR_QUERY_MS;
    autoState = AUTO_WAIT_FINGER;
    buzzerOrderReceived();
    Serial.println("ORDEN RECIBIDA. Pon el dedo en el sensor ahora; tienes 10 segundos.");
}

void serviceWifiConnection() {
    if (WiFi.status() == WL_CONNECTED) {
        return;
    }
    unsigned long now = millis();
    if (now - lastWifiRetryAt < WIFI_RETRY_MS) {
        return;
    }
    lastWifiRetryAt = now;
    Serial.println("WiFi desconectado; reintentando en segundo plano.");
    WiFi.mode(WIFI_STA);
    WiFi.reconnect();
}

// ---------- Menu Serial opcional: no interviene en el flujo normal ----------

void showMenu() {
    Serial.println(R"(
===== MENU OPCIONAL DE PRUEBAS =====
e -> registrar una huella nueva en un slot
b -> buscar una huella (prueba local del sensor)
i -> repetir el diagnostico
d -> borrar un slot
x -> borrar TODAS las huellas
p -> pausar / reanudar sondeo automatico
s -> sincronizar secuencia con el servidor
t -> probar el buzzer (orden, exito y error)
La verificacion de votacion se activa automaticamente desde el frontend.
====================================)");
}

void runDiagnostics() {
    sensorReady = checkSensor();
    bool isWifiOk = connectWifi();
    bool isApiOk = isWifiOk ? checkApi() : false;
    Serial.println();
    Serial.println(sensorReady && isWifiOk && isApiOk ? "DIAGNOSTICO: todo en orden." : "DIAGNOSTICO: revisa los fallos anteriores.");
}

void handleSerialCommand() {
    if (!Serial.available()) {
        return;
    }
    char command = Serial.read();
    delay(50);
    while (Serial.available()) {
        Serial.read();
    }
    if (command == '\r' || command == '\n') {
        return;
    }
    if (autoState != AUTO_IDLE) {
        Serial.println("Hay una lectura/entrega automatica en curso. Espera a que termine.");
        return;
    }

    if (command == 'e') {
        int slot = askSlot("Slot donde guardar la huella (por ejemplo 1):");
        if (slot != 0) {
            enrollFinger(slot);
        }
    } else if (command == 'b') {
        searchFinger();
    } else if (command == 'i') {
        runDiagnostics();
    } else if (command == 'd') {
        int slot = askSlot("Slot a borrar:");
        if (slot != 0 && finger.deleteModel(slot) == FINGERPRINT_OK) {
            Serial.println("Slot borrado.");
        }
    } else if (command == 'x') {
        Serial.println("Escribe SI para borrar TODAS las huellas:");
        if (readLine() == "SI") {
            finger.emptyDatabase();
            Serial.println("Sensor vacio.");
        } else {
            Serial.println("Cancelado.");
        }
    } else if (command == 'p') {
        pollingPaused = !pollingPaused;
        Serial.println(pollingPaused ? "Sondeo automatico PAUSADO." : "Sondeo automatico REANUDADO.");
        return;
    } else if (command == 's') {
        Serial.println("Escribe el numero 'Ultima secuencia aceptada' que imprime el backend:");
        String valStr = readLine();
        uint64_t serverSeq = strtoull(valStr.c_str(), nullptr, 10);
        if (serverSeq > 0) {
            synchronizeSequence(serverSeq);
            pollingPaused = false;
            Serial.println("Sondeo reanudado. Probando conexion con el nuevo contador...");
        } else {
            Serial.println("Valor invalido o 0. Cancelado.");
        }
        return;
    } else if (command == 't') {
        Serial.println("Probando buzzer (orden, exito y error)...");
        buzzerOrderReceived();
        delay(300);
        buzzerSuccess();
        delay(300);
        buzzerError();
        return;
    } else if (command == 'v') {
        Serial.println("El comando 'v' no es necesario: kiosk_ui crea la orden mediante la API.");
        return;
    } else {
        return;
    }
    showMenu();
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    buzzerInit();
    // Si prefieres hacerlo por codigo en lugar del menu Serial, descomenta la siguiente linea con el valor real y luego borrala:
    // synchronizeSequence(123);
    runDiagnostics();
    showMenu();
    lastCommandPollAt = millis() - COMMAND_POLL_MS;
    lastWifiRetryAt = millis();
}

void loop() {
    handleSerialCommand();
    serviceWifiConnection();
    serviceAutomaticFingerRead();
    serviceAutomaticResultDelivery();
    pollFingerprintCommand();
}