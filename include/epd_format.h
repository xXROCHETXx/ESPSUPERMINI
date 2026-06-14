#pragma once

#include <stddef.h>
#include <stdint.h>

namespace epd {

constexpr size_t headerSize = 24;
constexpr uint16_t width = 296;
constexpr uint16_t height = 152;
constexpr uint16_t bytesPerRow = 37;
constexpr uint16_t planeSize = bytesPerRow * height;
constexpr size_t maxFileSize = headerSize + planeSize * 2;

enum class Mode : uint8_t {
    bw = 1,
    bwr = 2,
};

enum class ParseError : uint8_t {
    none,
    tooShort,
    badMagic,
    unsupportedVersion,
    badHeaderSize,
    badMode,
    badDimensions,
    badStride,
    badLength,
    trailingData,
    badCrc,
    overlappingColours,
};

struct ImageView {
    Mode mode = Mode::bw;
    uint32_t publishedAt = 0;
    uint32_t payloadCrc = 0;
    const uint8_t* blackPlane = nullptr;
    const uint8_t* redPlane = nullptr;
    uint16_t payloadLength = 0;
};

uint32_t crc32(const uint8_t* data, size_t length);
bool parse(const uint8_t* data, size_t length, ImageView& image, ParseError& error);
const char* errorText(ParseError error);

}  // namespace epd

