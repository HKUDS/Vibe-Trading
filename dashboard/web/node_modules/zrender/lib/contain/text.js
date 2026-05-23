import BoundingRect from '../core/BoundingRect.js';
import LRU from '../core/LRU.js';
import { DEFAULT_FONT, platformApi } from '../core/platform.js';
export function getWidth(text, font) {
    return measureWidth(ensureFontMeasureInfo(font), text);
}
export function ensureFontMeasureInfo(font) {
    if (!_fontMeasureInfoCache) {
        _fontMeasureInfoCache = new LRU(100);
    }
    font = font || DEFAULT_FONT;
    var measureInfo = _fontMeasureInfoCache.get(font);
    if (!measureInfo) {
        measureInfo = {
            font: font,
            strWidthCache: new LRU(500),
            asciiWidthMap: null,
            asciiWidthMapTried: false,
            stWideCharWidth: platformApi.measureText('国', font).width,
            asciiCharWidth: platformApi.measureText('a', font).width
        };
        _fontMeasureInfoCache.put(font, measureInfo);
    }
    return measureInfo;
}
var _fontMeasureInfoCache;
function tryCreateASCIIWidthMap(font) {
    if (_getASCIIWidthMapLongCount >= GET_ASCII_WIDTH_LONG_COUNT_MAX) {
        return;
    }
    font = font || DEFAULT_FONT;
    var asciiWidthMap = [];
    var start = +(new Date());
    for (var code = 0; code <= 127; code++) {
        asciiWidthMap[code] = platformApi.measureText(String.fromCharCode(code), font).width;
    }
    var cost = +(new Date()) - start;
    if (cost > 16) {
        _getASCIIWidthMapLongCount = GET_ASCII_WIDTH_LONG_COUNT_MAX;
    }
    else if (cost > 2) {
        _getASCIIWidthMapLongCount++;
    }
    return asciiWidthMap;
}
var _getASCIIWidthMapLongCount = 0;
var GET_ASCII_WIDTH_LONG_COUNT_MAX = 5;
export function measureCharWidth(fontMeasureInfo, charCode) {
    if (!fontMeasureInfo.asciiWidthMapTried) {
        fontMeasureInfo.asciiWidthMap = tryCreateASCIIWidthMap(fontMeasureInfo.font);
        fontMeasureInfo.asciiWidthMapTried = true;
    }
    return (0 <= charCode && charCode <= 127)
        ? (fontMeasureInfo.asciiWidthMap != null
            ? fontMeasureInfo.asciiWidthMap[charCode]
            : fontMeasureInfo.asciiCharWidth)
        : fontMeasureInfo.stWideCharWidth;
}
export function measureWidth(fontMeasureInfo, text) {
    var strWidthCache = fontMeasureInfo.strWidthCache;
    var width = strWidthCache.get(text);
    if (width == null) {
        width = platformApi.measureText(text, fontMeasureInfo.font).width;
        strWidthCache.put(text, width);
    }
    return width;
}
export function innerGetBoundingRect(text, font, textAlign, textBaseline) {
    var width = measureWidth(ensureFontMeasureInfo(font), text);
    var height = getLineHeight(font);
    var x = adjustTextX(0, width, textAlign);
    var y = adjustTextY(0, height, textBaseline);
    var rect = new BoundingRect(x, y, width, height);
    return rect;
}
export function getBoundingRect(text, font, textAlign, textBaseline) {
    var textLines = ((text || '') + '').split('\n');
    var len = textLines.length;
    if (len === 1) {
        return innerGetBoundingRect(textLines[0], font, textAlign, textBaseline);
    }
    else {
        var uniondRect = new BoundingRect(0, 0, 0, 0);
        for (var i = 0; i < textLines.length; i++) {
            var rect = innerGetBoundingRect(textLines[i], font, textAlign, textBaseline);
            i === 0 ? uniondRect.copy(rect) : uniondRect.union(rect);
        }
        return uniondRect;
    }
}
export function adjustTextX(x, width, textAlign, inverse) {
    if (textAlign === 'right') {
        !inverse ? (x -= width) : (x += width);
    }
    else if (textAlign === 'center') {
        !inverse ? (x -= width / 2) : (x += width / 2);
    }
    return x;
}
export function adjustTextY(y, height, verticalAlign, inverse) {
    if (verticalAlign === 'middle') {
        !inverse ? (y -= height / 2) : (y += height / 2);
    }
    else if (verticalAlign === 'bottom') {
        !inverse ? (y -= height) : (y += height);
    }
    return y;
}
export function getLineHeight(font) {
    return ensureFontMeasureInfo(font).stWideCharWidth;
}
export function measureText(text, font) {
    return platformApi.measureText(text, font);
}
export function parsePercent(value, maxValue) {
    if (typeof value === 'string') {
        if (value.lastIndexOf('%') >= 0) {
            return parseFloat(value) / 100 * maxValue;
        }
        return parseFloat(value);
    }
    return value;
}
export function calculateTextPosition(out, opts, rect) {
    var textPosition = opts.position || 'inside';
    var distance = opts.distance != null ? opts.distance : 5;
    var height = rect.height;
    var width = rect.width;
    var halfHeight = height / 2;
    var x = rect.x;
    var y = rect.y;
    var textAlign = 'left';
    var textVerticalAlign = 'top';
    if (textPosition instanceof Array) {
        x += parsePercent(textPosition[0], rect.width);
        y += parsePercent(textPosition[1], rect.height);
        textAlign = null;
        textVerticalAlign = null;
    }
    else {
        switch (textPosition) {
            case 'left':
                x -= distance;
                y += halfHeight;
                textAlign = 'right';
                textVerticalAlign = 'middle';
                break;
            case 'right':
                x += distance + width;
                y += halfHeight;
                textVerticalAlign = 'middle';
                break;
            case 'top':
                x += width / 2;
                y -= distance;
                textAlign = 'center';
                textVerticalAlign = 'bottom';
                break;
            case 'bottom':
                x += width / 2;
                y += height + distance;
                textAlign = 'center';
                break;
            case 'inside':
                x += width / 2;
                y += halfHeight;
                textAlign = 'center';
                textVerticalAlign = 'middle';
                break;
            case 'insideLeft':
                x += distance;
                y += halfHeight;
                textVerticalAlign = 'middle';
                break;
            case 'insideRight':
                x += width - distance;
                y += halfHeight;
                textAlign = 'right';
                textVerticalAlign = 'middle';
                break;
            case 'insideTop':
                x += width / 2;
                y += distance;
                textAlign = 'center';
                break;
            case 'insideBottom':
                x += width / 2;
                y += height - distance;
                textAlign = 'center';
                textVerticalAlign = 'bottom';
                break;
            case 'insideTopLeft':
                x += distance;
                y += distance;
                break;
            case 'insideTopRight':
                x += width - distance;
                y += distance;
                textAlign = 'right';
                break;
            case 'insideBottomLeft':
                x += distance;
                y += height - distance;
                textVerticalAlign = 'bottom';
                break;
            case 'insideBottomRight':
                x += width - distance;
                y += height - distance;
                textAlign = 'right';
                textVerticalAlign = 'bottom';
                break;
        }
    }
    out = out || {};
    out.x = x;
    out.y = y;
    out.align = textAlign;
    out.verticalAlign = textVerticalAlign;
    return out;
}
