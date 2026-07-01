#ifdef EPD_SERVER_TEST

#include <Arduino.h>
#include <HTTPClient.h>
#include <PDLS_EXT3_Basic_Global.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <string.h>
#include <vector>

#include "epd_format.h"
#include "project_config.h"

namespace {

constexpr uint8_t pinMosi = 23;
constexpr uint8_t pinSck = 18;
constexpr uint8_t pinBusy = 27;
constexpr uint8_t pinDc = 26;
constexpr uint8_t pinReset = 25;
constexpr uint8_t pinPanelCs = 32;
constexpr uint32_t pollIntervalMs = 20000;
constexpr uint32_t heartbeatIntervalMs = 5000;

bool haveLastImage = false;
uint32_t lastPublishedAt = 0;
uint32_t lastPayloadCrc = 0;
uint16_t lastPayloadLength = 0;
uint32_t nextPollAt = 0;
uint32_t nextHeartbeatAt = 0;

const pins_t displayPins = {
    pinBusy,
    pinDc,
    pinReset,
    NOT_CONNECTED,
    pinPanelCs,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
};

bool credentialsConfigured() {
    return strcmp(WIFI_SSID, "YOUR_WIFI_NAME") != 0 &&
           strlen(WIFI_SSID) > 0 &&
           strlen(EPD_IMAGE_URL) > 0;
}

void printPins() {
    Serial.println("E-paper server fetch test");
    Serial.printf("MOSI=%u SCK=%u BUSY=%u DC=%u RST=%u CS=%u\n",
                  pinMosi,
                  pinSck,
                  pinBusy,
                  pinDc,
                  pinReset,
                  pinPanelCs);
}

bool timeReached(uint32_t targetMs) {
    return static_cast<int32_t>(millis() - targetMs) >= 0;
}

void scheduleNextPoll() {
    nextPollAt = millis() + pollIntervalMs;
}

String cacheBustedImageUrl() {
    String url(EPD_IMAGE_URL);
    url += url.indexOf('?') >= 0 ? '&' : '?';
    url += "esp_probe=";
    url += String(millis());
    return url;
}

void printHeartbeat() {
    if (!timeReached(nextHeartbeatAt)) {
        return;
    }

    const uint32_t now = millis();
    const uint32_t remainingMs =
        timeReached(nextPollAt) ? 0 : static_cast<uint32_t>(nextPollAt - now);
    Serial.printf("Loop alive. Next server check in %lu s.\n",
                  static_cast<unsigned long>((remainingMs + 999) / 1000));
    nextHeartbeatAt = millis() + heartbeatIntervalMs;
}

bool connectWiFi() {
    Serial.printf("Connecting WiFi SSID '%s'", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    const uint32_t startedAt = millis();
    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < config::wifiTimeoutMs) {
        Serial.print(".");
        delay(250);
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi timeout");
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        return false;
    }

    Serial.print("WiFi connected, IP ");
    Serial.println(WiFi.localIP());
    return true;
}

bool downloadImage(std::vector<uint8_t>& body) {
    WiFiClientSecure client;
    client.setInsecure();

    HTTPClient http;
    http.setConnectTimeout(config::downloadTimeoutMs);
    http.setTimeout(config::downloadTimeoutMs);
    http.useHTTP10(true);

    const String url = cacheBustedImageUrl();
    Serial.print("GET ");
    Serial.println(url);
    if (!http.begin(client, url)) {
        Serial.println("HTTP begin failed");
        return false;
    }

    http.addHeader("Cache-Control", "no-cache");
    http.addHeader("Pragma", "no-cache");

    const int code = http.GET();
    Serial.printf("HTTP status: %d\n", code);
    if (code != HTTP_CODE_OK) {
        http.end();
        return false;
    }

    const int length = http.getSize();
    Serial.printf("HTTP length: %d\n", length);
    if (length <= 0 || length > static_cast<int>(epd::maxFileSize)) {
        Serial.println("Unexpected file size");
        http.end();
        return false;
    }

    WiFiClient* stream = http.getStreamPtr();
    body.clear();
    body.reserve(length);

    uint8_t buffer[256];
    uint32_t lastProgress = millis();
    while (http.connected() && body.size() < static_cast<size_t>(length)) {
        const size_t available = stream->available();
        if (available == 0) {
            if (millis() - lastProgress > config::downloadTimeoutMs) {
                Serial.println("Download stalled");
                http.end();
                return false;
            }
            delay(10);
            continue;
        }

        const size_t wanted =
            min(sizeof(buffer), static_cast<size_t>(length) - body.size());
        const int read = stream->readBytes(buffer, min(available, wanted));
        if (read > 0) {
            body.insert(body.end(), buffer, buffer + read);
            lastProgress = millis();
        }
    }

    http.end();
    Serial.printf("Downloaded %u bytes\n", static_cast<unsigned>(body.size()));
    return body.size() == static_cast<size_t>(length);
}

bool planePixelIsActive(const uint8_t* plane, uint16_t x, uint16_t y) {
    const size_t index = static_cast<size_t>(y) * epd::bytesPerRow + x / 8;
    const uint8_t mask = static_cast<uint8_t>(1U << (7U - (x % 8U)));
    return (plane[index] & mask) == 0;
}

bool drawImage(const epd::ImageView& image) {
    Serial.println("Initialising display");

    // ESP32-WROOM-32 VSPI defaults are MOSI=23 and SCK=18. This explicit call
    // documents the wiring used for this smoke test.
    SPI.begin(pinSck, -1, pinMosi, pinPanelCs);

    Screen_EPD_EXT3 screen(eScreen_EPD_417_JS_0D, displayPins);
    screen.begin();
    screen.setOrientation(config::displayOrientation);

    Serial.printf("Library display size: %ux%u\n",
                  screen.screenSizeX(),
                  screen.screenSizeY());
    if (screen.screenSizeX() != epd::width ||
        screen.screenSizeY() != epd::height) {
        Serial.println("Unexpected display size");
        return false;
    }

    screen.setPenSolid(true);
    screen.clear(myColours.white);
    for (uint16_t y = 0; y < epd::height; ++y) {
        for (uint16_t x = 0; x < epd::width; ++x) {
            if (planePixelIsActive(image.blackPlane, x, y)) {
                screen.point(x, y, myColours.black);
            } else if (image.redPlane != nullptr &&
                       planePixelIsActive(image.redPlane, x, y)) {
                screen.point(x, y, myColours.red);
            }
        }
    }

    Serial.println("Flushing display. This can take several seconds.");
    const uint32_t startedAt = millis();
    screen.flush();
    Serial.printf("Flush finished in %lu ms\n",
                  static_cast<unsigned long>(millis() - startedAt));

    digitalWrite(pinPanelCs, HIGH);
    digitalWrite(pinDc, LOW);
    digitalWrite(pinReset, LOW);
    SPI.end();
    return true;
}

bool imageChanged(const epd::ImageView& image) {
    return !haveLastImage ||
           image.publishedAt != lastPublishedAt ||
           image.payloadCrc != lastPayloadCrc ||
           image.payloadLength != lastPayloadLength;
}

void rememberImage(const epd::ImageView& image) {
    haveLastImage = true;
    lastPublishedAt = image.publishedAt;
    lastPayloadCrc = image.payloadCrc;
    lastPayloadLength = image.payloadLength;
}

void runServerCheck(bool forceDraw) {
    if (!credentialsConfigured()) {
        Serial.println("Missing include/secrets.h WiFi credentials.");
        Serial.println("Copy include/secrets.example.h to include/secrets.h first.");
        return;
    }

    if (!connectWiFi()) {
        return;
    }

    std::vector<uint8_t> body;
    const bool downloaded = downloadImage(body);
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    Serial.println("WiFi off");

    if (!downloaded) {
        Serial.println("Download failed");
        return;
    }

    epd::ImageView image;
    epd::ParseError error;
    if (!epd::parse(body.data(), body.size(), image, error)) {
        Serial.printf("EPD parse failed: %s\n", epd::errorText(error));
        return;
    }

    Serial.printf("EPD parsed: mode=%s crc=0x%08lx payload=%u\n",
                  image.mode == epd::Mode::bwr ? "BWR" : "BW",
                  static_cast<unsigned long>(image.payloadCrc),
                  image.payloadLength);
    Serial.printf("Published at: %lu\n",
                  static_cast<unsigned long>(image.publishedAt));

    if (!forceDraw && !imageChanged(image)) {
        Serial.println("Image unchanged, skipping display refresh.");
        return;
    }

    if (!drawImage(image)) {
        Serial.println("Display update failed");
        return;
    }

    rememberImage(image);
    Serial.println("Server fetch e-paper test complete.");
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(1500);
    printPins();
    Serial.printf("Polling server every %lu seconds.\n",
                  static_cast<unsigned long>(pollIntervalMs / 1000));
    runServerCheck(true);
    scheduleNextPoll();
    nextHeartbeatAt = millis() + heartbeatIntervalMs;
}

void loop() {
    if (timeReached(nextPollAt)) {
        Serial.println("Checking server for a new image...");
        runServerCheck(false);
        scheduleNextPoll();
    }
    printHeartbeat();
    delay(250);
}

#endif  // EPD_SERVER_TEST
