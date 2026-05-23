import BoundingRect, { RectLike } from '../core/BoundingRect';
import { TextAlign, TextVerticalAlign, BuiltinTextPosition } from '../core/types';
import LRU from '../core/LRU';
import { DEFAULT_FONT, platformApi } from '../core/platform';

/**
 * @deprecated But keep for possible outside usage.
 *  Use `ensureFontMeasureInfo` + `measureWidth` instead.
 */
export function getWidth(text: string, font: string): number {
    return measureWidth(ensureFontMeasureInfo(font), text);
}

export interface FontMeasureInfo {
    font: string;
    strWidthCache: LRU<number>;
    // Key: char code, index: 0~127 (include 127)
    asciiWidthMap: number[] | null | undefined;
    asciiWidthMapTried: boolean;
    // Default width char width used both in non-ascii and line height.
    stWideCharWidth: number;
    // Default asc char width
    asciiCharWidth: number;
}

export function ensureFontMeasureInfo(font: string): FontMeasureInfo {
    if (!_fontMeasureInfoCache) {
        _fontMeasureInfoCache = new LRU(100);
    }
    font = font || DEFAULT_FONT;
    let measureInfo = _fontMeasureInfoCache.get(font);
    if (!measureInfo) {
        measureInfo = {
            font: font,
            strWidthCache: new LRU(500),
            asciiWidthMap: null, // Init lazily for performance.
            asciiWidthMapTried: false,
            // FIXME
            // Other languages?
            // FIXME
            // Consider proportional font?
            stWideCharWidth: platformApi.measureText('国', font).width,
            asciiCharWidth: platformApi.measureText('a', font).width,
        };
        _fontMeasureInfoCache.put(font, measureInfo);
    }
    return measureInfo;
}
let _fontMeasureInfoCache: LRU<FontMeasureInfo>;

/**
 * For getting more precise result in truncate.
 * non-monospace font vary in char width.
 * But if it is time consuming in some platform, return null/undefined.
 * @return Key: char code, index: 0~127 (include 127)
 */
function tryCreateASCIIWidthMap(font: string): FontMeasureInfo['asciiWidthMap'] {
    // PENDING: is it necessary? Re-examine it if bad case reported.
    if (_getASCIIWidthMapLongCount >= GET_ASCII_WIDTH_LONG_COUNT_MAX) {
        return;
    }
    font = font || DEFAULT_FONT;
    const asciiWidthMap = [];
    const start = +(new Date());
    // 0~31 and 127 may also have width, and may vary in some fonts.
    for (let code = 0; code <= 127; code++) {
        asciiWidthMap[code] = platformApi.measureText(String.fromCharCode(code), font).width;
    }
    const cost = +(new Date()) - start;
    if (cost > 16) {
        _getASCIIWidthMapLongCount = GET_ASCII_WIDTH_LONG_COUNT_MAX;
    }
    else if (cost > 2) {
        _getASCIIWidthMapLongCount++;
    }
    return asciiWidthMap;
}
let _getASCIIWidthMapLongCount: number = 0;
const GET_ASCII_WIDTH_LONG_COUNT_MAX = 5;

/**
 * Hot path, performance sensitive.
 */
export function measureCharWidth(fontMeasureInfo: FontMeasureInfo, charCode: number): number {
    if (!fontMeasureInfo.asciiWidthMapTried) {
        fontMeasureInfo.asciiWidthMap = tryCreateASCIIWidthMap(fontMeasureInfo.font);
        fontMeasureInfo.asciiWidthMapTried = true;
    }
    return (0 <= charCode && charCode <= 127)
        ? (fontMeasureInfo.asciiWidthMap != null
            ? fontMeasureInfo.asciiWidthMap[charCode]
            : fontMeasureInfo.asciiCharWidth
        )
        : fontMeasureInfo.stWideCharWidth;
}

export function measureWidth(fontMeasureInfo: FontMeasureInfo, text: string): number {
    const strWidthCache = fontMeasureInfo.strWidthCache;
    let width = strWidthCache.get(text);
    if (width == null) {
        width = platformApi.measureText(text, fontMeasureInfo.font).width;
        strWidthCache.put(text, width);
    }
    return width;
}


/**
 * @deprecated See `getBoundingRect`.
 * Get bounding rect for inner usage(TSpan)
 * Which not include text newline.
 */
