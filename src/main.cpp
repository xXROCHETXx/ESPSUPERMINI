#include <Arduino.h>
#include <HTTPClient.h>
#include <PDLS_EXT3_Basic_Global.h>
#include <Preferences.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <sys/time.h>
#include <time.h>

#include <algorithm>
#include <vector>

#include "epd_format.h"
#include "project_config.h"

namespace {

enum class FetchStatus {
    updated,
    notModified,
    failed,
};

struct FetchResult {
    FetchStatus status = FetchStatus::failed;
    std::vector<uint8_t> body;
    String etag;
    String date;
};

struct CycleMetrics {
    uint32_t startedAt = 0;
    uint32_t wifiMs = 0;
    uint32_t networkMs = 0;
    uint32_t displayMs = 0;
};

const pins_t displayPins = {
    config::pinBusy,
    config::pinDc,
    config::pinReset,
    NOT_CONNECTED,
    config::pinPanelCs,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
    NOT_CONNECTED,
};

Preferences preferences;
CycleMetrics metrics;
bool watchdogInitialisedHere = false;

void enterDeepSleep(uint64_t seconds);

const char* resetReasonText(esp_reset_reason_t reason) {
    switch (reason) {
        case ESP_RST_POWERON:
            return "power-on";
        case ESP_RST_EXT:
            return "external reset";
        case ESP_RST_SW:
            return "software reset";
        case ESP_RST_PANIC:
            return "panic";
        case ESP_RST_INT_WDT:
            return "interrupt watchdog";
        case ESP_RST_TASK_WDT:
            return "task watchdog";
        case ESP_RST_WDT:
            return "other watchdog";
        case ESP_RST_DEEPSLEEP:
            return "deep sleep wake";
        case ESP_RST_BROWNOUT:
            return "brownout";
        case ESP_RST_SDIO:
            return "sdio";
        default:
            return "unknown";
    }
}

bool credentialsConfigured() {
    return strcmp(WIFI_SSID, "YOUR_WIFI_NAME") != 0 &&
           strstr(EPD_IMAGE_URL, "YOUR_USER.github.io") == nullptr;
}

bool resetWasWatchdog() {
    const esp_reset_reason_t reason = esp_reset_reason();
    return reason == ESP_RST_TASK_WDT || reason == ESP_RST_INT_WDT ||
           reason == ESP_RST_WDT;
}

bool connectWifi() {
    const uint32_t startedAt = millis();
    WiFi.persistent(false);
    WiFi.setAutoReconnect(false);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < config::wifiTimeoutMs) {
        delay(50);
    }
    metrics.wifiMs = millis() - startedAt;
    if (WiFi.status() != WL_CONNECTED) {
        Serial.printf("WiFi timeout after %lu ms\n",
                      static_cast<unsigned long>(metrics.wifiMs));
        return false;
    }

    Serial.printf(
        "WiFi connected in %lu ms, RSSI %d dBm, IP %s\n",
        static_cast<unsigned long>(metrics.wifiMs),
        WiFi.RSSI(),
        WiFi.localIP().toString().c_str());
    return true;
}

void stopWifi() {
    WiFi.disconnect(true, true);
    WiFi.mode(WIFI_OFF);
    delay(10);
}

bool readHttpBody(HTTPClient& http, std::vector<uint8_t>& body) {
    const int contentLength = http.getSize();
    if (contentLength < static_cast<int>(epd::headerSize) ||
        contentLength > static_cast<int>(epd::maxFileSize)) {
        Serial.printf("Invalid Content-Length: %d\n", contentLength);
        return false;
    }

    body.resize(static_cast<size_t>(contentLength));
    WiFiClient* stream = http.getStreamPtr();
    size_t offset = 0;
    const uint32_t deadline = millis() + config::downloadTimeoutMs;

    while (offset < body.size() &&
           static_cast<int32_t>(deadline - millis()) > 0) {
        const int available = stream->available();
        if (available > 0) {
            const size_t wanted =
                std::min(static_cast<size_t>(available), body.size() - offset);
            const int received = stream->read(body.data() + offset, wanted);
            if (received > 0) {
                offset += static_cast<size_t>(received);
            }
            continue;
        }
        if (!http.connected()) {
            break;
        }
        delay(5);
    }

    if (offset != body.size()) {
        Serial.printf("Truncated download: %u/%u bytes\n",
                      static_cast<unsigned>(offset),
                      static_cast<unsigned>(body.size()));
        body.clear();
        return false;
    }
    return true;
}

