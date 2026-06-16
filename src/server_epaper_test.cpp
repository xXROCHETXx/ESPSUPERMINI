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

constexpr uint8_t pinMosi = 11;
constexpr uint8_t pinSck = 12;
constexpr uint8_t pinBusy = 4;
constexpr uint8_t pinDc = 5;
constexpr uint8_t pinReset = 6;
constexpr uint8_t pinPanelCs = 8;

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

    Serial.print("GET ");
    Serial.println(EPD_IMAGE_URL);
    if (!http.begin(client, EPD_IMAGE_URL)) {
        Serial.println("HTTP begin failed");
        return false;
    }

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

    // Arduino ESP32-S3 defaults are normally MOSI=11 and SCK=12. This explicit
    // call documents the wiring used for this smoke test.
    SPI.begin(pinSck, -1, pinMosi, pinPanelCs);

    Screen_EPD_EXT3 screen(eScreen_EPD_266_JS_0C, displayPins);
    screen.begin();
    screen.setOrientation(ORIENTATION_LANDSCAPE);

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

void runTestOnce() {
    printPins();
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

    if (!drawImage(image)) {
        Serial.println("Display update failed");
        return;
    }

    Serial.println("Server fetch e-paper test complete.");
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(1500);
    runTestOnce();
}

void loop() {
    delay(1000);
}

#endif  // EPD_SERVER_TEST