export function innerGetBoundingRect(
    text: string,
    font: string,
    textAlign?: TextAlign,
    textBaseline?: TextVerticalAlign
): BoundingRect {
    const width = measureWidth(ensureFontMeasureInfo(font), text);
    const height = getLineHeight(font);

    const x = adjustTextX(0, width, textAlign);
    const y = adjustTextY(0, height, textBaseline);

    const rect = new BoundingRect(x, y, width, height);

    return rect;
}

/**
 * @deprecated Use `(new Text(...)).getBoundingRect()` or `(new TSpan(...)).getBoundingRect()` instead.
 *  This method behaves differently from `Text#getBoundingRect()` - e.g., it does not support the overflow
 *  strategy, and only has single line height even if multiple lines.
 *
 * Get bounding rect for outer usage. Compatitable with old implementation
 * Which includes text newline.
 */
export function getBoundingRect(
    text: string,
    font: string,
    textAlign?: TextAlign,
    textBaseline?: TextVerticalAlign
) {
    const textLines = ((text || '') + '').split('\n');
    const len = textLines.length;
    if (len === 1) {
        return innerGetBoundingRect(textLines[0], font, textAlign, textBaseline);
    }
    else {
        const uniondRect = new BoundingRect(0, 0, 0, 0);
        for (let i = 0; i < textLines.length; i++) {
            const rect = innerGetBoundingRect(textLines[i], font, textAlign, textBaseline);
            i === 0 ? uniondRect.copy(rect) : uniondRect.union(rect);
        }
        return uniondRect;
    }
}

export function adjustTextX(x: number, width: number, textAlign: TextAlign, inverse?: boolean): number {
    // TODO Right to left language
    if (textAlign === 'right') {
        !inverse ? (x -= width) : (x += width);
    }
    else if (textAlign === 'center') {
        !inverse ? (x -= width / 2) : (x += width / 2);
    }
    return x;
}

export function adjustTextY(y: number, height: number, verticalAlign: TextVerticalAlign, inverse?: boolean): number {
    if (verticalAlign === 'middle') {
        !inverse ? (y -= height / 2) : (y += height / 2);
    }
    else if (verticalAlign === 'bottom') {
        !inverse ? (y -= height) : (y += height);
    }
    return y;
}

export function getLineHeight(font?: string): number {
    // FIXME A rough approach.
    return ensureFontMeasureInfo(font).stWideCharWidth;
}

export function measureText(text: string, font?: string): {
    width: number
} {
    return platformApi.measureText(text, font);
}


export function parsePercent(value: number | string, maxValue: number): number {
    if (typeof value === 'string') {
        if (value.lastIndexOf('%') >= 0) {
            return parseFloat(value) / 100 * maxValue;
        }
        return parseFloat(value);
    }
    return value;
}

export interface TextPositionCalculationResult {
    x: number
    y: number
    align: TextAlign
    verticalAlign: TextVerticalAlign
}
/**
 * Follow same interface to `Displayable.prototype.calculateTextPosition`.
 * @public
 * @param out Prepared out object. If not input, auto created in the method.
 * @param style where `textPosition` and `textDistance` are visited.
 * @param rect {x, y, width, height} Rect of the host elment, according to which the text positioned.
 * @return The input `out`. Set: {x, y, textAlign, textVerticalAlign}
 */
export function calculateTextPosition(
    out: TextPositionCalculationResult,
    opts: {
        position?: BuiltinTextPosition | (number | string)[]
        distance?: number   // Default 5
        global?: boolean
    },
    rect: RectLike
): TextPositionCalculationResult {
    const textPosition = opts.position || 'inside';
    const distance = opts.distance != null ? opts.distance : 5;

    const height = rect.height;
    const width = rect.width;
    const halfHeight = height / 2;

    let x = rect.x;
    let y = rect.y;

    let textAlign: TextAlign = 'left';
    let textVerticalAlign: TextVerticalAlign = 'top';

    if (textPosition instanceof Array) {
        x += parsePercent(textPosition[0], rect.width);
        y += parsePercent(textPosition[1], rect.height);
        // Not use textAlign / textVerticalAlign
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

    out = out || {} as TextPositionCalculationResult;
    out.x = x;
    out.y = y;
    out.align = textAlign;
    out.verticalAlign = textVerticalAlign;

    return out;
}