FetchResult fetchImage(const String& previousEtag) {
    FetchResult result;
    WiFiClientSecure client;
    client.setInsecure();

    HTTPClient http;
    http.setConnectTimeout(5000);
    http.setTimeout(config::downloadTimeoutMs);
    http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
    const char* responseHeaders[] = {"Date", "ETag"};
    http.collectHeaders(responseHeaders, 2);

    if (!http.begin(client, EPD_IMAGE_URL)) {
        Serial.println("Could not initialise HTTP client");
        return result;
    }
    if (!previousEtag.isEmpty()) {
        http.addHeader("If-None-Match", previousEtag);
    }

    const uint32_t startedAt = millis();
    const int statusCode = http.GET();
    metrics.networkMs = millis() - startedAt;
    result.date = http.header("Date");
    result.etag = http.header("ETag");

    if (statusCode == HTTP_CODE_NOT_MODIFIED) {
        result.status = FetchStatus::notModified;
    } else if (statusCode == HTTP_CODE_OK && readHttpBody(http, result.body)) {
        result.status = FetchStatus::updated;
    } else {
        Serial.printf("HTTP request failed with status %d (%s)\n",
                      statusCode,
                      http.errorToString(statusCode).c_str());
    }
    http.end();
    return result;
}

bool setClockFromHttpDate(const String& date) {
    if (date.isEmpty()) {
        return false;
    }

    struct tm parsed = {};
    char* end = strptime(
        date.c_str(), "%a, %d %b %Y %H:%M:%S GMT", &parsed);
    if (end == nullptr) {
        Serial.printf("Could not parse HTTP Date: %s\n", date.c_str());
        return false;
    }

    setenv("TZ", "UTC0", 1);
    tzset();
    parsed.tm_isdst = 0;
    const time_t utc = mktime(&parsed);
    if (utc <= 0) {
        return false;
    }

    const timeval now = {utc, 0};
    settimeofday(&now, nullptr);
    setenv("TZ", config::chileTimezone, 1);
    tzset();
    return true;
}

uint64_t secondsUntilNextMidnight(bool clockWasSet) {
    if (!clockWasSet) {
        return config::fallbackSleepSeconds;
    }

    const time_t now = time(nullptr);
    struct tm local = {};
    localtime_r(&now, &local);
    local.tm_hour = 0;
    local.tm_min = 0;
    local.tm_sec = 0;
    local.tm_mday += 1;
    local.tm_isdst = -1;
    time_t nextMidnight = mktime(&local);
    int64_t sleepSeconds = static_cast<int64_t>(nextMidnight - now);

    if (sleepSeconds < static_cast<int64_t>(config::minimumSleepSeconds)) {
        localtime_r(&nextMidnight, &local);
        local.tm_mday += 1;
        local.tm_isdst = -1;
        nextMidnight = mktime(&local);
        sleepSeconds = static_cast<int64_t>(nextMidnight - now);
    }
    if (sleepSeconds <= 0 ||
        sleepSeconds > static_cast<int64_t>(config::fallbackSleepSeconds + 7200)) {
        return config::fallbackSleepSeconds;
    }
    return static_cast<uint64_t>(sleepSeconds);
}

void startDisplayWatchdog() {
    const esp_err_t initialised =
        esp_task_wdt_init(config::displayWatchdogSeconds, true);
    watchdogInitialisedHere = initialised == ESP_OK;
    if (initialised != ESP_OK && initialised != ESP_ERR_INVALID_STATE) {
        Serial.printf("Could not initialise task watchdog: %d\n", initialised);
        return;
    }
    const esp_err_t added = esp_task_wdt_add(nullptr);
    if (added != ESP_OK && added != ESP_ERR_INVALID_STATE) {
        Serial.printf("Could not attach task watchdog: %d\n", added);
    }
}

void stopDisplayWatchdog() {
    esp_task_wdt_delete(nullptr);
    if (watchdogInitialisedHere) {
        esp_task_wdt_deinit();
        watchdogInitialisedHere = false;
    }
}

bool planePixelIsActive(const uint8_t* plane, uint16_t x, uint16_t y) {
    const size_t index = static_cast<size_t>(y) * epd::bytesPerRow + x / 8;
    const uint8_t mask = static_cast<uint8_t>(1U << (7U - (x % 8U)));
    return (plane[index] & mask) == 0;
}

