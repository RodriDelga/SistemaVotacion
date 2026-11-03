// ESP32 dedicada al PN532. WiFi + HTTP local + HMAC-SHA256.
// No realiza lecturas hasta recibir una orden autenticada de la Raspberry Pi.
#include <SPI.h>
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <mbedtls/md.h>
#include <time.h>
#include "secrets.h"

#define PN532_SCK 18
#define PN532_MISO 19
#define PN532_MOSI 23
#define PN532_SS 5
const unsigned long SCAN_TIMEOUT_MS = 20000;
const size_t MAX_BODY = 2048;

Adafruit_PN532 nfc(PN532_SS);
WebServer server(80);
Preferences preferences;
bool nfcReady = false;
uint64_t lastSequence = 0;
String usedNonces[16];
uint8_t nonceCursor = 0;

bool constantTimeEqual(const String& a, const String& b) {
  if (a.length() != b.length()) return false;
  uint8_t diff = 0;
  for (size_t i = 0; i < a.length(); i++) diff |= (uint8_t)a[i] ^ (uint8_t)b[i];
  return diff == 0;
}

bool decodeKey(uint8_t* output) {
  String encoded = String(NFC_HMAC_KEY_HEX);
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

String hmacHex(const String& message) {
  uint8_t key[32];
  uint8_t output[32];
  if (!decodeKey(key)) return "";
  const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (mbedtls_md_hmac(info, key, sizeof(key), (const uint8_t*)message.c_str(),
                      message.length(), output) != 0) {
    memset(key, 0, sizeof(key));
    return "";
  }
  memset(key, 0, sizeof(key));
  static const char HEX[] = "0123456789abcdef";
  String result;
  for (uint8_t byte : output) {
    result += HEX[byte >> 4];
    result += HEX[byte & 15];
  }
  return result;
}

String commandCanonical(const String& deviceId, const String& sessionId,
                        const String& action, const String& nonce,
                        uint64_t sequence, uint64_t expiresAt) {
  return String("nfc-command-v1\n") + deviceId + "\n" + sessionId + "\n" + action +
         "\n" + nonce + "\n" + String((unsigned long long)sequence) + "\n" +
         String((unsigned long long)expiresAt);
}

String responseCanonical(const String& deviceId, const String& sessionId,
                         const String& nonce, uint64_t sequence,
                         const String& status, const String& uid, uint64_t expiresAt) {
  return String("nfc-response-v1\n") + deviceId + "\n" + sessionId + "\n" + nonce +
         "\n" + String((unsigned long long)sequence) + "\n" + status + "\n" + uid +
         "\n" + String((unsigned long long)expiresAt);
}

bool nonceUsed(const String& nonce) {
  for (const String& saved : usedNonces) if (saved == nonce) return true;
  return false;
}

void rememberNonce(const String& nonce) {
  usedNonces[nonceCursor] = nonce;
  nonceCursor = (nonceCursor + 1) % 16;
}

void sendError(int code, const char* message) {
  server.send(code, "application/json", String("{\"detail\":\"") + message + "\"}");
}

void sendSignedResponse(const String& sessionId, const String& nonce,
                        uint64_t sequence, const String& status, const String& uid) {
  uint64_t expiresAt = (uint64_t)time(nullptr) + 15;
  String signature = hmacHex(responseCanonical(NFC_DEVICE_ID, sessionId, nonce,
                                               sequence, status, uid, expiresAt));
  if (signature.length() != 64) {
    sendError(500, "security_configuration");
    return;
  }
  StaticJsonDocument<1024> doc;
  doc["deviceId"] = NFC_DEVICE_ID;
  doc["sessionId"] = sessionId;
  doc["nonce"] = nonce;
  doc["sequence"] = sequence;
  doc["status"] = status;
  doc["uid"] = uid;
  doc["expiresAt"] = expiresAt;
  doc["hmac"] = signature;
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

bool timeReady() {
  return time(nullptr) > 1700000000;
}

bool configureTime() {
  configTime(0, 0, NTP_SERVER);
  unsigned long started = millis();
  while (!timeReady() && millis() - started < 15000) delay(250);
  return timeReady();
}

void handleScan() {
  if (!nfcReady || !timeReady()) {
    sendError(503, "reader_not_ready");
    return;
  }
  if (server.hasArg("plain") == false || server.arg("plain").length() > MAX_BODY) {
    sendError(400, "invalid_body");
    return;
  }
  StaticJsonDocument<2048> doc;
  if (deserializeJson(doc, server.arg("plain")) != DeserializationError::Ok) {
    sendError(400, "invalid_json");
    return;
  }
  String deviceId = doc["deviceId"] | "";
  String sessionId = doc["sessionId"] | "";
  String action = doc["action"] | "";
  String nonce = doc["nonce"] | "";
  String provided = doc["hmac"] | "";
  uint64_t sequence = doc["sequence"] | 0ULL;
  uint64_t expiresAt = doc["expiresAt"] | 0ULL;
  if (deviceId != NFC_DEVICE_ID || action != "scan" || sessionId.length() < 16 ||
      nonce.length() < 16 || sequence == 0 || sequence <= lastSequence ||
      expiresAt < (uint64_t)time(nullptr) || expiresAt > (uint64_t)time(nullptr) + 120 ||
      nonceUsed(nonce)) {
    sendError(401, "command_rejected");
    return;
  }
  String expected = hmacHex(commandCanonical(deviceId, sessionId, action, nonce,
                                              sequence, expiresAt));
  if (!constantTimeEqual(provided, expected)) {
    sendError(401, "command_rejected");
    return;
  }
  lastSequence = sequence;
  preferences.putULong64("lastSeq", lastSequence);
  rememberNonce(nonce);

  String uid = "";
  String status = "timeout";
  unsigned long started = millis();
  while (millis() - started < SCAN_TIMEOUT_MS) {
    uint8_t rawUid[10];
    uint8_t uidLength = 0;
    bool found = nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, rawUid, &uidLength, 150);
    if (found) {
      if (uidLength < 4 || uidLength > 10) {
        status = "invalid_read";
        break;
      }
      static const char HEX[] = "0123456789ABCDEF";
      for (uint8_t i = 0; i < uidLength; i++) {
        uid += HEX[rawUid[i] >> 4];
        uid += HEX[rawUid[i] & 15];
      }
      status = "ok";
      break;
    }
    delay(20);
  }
  sendSignedResponse(sessionId, nonce, sequence, status, uid); // nunca registra el UID
}

void setup() {
  Serial.begin(115200); // solo diagnóstico; no interviene en la comunicación
  preferences.begin("nfc-security", false);
  lastSequence = preferences.getULong64("lastSeq", 0);
  SPI.begin(PN532_SCK, PN532_MISO, PN532_MOSI, PN532_SS);
  nfc.begin();
  nfcReady = nfc.getFirmwareVersion() != 0;
  if (nfcReady) nfc.SAMConfig();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) delay(250);
  if (WiFi.status() == WL_CONNECTED) configureTime();
  server.on("/v1/nfc/scan", HTTP_POST, handleScan);
  server.begin();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(2000);
  }
  server.handleClient();
}
