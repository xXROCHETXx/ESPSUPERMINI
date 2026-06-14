#include "epd_format.h"

#include <string.h>

namespace epd {
namespace {

uint16_t readLe16(const uint8_t* data) {
    return static_cast<uint16_t>(data[0]) |
           (static_cast<uint16_t>(data[1]) << 8);
}

uint32_t readLe32(const uint8_t* data) {
    return static_cast<uint32_t>(data[0]) |
           (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) |
           (static_cast<uint32_t>(data[3]) << 24);
}

bool planesOverlap(const uint8_t* black, const uint8_t* red) {
    for (size_t index = 0; index < planeSize; ++index) {
        const uint8_t blackActive = static_cast<uint8_t>(~black[index]);
        const uint8_t redActive = static_cast<uint8_t>(~red[index]);
        if ((blackActive & redActive) != 0) {
            return true;
        }
    }
    return false;
}

}  // namespace

uint32_t crc32(const uint8_t* data, size_t length) {
    uint32_t crc = 0xffffffffU;
    for (size_t index = 0; index < length; ++index) {
        crc ^= data[index];
        for (uint8_t bit = 0; bit < 8; ++bit) {
            const uint32_t mask = 0U - (crc & 1U);
            crc = (crc >> 1) ^ (0xedb88320U & mask);
        }
    }
    return ~crc;
}

bool parse(const uint8_t* data, size_t length, ImageView& image, ParseError& error) {
    error = ParseError::none;
    image = {};

    if (data == nullptr || length < headerSize) {
        error = ParseError::tooShort;
        return false;
    }
    if (memcmp(data, "EPD1", 4) != 0) {
        error = ParseError::badMagic;
        return false;
    }
    if (data[4] != 1) {
        error = ParseError::unsupportedVersion;
        return false;
    }
    if (data[6] != headerSize) {
        error = ParseError::badHeaderSize;
        return false;
    }

    const auto mode = static_cast<Mode>(data[5]);
    if (mode != Mode::bw && mode != Mode::bwr) {
        error = ParseError::badMode;
        return false;
    }
    if (readLe16(data + 8) != width || readLe16(data + 10) != height) {
        error = ParseError::badDimensions;
        return false;
    }
    if (readLe16(data + 12) != bytesPerRow) {
        error = ParseError::badStride;
        return false;
    }

    const uint16_t payloadLength = readLe16(data + 14);
    const uint16_t expectedLength = mode == Mode::bw ? planeSize : planeSize * 2;
    if (payloadLength != expectedLength) {
        error = ParseError::badLength;
        return false;
    }
    if (length != headerSize + payloadLength) {
        error = length < headerSize + payloadLength
                    ? ParseError::tooShort
                    : ParseError::trailingData;
        return false;
    }

    const uint8_t* payload = data + headerSize;
    const uint32_t expectedCrc = readLe32(data + 20);
    if (crc32(payload, payloadLength) != expectedCrc) {
        error = ParseError::badCrc;
        return false;
    }

    image.mode = mode;
    image.publishedAt = readLe32(data + 16);
    image.payloadCrc = expectedCrc;
    image.payloadLength = payloadLength;
    image.blackPlane = payload;
    image.redPlane = mode == Mode::bwr ? payload + planeSize : nullptr;

    if (image.redPlane != nullptr && planesOverlap(image.blackPlane, image.redPlane)) {
        image = {};
        error = ParseError::overlappingColours;
        return false;
    }
    return true;
}

const char* errorText(ParseError error) {
    switch (error) {
        case ParseError::none:
            return "ok";
        case ParseError::tooShort:
            return "archivo truncado";
        case ParseError::badMagic:
            return "magic EPD1 invalido";
        case ParseError::unsupportedVersion:
            return "version no soportada";
        case ParseError::badHeaderSize:
            return "cabecera invalida";
        case ParseError::badMode:
            return "modo invalido";
        case ParseError::badDimensions:
            return "dimensiones invalidas";
        case ParseError::badStride:
            return "bytes por fila invalidos";
        case ParseError::badLength:
            return "longitud de payload invalida";
        case ParseError::trailingData:
            return "datos sobrantes";
        case ParseError::badCrc:
            return "CRC32 invalido";
        case ParseError::overlappingColours:
            return "pixel negro y rojo simultaneo";
    }
    return "error desconocido";
}

}  // namespace epd