bool updateDisplay(const epd::ImageView& image) {
    const uint32_t startedAt = millis();
    SPI.begin(config::pinSck, -1, config::pinMosi, config::pinPanelCs);

    Screen_EPD_EXT3 screen(eScreen_EPD_417_JS_0D, displayPins);
    screen.begin();
    screen.setOrientation(config::displayOrientation);

    if (screen.screenSizeX() != epd::width ||
        screen.screenSizeY() != epd::height) {
        Serial.printf("Unexpected display size: %ux%u\n",
                      screen.screenSizeX(),
                      screen.screenSizeY());
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

    startDisplayWatchdog();
    Serial.println("Starting e-ink flush");
    screen.flush();
    stopDisplayWatchdog();
    metrics.displayMs = millis() - startedAt;
    Serial.printf("Display updated in %lu ms\n",
                  static_cast<unsigned long>(metrics.displayMs));

    digitalWrite(config::pinPanelCs, HIGH);
    digitalWrite(config::pinDc, LOW);
    digitalWrite(config::pinReset, LOW);
    SPI.end();
    return true;
}

void saveAppliedState(uint32_t crc, const String& etag) {
    preferences.putUInt("crc", crc);
    if (!etag.isEmpty()) {
        preferences.putString("etag", etag);
    } else {
        preferences.remove("etag");
    }
}

void saveVerifiedEtag(const String& etag) {
    if (!etag.isEmpty()) {
        preferences.putString("etag", etag);
    } else {
        preferences.remove("etag");
    }
}

void printEnergyEstimate(uint64_t sleepSeconds) {
    const uint32_t totalMs = millis() - metrics.startedAt;
    const uint32_t nonDisplayMs =
        totalMs > metrics.displayMs ? totalMs - metrics.displayMs : totalMs;
    const float awakeMah =
        config::estimatedAwakeMa * nonDisplayMs / 3600000.0f +
        config::estimatedDisplayMa * metrics.displayMs / 3600000.0f;
    const float sleepMah =
        config::estimatedDeepSleepMa * sleepSeconds / 3600.0f;
    const float dailyMah = awakeMah + sleepMah;
    const float estimatedDays =
        dailyMah > 0.0f ? config::batteryCapacityMah / dailyMah : 0.0f;

    Serial.printf(
        "Cycle: total=%lu ms wifi=%lu ms network=%lu ms display=%lu ms\n",
        static_cast<unsigned long>(totalMs),
        static_cast<unsigned long>(metrics.wifiMs),
        static_cast<unsigned long>(metrics.networkMs),
        static_cast<unsigned long>(metrics.displayMs));
    Serial.printf(
        "Estimated energy: awake=%.4f mAh sleep=%.4f mAh total=%.4f mAh, "
        "battery=%.0f days\n",
        awakeMah,
        sleepMah,
        dailyMah,
        estimatedDays);
}

void enterDeepSleep(uint64_t seconds) {
    stopWifi();
    preferences.end();
    printEnergyEstimate(seconds);
    Serial.printf("Deep sleep for %llu seconds\n",
                  static_cast<unsigned long long>(seconds));
    Serial.flush();
    if (config::debugStayAwakeInsteadOfSleep) {
        Serial.println("DEBUG: deep sleep skipped; staying awake for serial diagnostics.");
        Serial.flush();
        while (true) {
            delay(1000);
        }
    }
    esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
    esp_deep_sleep_start();
}

}  // namespace

void setup() {
    metrics.startedAt = millis();
    Serial.begin(115200);
    delay(2000);
    Serial.println("\nESP32-S3 e-paper daily cycle");
    const esp_reset_reason_t reason = esp_reset_reason();
    Serial.printf("Reset reason: %d (%s)\n", reason, resetReasonText(reason));
    Serial.printf("Flash chip: %lu bytes\n",
                  static_cast<unsigned long>(ESP.getFlashChipSize()));
    Serial.printf("PSRAM: %lu bytes\n",
                  static_cast<unsigned long>(ESP.getPsramSize()));
    Serial.printf("Firmware expects display %ux%u, row=%u bytes\n",
                  epd::width,
                  epd::height,
                  epd::bytesPerRow);

    setenv("TZ", config::chileTimezone, 1);
    tzset();
    preferences.begin("epaper", false);

    if (resetWasWatchdog()) {
        Serial.println("Previous cycle ended by watchdog; sleeping to avoid a reset loop");
        enterDeepSleep(config::fallbackSleepSeconds);
    }
    if (!credentialsConfigured()) {
        Serial.println("WiFi or EPD_IMAGE_URL is not configured");
        enterDeepSleep(config::fallbackSleepSeconds);
    }
    if (!connectWifi()) {
        enterDeepSleep(config::fallbackSleepSeconds);
    }

    const String previousEtag = preferences.getString("etag", "");
    const uint32_t appliedCrc = preferences.getUInt("crc", 0);
    FetchResult result = fetchImage(previousEtag);
    const bool clockWasSet = setClockFromHttpDate(result.date);
    const uint64_t sleepSeconds = secondsUntilNextMidnight(clockWasSet);

    if (result.status == FetchStatus::notModified) {
        Serial.println("Remote image has not changed");
        enterDeepSleep(sleepSeconds);
    }
    if (result.status != FetchStatus::updated) {
        Serial.println("No valid update was downloaded");
        enterDeepSleep(sleepSeconds);
    }

    epd::ImageView image;
    epd::ParseError parseError;
    if (!epd::parse(result.body.data(), result.body.size(), image, parseError)) {
        Serial.printf("Rejected EPD file: %s\n", epd::errorText(parseError));
        enterDeepSleep(sleepSeconds);
    }
    if (image.payloadCrc == appliedCrc) {
        Serial.println("Downloaded image is identical to the applied image");
        saveVerifiedEtag(result.etag);
        enterDeepSleep(sleepSeconds);
    }

    stopWifi();
    if (updateDisplay(image)) {
        saveAppliedState(image.payloadCrc, result.etag);
    } else {
        Serial.println("Display update failed; previous state remains pending");
    }
    enterDeepSleep(sleepSeconds);
}

void loop() {
    enterDeepSleep(config::fallbackSleepSeconds);
}
