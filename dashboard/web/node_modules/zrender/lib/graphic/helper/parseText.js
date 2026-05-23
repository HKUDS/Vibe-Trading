import * as imageHelper from '../helper/image.js';
import { extend, retrieve2, retrieve3, reduce, } from '../../core/util.js';
import { adjustTextX, adjustTextY, ensureFontMeasureInfo, getLineHeight, measureCharWidth, measureWidth, parsePercent, } from '../../contain/text.js';
import BoundingRect from '../../core/BoundingRect.js';
var STYLE_REG = /\{([a-zA-Z0-9_]+)\|([^}]*)\}/g;
export function truncateText(text, containerWidth, font, ellipsis, options) {
    var out = {};
    truncateText2(out, text, containerWidth, font, ellipsis, options);
    return out.text;
}
function truncateText2(out, text, containerWidth, font, ellipsis, options) {
    if (!containerWidth) {
        out.text = '';
        out.isTruncated = false;
        return;
    }
    var textLines = (text + '').split('\n');
    options = prepareTruncateOptions(containerWidth, font, ellipsis, options);
    var isTruncated = false;
    var truncateOut = {};
    for (var i = 0, len = textLines.length; i < len; i++) {
        truncateSingleLine(truncateOut, textLines[i], options);
        textLines[i] = truncateOut.textLine;
        isTruncated = isTruncated || truncateOut.isTruncated;
    }
    out.text = textLines.join('\n');
    out.isTruncated = isTruncated;
}
function prepareTruncateOptions(containerWidth, font, ellipsis, options) {
    options = options || {};
    var preparedOpts = extend({}, options);
    ellipsis = retrieve2(ellipsis, '...');
    preparedOpts.maxIterations = retrieve2(options.maxIterations, 2);
    var minChar = preparedOpts.minChar = retrieve2(options.minChar, 0);
    var fontMeasureInfo = preparedOpts.fontMeasureInfo = ensureFontMeasureInfo(font);
    var ascCharWidth = fontMeasureInfo.asciiCharWidth;
    preparedOpts.placeholder = retrieve2(options.placeholder, '');
    var contentWidth = containerWidth = Math.max(0, containerWidth - 1);
    for (var i = 0; i < minChar && contentWidth >= ascCharWidth; i++) {
        contentWidth -= ascCharWidth;
    }
    var ellipsisWidth = measureWidth(fontMeasureInfo, ellipsis);
    if (ellipsisWidth > contentWidth) {
        ellipsis = '';
        ellipsisWidth = 0;
    }
    contentWidth = containerWidth - ellipsisWidth;
    preparedOpts.ellipsis = ellipsis;
    preparedOpts.ellipsisWidth = ellipsisWidth;
    preparedOpts.contentWidth = contentWidth;
    preparedOpts.containerWidth = containerWidth;
    return preparedOpts;
}
function truncateSingleLine(out, textLine, options) {
    var containerWidth = options.containerWidth;
    var contentWidth = options.contentWidth;
    var fontMeasureInfo = options.fontMeasureInfo;
    if (!containerWidth) {
        out.textLine = '';
        out.isTruncated = false;
        return;
    }
    var lineWidth = measureWidth(fontMeasureInfo, textLine);
    if (lineWidth <= containerWidth) {
        out.textLine = textLine;
        out.isTruncated = false;
        return;
    }
    for (var j = 0;; j++) {
        if (lineWidth <= contentWidth || j >= options.maxIterations) {
            textLine += options.ellipsis;
            break;
        }
        var subLength = j === 0
            ? estimateLength(textLine, contentWidth, fontMeasureInfo)
            : lineWidth > 0
                ? Math.floor(textLine.length * contentWidth / lineWidth)
                : 0;
        textLine = textLine.substr(0, subLength);
        lineWidth = measureWidth(fontMeasureInfo, textLine);
    }
    if (textLine === '') {
        textLine = options.placeholder;
    }
    out.textLine = textLine;
    out.isTruncated = true;
}
function estimateLength(text, contentWidth, fontMeasureInfo) {
    var width = 0;
    var i = 0;
    for (var len = text.length; i < len && width < contentWidth; i++) {
        width += measureCharWidth(fontMeasureInfo, text.charCodeAt(i));
    }
    return i;
}
export function parsePlainText(rawText, style, defaultOuterWidth, defaultOuterHeight) {
    var text = formatText(rawText);
    var overflow = style.overflow;
    var padding = style.padding;
    var paddingH = padding ? padding[1] + padding[3] : 0;
    var paddingV = padding ? padding[0] + padding[2] : 0;
    var font = style.font;
    var truncate = overflow === 'truncate';
    var calculatedLineHeight = getLineHeight(font);
    var lineHeight = retrieve2(style.lineHeight, calculatedLineHeight);
    var truncateLineOverflow = style.lineOverflow === 'truncate';
    var isTruncated = false;
    var width = style.width;
    if (width == null && defaultOuterWidth != null) {
        width = defaultOuterWidth - paddingH;
    }
    var height = style.height;
    if (height == null && defaultOuterHeight != null) {
        height = defaultOuterHeight - paddingV;
    }
    var lines;
    if (width != null && (overflow === 'break' || overflow === 'breakAll')) {
        lines = text ? wrapText(text, style.font, width, overflow === 'breakAll', 0).lines : [];
    }
    else {
        lines = text ? text.split('\n') : [];
    }
    var contentHeight = lines.length * lineHeight;
    if (height == null) {
        height = contentHeight;
    }
    if (contentHeight > height && truncateLineOverflow) {
        var lineCount = Math.floor(height / lineHeight);
        isTruncated = isTruncated || (lines.length > lineCount);
        lines = lines.slice(0, lineCount);
        contentHeight = lines.length * lineHeight;
    }
    if (text && truncate && width != null) {
        var options = prepareTruncateOptions(width, font, style.ellipsis, {
            minChar: style.truncateMinChar,
            placeholder: style.placeholder
        });
        var singleOut = {};
        for (var i = 0; i < lines.length; i++) {
            truncateSingleLine(singleOut, lines[i], options);
            lines[i] = singleOut.textLine;
            isTruncated = isTruncated || singleOut.isTruncated;
        }
    }
    var outerHeight = height;
    var contentWidth = 0;
    var fontMeasureInfo = ensureFontMeasureInfo(font);
    for (var i = 0; i < lines.length; i++) {
        contentWidth = Math.max(measureWidth(fontMeasureInfo, lines[i]), contentWidth);
    }
    if (width == null) {
        width = contentWidth;
    }
    var outerWidth = width;
    outerHeight += paddingV;
    outerWidth += paddingH;
    return {
        lines: lines,
        height: height,
        outerWidth: outerWidth,
        outerHeight: outerHeight,
        lineHeight: lineHeight,
        calculatedLineHeight: calculatedLineHeight,
        contentWidth: contentWidth,
        contentHeight: contentHeight,
        width: width,
        isTruncated: isTruncated
    };
}
var RichTextToken = (function () {
    function RichTextToken() {
    }
    return RichTextToken;
}());
var RichTextLine = (function () {
    function RichTextLine(tokens) {
        this.tokens = [];
        if (tokens) {
            this.tokens = tokens;
        }
    }
    return RichTextLine;
}());
var RichTextContentBlock = (function () {
    function RichTextContentBlock() {
        this.width = 0;
        this.height = 0;
        this.contentWidth = 0;
        this.contentHeight = 0;
        this.outerWidth = 0;
        this.outerHeight = 0;
        this.lines = [];
        this.isTruncated = false;
    }
    return RichTextContentBlock;
}());
export { RichTextContentBlock };
export function parseRichText(rawText, style, defaultOuterWidth, defaultOuterHeight, topTextAlign) {
    var contentBlock = new RichTextContentBlock();
    var text = formatText(rawText);
    if (!text) {
        return contentBlock;
    }
    var stlPadding = style.padding;
    var stlPaddingH = stlPadding ? stlPadding[1] + stlPadding[3] : 0;
    var stlPaddingV = stlPadding ? stlPadding[0] + stlPadding[2] : 0;
    var topWidth = style.width;
    if (topWidth == null && defaultOuterWidth != null) {
        topWidth = defaultOuterWidth - stlPaddingH;
    }
    var topHeight = style.height;
    if (topHeight == null && defaultOuterHeight != null) {
        topHeight = defaultOuterHeight - stlPaddingV;
    }
    var overflow = style.overflow;
    var wrapInfo = (overflow === 'break' || overflow === 'breakAll') && topWidth != null
        ? { width: topWidth, accumWidth: 0, breakAll: overflow === 'breakAll' }
        : null;
    var lastIndex = STYLE_REG.lastIndex = 0;
    var result;
    while ((result = STYLE_REG.exec(text)) != null) {
        var matchedIndex = result.index;
        if (matchedIndex > lastIndex) {
            pushTokens(contentBlock, text.substring(lastIndex, matchedIndex), style, wrapInfo);
        }
        pushTokens(contentBlock, result[2], style, wrapInfo, result[1]);
        lastIndex = STYLE_REG.lastIndex;
    }
    if (lastIndex < text.length) {
        pushTokens(contentBlock, text.substring(lastIndex, text.length), style, wrapInfo);
    }
    var pendingList = [];
    var calculatedHeight = 0;
    var calculatedWidth = 0;
    var truncate = overflow === 'truncate';
    var truncateLine = style.lineOverflow === 'truncate';
    var tmpTruncateOut = {};
    function finishLine(line, lineWidth, lineHeight) {
        line.width = lineWidth;
        line.lineHeight = lineHeight;
        calculatedHeight += lineHeight;
        calculatedWidth = Math.max(calculatedWidth, lineWidth);
    }
    outer: for (var i = 0; i < contentBlock.lines.length; i++) {
        var line = contentBlock.lines[i];
        var lineHeight = 0;
        var lineWidth = 0;
        for (var j = 0; j < line.tokens.length; j++) {
            var token = line.tokens[j];
            var tokenStyle = token.styleName && style.rich[token.styleName] || {};
            var textPadding = token.textPadding = tokenStyle.padding;
            var paddingH = textPadding ? textPadding[1] + textPadding[3] : 0;
            var font = token.font = tokenStyle.font || style.font;
            token.contentHeight = getLineHeight(font);
            var tokenHeight = retrieve2(tokenStyle.height, token.contentHeight);
            token.innerHeight = tokenHeight;
            textPadding && (tokenHeight += textPadding[0] + textPadding[2]);
            token.height = tokenHeight;
            token.lineHeight = retrieve3(tokenStyle.lineHeight, style.lineHeight, tokenHeight);
            token.align = tokenStyle && tokenStyle.align || topTextAlign;
            token.verticalAlign = tokenStyle && tokenStyle.verticalAlign || 'middle';
            if (truncateLine && topHeight != null && calculatedHeight + token.lineHeight > topHeight) {
                var originalLength = contentBlock.lines.length;
                if (j > 0) {
                    line.tokens = line.tokens.slice(0, j);
                    finishLine(line, lineWidth, lineHeight);
                    contentBlock.lines = contentBlock.lines.slice(0, i + 1);
                }
                else {
                    contentBlock.lines = contentBlock.lines.slice(0, i);
                }
                contentBlock.isTruncated = contentBlock.isTruncated || (contentBlock.lines.length < originalLength);
                break outer;
            }
            var styleTokenWidth = tokenStyle.width;
            var tokenWidthNotSpecified = styleTokenWidth == null || styleTokenWidth === 'auto';
            if (typeof styleTokenWidth === 'string' && styleTokenWidth.charAt(styleTokenWidth.length - 1) === '%') {
                token.percentWidth = styleTokenWidth;
                pendingList.push(token);
                token.contentWidth = measureWidth(ensureFontMeasureInfo(font), token.text);
            }
            else {
                if (tokenWidthNotSpecified) {
                    var textBackgroundColor = tokenStyle.backgroundColor;
                    var bgImg = textBackgroundColor && textBackgroundColor.image;
                    if (bgImg) {
                        bgImg = imageHelper.findExistImage(bgImg);
                        if (imageHelper.isImageReady(bgImg)) {
                            token.width = Math.max(token.width, bgImg.width * tokenHeight / bgImg.height);
                        }
                    }
                }
                var remainTruncWidth = truncate && topWidth != null
                    ? topWidth - lineWidth : null;
                if (remainTruncWidth != null && remainTruncWidth < token.width) {
                    if (!tokenWidthNotSpecified || remainTruncWidth < paddingH) {
                        token.text = '';
                        token.width = token.contentWidth = 0;
                    }
                    else {
                        truncateText2(tmpTruncateOut, token.text, remainTruncWidth - paddingH, font, style.ellipsis, { minChar: style.truncateMinChar });
                        token.text = tmpTruncateOut.text;
                        contentBlock.isTruncated = contentBlock.isTruncated || tmpTruncateOut.isTruncated;
                        token.width = token.contentWidth = measureWidth(ensureFontMeasureInfo(font), token.text);
                    }
                }
                else {
                    token.contentWidth = measureWidth(ensureFontMeasureInfo(font), token.text);
                }
            }
            token.width += paddingH;
            lineWidth += token.width;
            tokenStyle && (lineHeight = Math.max(lineHeight, token.lineHeight));
        }
        finishLine(line, lineWidth, lineHeight);
    }
    contentBlock.outerWidth = contentBlock.width = retrieve2(topWidth, calculatedWidth);
    contentBlock.outerHeight = contentBlock.height = retrieve2(topHeight, calculatedHeight);
    contentBlock.contentHeight = calculatedHeight;
    contentBlock.contentWidth = calculatedWidth;
    contentBlock.outerWidth += stlPaddingH;
    contentBlock.outerHeight += stlPaddingV;
    for (var i = 0; i < pendingList.length; i++) {
        var token = pendingList[i];
        var percentWidth = token.percentWidth;
        token.width = parseInt(percentWidth, 10) / 100 * contentBlock.width;
    }
    return contentBlock;
}
function pushTokens(block, str, style, wrapInfo, styleName) {
    var isEmptyStr = str === '';
    var tokenStyle = styleName && style.rich[styleName] || {};
    var lines = block.lines;
    var font = tokenStyle.font || style.font;
    var newLine = false;
    var strLines;
    var linesWidths;
    if (wrapInfo) {
        var tokenPadding = tokenStyle.padding;
        var tokenPaddingH = tokenPadding ? tokenPadding[1] + tokenPadding[3] : 0;
        if (tokenStyle.width != null && tokenStyle.width !== 'auto') {
            var outerWidth_1 = parsePercent(tokenStyle.width, wrapInfo.width) + tokenPaddingH;
            if (lines.length > 0) {
                if (outerWidth_1 + wrapInfo.accumWidth > wrapInfo.width) {
                    strLines = str.split('\n');
                    newLine = true;
                }
            }
            wrapInfo.accumWidth = outerWidth_1;
        }
        else {
            var res = wrapText(str, font, wrapInfo.width, wrapInfo.breakAll, wrapInfo.accumWidth);
            wrapInfo.accumWidth = res.accumWidth + tokenPaddingH;
            linesWidths = res.linesWidths;
            strLines = res.lines;
        }
    }
    if (!strLines) {
        strLines = str.split('\n');
    }
    var fontMeasureInfo = ensureFontMeasureInfo(font);
    for (var i = 0; i < strLines.length; i++) {
        var text = strLines[i];
        var token = new RichTextToken();
        token.styleName = styleName;
        token.text = text;
        token.isLineHolder = !text && !isEmptyStr;
        if (typeof tokenStyle.width === 'number') {
            token.width = tokenStyle.width;
        }
        else {
            token.width = linesWidths
                ? linesWidths[i]
                : measureWidth(fontMeasureInfo, text);
        }
        if (!i && !newLine) {
            var tokens = (lines[lines.length - 1] || (lines[0] = new RichTextLine())).tokens;
            var tokensLen = tokens.length;
            (tokensLen === 1 && tokens[0].isLineHolder)
                ? (tokens[0] = token)
                : ((text || !tokensLen || isEmptyStr) && tokens.push(token));
        }
        else {
            lines.push(new RichTextLine([token]));
        }
    }
}
function isAlphabeticLetter(ch) {
    var code = ch.charCodeAt(0);
    return code >= 0x20 && code <= 0x24F
        || code >= 0x370 && code <= 0x10FF
        || code >= 0x1200 && code <= 0x13FF
        || code >= 0x1E00 && code <= 0x206F;
}
var breakCharMap = reduce(',&?/;] '.split(''), function (obj, ch) {
    obj[ch] = true;
    return obj;
}, {});
function isWordBreakChar(ch) {
    if (isAlphabeticLetter(ch)) {
        if (breakCharMap[ch]) {
            return true;
        }
        return false;
    }
    return true;
}
function wrapText(text, font, lineWidth, isBreakAll, lastAccumWidth) {
    var lines = [];
    var linesWidths = [];
    var line = '';
    var currentWord = '';
    var currentWordWidth = 0;
    var accumWidth = 0;
    var fontMeasureInfo = ensureFontMeasureInfo(font);
    for (var i = 0; i < text.length; i++) {
        var ch = text.charAt(i);
        if (ch === '\n') {
            if (currentWord) {
                line += currentWord;
                accumWidth += currentWordWidth;
            }
            lines.push(line);
            linesWidths.push(accumWidth);
            line = '';
            currentWord = '';
            currentWordWidth = 0;
            accumWidth = 0;
            continue;
        }
        var chWidth = measureCharWidth(fontMeasureInfo, ch.charCodeAt(0));
        var inWord = isBreakAll ? false : !isWordBreakChar(ch);
        if (!lines.length
            ? lastAccumWidth + accumWidth + chWidth > lineWidth
            : accumWidth + chWidth > lineWidth) {
            if (!accumWidth) {
                if (inWord) {
                    lines.push(currentWord);
                    linesWidths.push(currentWordWidth);
                    currentWord = ch;
                    currentWordWidth = chWidth;
                }
                else {
                    lines.push(ch);
                    linesWidths.push(chWidth);
                }
            }
            else if (line || currentWord) {
                if (inWord) {
                    if (!line) {
                        line = currentWord;
                        currentWord = '';
                        currentWordWidth = 0;
                        accumWidth = currentWordWidth;
                    }
                    lines.push(line);
                    linesWidths.push(accumWidth - currentWordWidth);
                    currentWord += ch;
                    currentWordWidth += chWidth;
                    line = '';
                    accumWidth = currentWordWidth;
                }
                else {
                    if (currentWord) {
                        line += currentWord;
                        currentWord = '';
                        currentWordWidth = 0;
                    }
                    lines.push(line);
                    linesWidths.push(accumWidth);
                    line = ch;
                    accumWidth = chWidth;
                }
            }
            continue;
        }
        accumWidth += chWidth;
        if (inWord) {
            currentWord += ch;
            currentWordWidth += chWidth;
        }
        else {
            if (currentWord) {
                line += currentWord;
                currentWord = '';
                currentWordWidth = 0;
            }
            line += ch;
        }
    }
    if (currentWord) {
        line += currentWord;
    }
    if (line) {
        lines.push(line);
        linesWidths.push(accumWidth);
    }
    if (lines.length === 1) {
        accumWidth += lastAccumWidth;
    }
    return {
        accumWidth: accumWidth,
        lines: lines,
        linesWidths: linesWidths
    };
}
export function calcInnerTextOverflowArea(out, overflowRect, baseX, baseY, textAlign, textVerticalAlign) {
    out.baseX = baseX;
    out.baseY = baseY;
    out.outerWidth = out.outerHeight = null;
    if (!overflowRect) {
        return;
    }
    var textWidth = overflowRect.width * 2;
    var textHeight = overflowRect.height * 2;
    BoundingRect.set(tmpCITCTextRect, adjustTextX(baseX, textWidth, textAlign), adjustTextY(baseY, textHeight, textVerticalAlign), textWidth, textHeight);
    BoundingRect.intersect(overflowRect, tmpCITCTextRect, null, tmpCITCIntersectRectOpt);
    var outIntersectRect = tmpCITCIntersectRectOpt.outIntersectRect;
    out.outerWidth = outIntersectRect.width;
    out.outerHeight = outIntersectRect.height;
    out.baseX = adjustTextX(outIntersectRect.x, outIntersectRect.width, textAlign, true);
    out.baseY = adjustTextY(outIntersectRect.y, outIntersectRect.height, textVerticalAlign, true);
}
var tmpCITCTextRect = new BoundingRect(0, 0, 0, 0);
var tmpCITCIntersectRectOpt = { outIntersectRect: {}, clamp: true };
function formatText(text) {
    return text != null ? (text += '') : (text = '');
}
export function tSpanCreateBoundingRect(style) {
    var text = formatText(style.text);
    var font = style.font;
    var contentWidth = measureWidth(ensureFontMeasureInfo(font), text);
    var contentHeight = getLineHeight(font);
    return tSpanCreateBoundingRect2(style, contentWidth, contentHeight, null);
}
export function tSpanCreateBoundingRect2(style, contentWidth, contentHeight, forceLineWidth) {
    var rect = new BoundingRect(adjustTextX(style.x || 0, contentWidth, style.textAlign), adjustTextY(style.y || 0, contentHeight, style.textBaseline), contentWidth, contentHeight);
    var lineWidth = forceLineWidth != null
        ? forceLineWidth
        : (tSpanHasStroke(style) ? style.lineWidth : 0);
    if (lineWidth > 0) {
        rect.x -= lineWidth / 2;
        rect.y -= lineWidth / 2;
        rect.width += lineWidth;
        rect.height += lineWidth;
    }
    return rect;
}
export function tSpanHasStroke(style) {
    var stroke = style.stroke;
    return stroke != null && stroke !== 'none' && style.lineWidth > 0;
}
