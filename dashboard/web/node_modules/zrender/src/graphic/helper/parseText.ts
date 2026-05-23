import * as imageHelper from '../helper/image';
import {
    extend,
    retrieve2,
    retrieve3,
    reduce,
} from '../../core/util';
import { TextAlign, TextVerticalAlign, ImageLike, Dictionary, NullUndefined } from '../../core/types';
import type { DefaultTextStyle, TextStyleProps } from '../Text';
import type { TSpanStyleProps } from '../TSpan';
import {
    adjustTextX,
    adjustTextY,
    ensureFontMeasureInfo, FontMeasureInfo, getLineHeight, measureCharWidth, measureWidth, parsePercent,
} from '../../contain/text';
import BoundingRect, { BoundingRectIntersectOpt } from '../../core/BoundingRect';

const STYLE_REG = /\{([a-zA-Z0-9_]+)\|([^}]*)\}/g;

interface InnerTruncateOption {
    maxIteration?: number
    // If truncate result are less than minChar, ellipsis will not show
    // which is better for user hint in some cases
    minChar?: number
    // When all truncated, use the placeholder
    placeholder?: string

    maxIterations?: number
}

interface InnerPreparedTruncateOption extends Required<InnerTruncateOption> {
    ellipsis: string
    ellipsisWidth: number
    contentWidth: number

    containerWidth: number
    fontMeasureInfo: FontMeasureInfo
}

/**
 * Show ellipsis if overflow.
 */
export function truncateText(
    text: string,
    containerWidth: number,
    font: string,
    ellipsis?: string,
    options?: InnerTruncateOption
): string {
    const out = {} as Parameters<typeof truncateText2>[0];
    truncateText2(out, text, containerWidth, font, ellipsis, options);
    return out.text;
}

// PENDING: not sure whether `truncateText` is used outside zrender, since it has an `export`
// specifier. So keep it and perform the interface modification in `truncateText2`.
function truncateText2(
    out: {text: string, isTruncated: boolean},
    text: string,
    containerWidth: number,
    font: string,
    ellipsis?: string,
    options?: InnerTruncateOption
): void {
    if (!containerWidth) {
        out.text = '';
        out.isTruncated = false;
        return;
    }

    const textLines = (text + '').split('\n');
    options = prepareTruncateOptions(containerWidth, font, ellipsis, options);

    // FIXME
    // It is not appropriate that every line has '...' when truncate multiple lines.
    let isTruncated = false;
    const truncateOut = {} as Parameters<typeof truncateSingleLine>[0];
    for (let i = 0, len = textLines.length; i < len; i++) {
        truncateSingleLine(truncateOut, textLines[i], options as InnerPreparedTruncateOption);
        textLines[i] = truncateOut.textLine;
        isTruncated = isTruncated || truncateOut.isTruncated;
    }

    out.text = textLines.join('\n');
    out.isTruncated = isTruncated;
}

function prepareTruncateOptions(
    containerWidth: number,
    font: string,
    ellipsis?: string,
    options?: InnerTruncateOption
): InnerPreparedTruncateOption {
    options = options || {};
    let preparedOpts = extend({}, options) as InnerPreparedTruncateOption;

    ellipsis = retrieve2(ellipsis, '...');
    preparedOpts.maxIterations = retrieve2(options.maxIterations, 2);
    const minChar = preparedOpts.minChar = retrieve2(options.minChar, 0);
    const fontMeasureInfo = preparedOpts.fontMeasureInfo = ensureFontMeasureInfo(font);
    const ascCharWidth = fontMeasureInfo.asciiCharWidth;
    preparedOpts.placeholder = retrieve2(options.placeholder, '');

    // Example 1: minChar: 3, text: 'asdfzxcv', truncate result: 'asdf', but not: 'a...'.
    // Example 2: minChar: 3, text: '维度', truncate result: '维', but not: '...'.
    let contentWidth = containerWidth = Math.max(0, containerWidth - 1); // Reserve some gap.
    for (let i = 0; i < minChar && contentWidth >= ascCharWidth; i++) {
        contentWidth -= ascCharWidth;
    }

    let ellipsisWidth = measureWidth(fontMeasureInfo, ellipsis);
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

function truncateSingleLine(
    out: {textLine: string, isTruncated: boolean},
    textLine: string,
    options: InnerPreparedTruncateOption
): void {
    const containerWidth = options.containerWidth;
    const contentWidth = options.contentWidth;
    const fontMeasureInfo = options.fontMeasureInfo;

    if (!containerWidth) {
        out.textLine = '';
        out.isTruncated = false;
        return;
    }

    let lineWidth = measureWidth(fontMeasureInfo, textLine);

    if (lineWidth <= containerWidth) {
        out.textLine = textLine;
        out.isTruncated = false;
        return;
    }

    for (let j = 0; ; j++) {
        if (lineWidth <= contentWidth || j >= options.maxIterations) {
            textLine += options.ellipsis;
            break;
        }

        const subLength = j === 0
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

function estimateLength(
    text: string,
    contentWidth: number,
    fontMeasureInfo: FontMeasureInfo
): number {
    let width = 0;
    let i = 0;
    for (let len = text.length; i < len && width < contentWidth; i++) {
        width += measureCharWidth(fontMeasureInfo, text.charCodeAt(i));
    }
    return i;
}

export interface PlainTextContentBlock {
    lineHeight: number
    // Line height of actual content.
    calculatedLineHeight: number

    // Calculated based on the text.
    contentWidth: number
    contentHeight: number

    // i.e., `retrieve2(style.width/height, contentWidth/contentHeight)`
    width: number
    height: number

    // i.e., `contentBlock.width/height + style.padding`
    // `borderWidth` is not included here, because historically Path is placed regardless of `lineWidth`,
    // and `outerWidth`/`outerHeight` is used to calculate placement.
    outerWidth: number
    outerHeight: number

    lines: string[]

    // Be `true` if and only if the result text is modified due to overflow, due to
    // settings on either `overflow` or `lineOverflow`
    isTruncated: boolean
}

export function parsePlainText(
    rawText: unknown,
    style: Omit<TextStyleProps, 'align' | 'verticalAlign'>, // Exclude props in DefaultTextStyle
    defaultOuterWidth: number | NullUndefined,
    defaultOuterHeight: number | NullUndefined
): PlainTextContentBlock {
    const text = formatText(rawText);

    // textPadding has been normalized
    const overflow = style.overflow;
    const padding = style.padding as number[];
    const paddingH = padding ? padding[1] + padding[3] : 0;
    const paddingV = padding ? padding[0] + padding[2] : 0;
    const font = style.font;
    const truncate = overflow === 'truncate';
    const calculatedLineHeight = getLineHeight(font);
    const lineHeight = retrieve2(style.lineHeight, calculatedLineHeight);

    const truncateLineOverflow = style.lineOverflow === 'truncate';
    let isTruncated = false;

    let width = style.width;
    if (width == null && defaultOuterWidth != null) {
        width = defaultOuterWidth - paddingH;
    }
    let height = style.height;
    if (height == null && defaultOuterHeight != null) {
        height = defaultOuterHeight - paddingV;
    }

    let lines: string[];

    if (width != null && (overflow === 'break' || overflow === 'breakAll')) {
        lines = text ? wrapText(text, style.font, width, overflow === 'breakAll', 0).lines : [];
    }
    else {
        lines = text ? text.split('\n') : [];
    }

    let contentHeight = lines.length * lineHeight;
    if (height == null) {
        height = contentHeight;
    }

    // Truncate lines.
    if (contentHeight > height && truncateLineOverflow) {
        const lineCount = Math.floor(height / lineHeight);

        isTruncated = isTruncated || (lines.length > lineCount);
        lines = lines.slice(0, lineCount);
        contentHeight = lines.length * lineHeight;

        // TODO If show ellipse for line truncate
        // if (style.ellipsis) {
        //     const options = prepareTruncateOptions(width, font, style.ellipsis, {
        //         minChar: style.truncateMinChar,
        //         placeholder: style.placeholder
        //     });
        //     lines[lineCount - 1] = truncateSingleLine(lastLine, options);
        // }
    }

    if (text && truncate && width != null) {
        const options = prepareTruncateOptions(width, font, style.ellipsis, {
            minChar: style.truncateMinChar,
            placeholder: style.placeholder
        });
        // Having every line has '...' when truncate multiple lines.
        const singleOut = {} as Parameters<typeof truncateSingleLine>[0];
        for (let i = 0; i < lines.length; i++) {
            truncateSingleLine(singleOut, lines[i], options);
            lines[i] = singleOut.textLine;
            isTruncated = isTruncated || singleOut.isTruncated;
        }
    }

    // Calculate real text width and height
    let outerHeight = height;
    let contentWidth = 0;
    const fontMeasureInfo = ensureFontMeasureInfo(font);
    for (let i = 0; i < lines.length; i++) {
        contentWidth = Math.max(measureWidth(fontMeasureInfo, lines[i]), contentWidth);
    }
    if (width == null) {
        // When width is not explicitly set, use contentWidth as width.
        width = contentWidth;
    }

    let outerWidth = width;
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

class RichTextToken {
    styleName: string
    text: string

    // Includes `tokenStyle.padding`
    width: number
    height: number

    // Inner height exclude padding
    // i.e., `retrieve2(tokenStyle.height, token.contentHeight)`
    innerHeight: number

    // Width and height of actual text content.
    contentHeight: number
    contentWidth: number

    lineHeight: number
    font: string
    align: TextAlign
    verticalAlign: TextVerticalAlign

    textPadding: number[]
    percentWidth?: string

    isLineHolder: boolean
}
class RichTextLine {
    lineHeight: number
    width: number
    tokens: RichTextToken[] = []

    constructor(tokens?: RichTextToken[]) {
        if (tokens) {
            this.tokens = tokens;
        }
    }
}
export class RichTextContentBlock {
    // i.e. `retrieve2(outermostStyle.width, contentWidth)`.
    // exclude outermost style.padding.
    width: number = 0
    height: number = 0
    // Calculated text width/height based on content (including tokenStyle.padding).
    contentWidth: number = 0
    contentHeight: number = 0
    // i.e., contentBlock.width/height + outermostStyle.padding
    // `borderWidth` is not included here, because historically Path is placed regardless of `lineWidth`,
    // and `outerWidth`/`outerHeight` is used to calculate placement.
    outerWidth: number = 0
    outerHeight: number = 0
    lines: RichTextLine[] = []
    // Be `true` if and only if the result text is modified due to overflow, due to
    // settings on either `overflow` or `lineOverflow`
    isTruncated: boolean = false
}

type WrapInfo = {
    width: number,
    accumWidth: number,
    breakAll: boolean
}
/**
 * For example: 'some text {a|some text}other text{b|some text}xxx{c|}xxx'
 * Also consider 'bbbb{a|xxx\nzzz}xxxx\naaaa'.
 * If styleName is undefined, it is plain text.
 */
export function parseRichText(
    rawText: unknown,
    style: Omit<TextStyleProps, 'align' | 'verticalAlign'>, // Exclude props in DefaultTextStyle
    defaultOuterWidth: number | NullUndefined,
    defaultOuterHeight: number | NullUndefined,
    topTextAlign: TextAlign
): RichTextContentBlock {
    const contentBlock = new RichTextContentBlock();

    const text = formatText(rawText);
    if (!text) {
        return contentBlock;
    }

    const stlPadding = style.padding as number[];
    const stlPaddingH = stlPadding ? stlPadding[1] + stlPadding[3] : 0;
    const stlPaddingV = stlPadding ? stlPadding[0] + stlPadding[2] : 0;

    let topWidth = style.width;
    if (topWidth == null && defaultOuterWidth != null) {
        topWidth = defaultOuterWidth - stlPaddingH;
    }
    let topHeight = style.height;
    if (topHeight == null && defaultOuterHeight != null) {
        topHeight = defaultOuterHeight - stlPaddingV;
    }

    const overflow = style.overflow;
    let wrapInfo: WrapInfo = (overflow === 'break' || overflow === 'breakAll') && topWidth != null
        ? {width: topWidth, accumWidth: 0, breakAll: overflow === 'breakAll'}
        : null;

    let lastIndex = STYLE_REG.lastIndex = 0;
    let result;
    while ((result = STYLE_REG.exec(text)) != null) {
        const matchedIndex = result.index;
        if (matchedIndex > lastIndex) {
            pushTokens(contentBlock, text.substring(lastIndex, matchedIndex), style, wrapInfo);
        }
        pushTokens(contentBlock, result[2], style, wrapInfo, result[1]);
        lastIndex = STYLE_REG.lastIndex;
    }

    if (lastIndex < text.length) {
        pushTokens(contentBlock, text.substring(lastIndex, text.length), style, wrapInfo);
    }

    // For `textWidth: xx%`
    let pendingList = [];

    let calculatedHeight = 0;
    let calculatedWidth = 0;

    const truncate = overflow === 'truncate';
    const truncateLine = style.lineOverflow === 'truncate';
    const tmpTruncateOut = {} as Parameters<typeof truncateText2>[0];

    // let prevToken: RichTextToken;

    function finishLine(line: RichTextLine, lineWidth: number, lineHeight: number) {
        line.width = lineWidth;
        line.lineHeight = lineHeight;
        calculatedHeight += lineHeight;
        calculatedWidth = Math.max(calculatedWidth, lineWidth);
    }
    // Calculate layout info of tokens.
    outer: for (let i = 0; i < contentBlock.lines.length; i++) {
        const line = contentBlock.lines[i];
        let lineHeight = 0;
        let lineWidth = 0;

        for (let j = 0; j < line.tokens.length; j++) {
            const token = line.tokens[j];
            const tokenStyle = token.styleName && style.rich[token.styleName] || {};
            // textPadding should not inherit from style.
            const textPadding = token.textPadding = tokenStyle.padding as number[];
            const paddingH = textPadding ? textPadding[1] + textPadding[3] : 0;

            const font = token.font = tokenStyle.font || style.font;

            token.contentHeight = getLineHeight(font);
            // textHeight can be used when textVerticalAlign is specified in token.
            let tokenHeight = retrieve2(
                // textHeight should not be inherited, consider it can be specified
                // as box height of the block.
                tokenStyle.height, token.contentHeight
            );
            token.innerHeight = tokenHeight;

            textPadding && (tokenHeight += textPadding[0] + textPadding[2]);
            token.height = tokenHeight;
            // Include padding in lineHeight.
            token.lineHeight = retrieve3(
                tokenStyle.lineHeight, style.lineHeight, tokenHeight
            );

            token.align = tokenStyle && tokenStyle.align || topTextAlign;
            token.verticalAlign = tokenStyle && tokenStyle.verticalAlign || 'middle';

            if (truncateLine && topHeight != null && calculatedHeight + token.lineHeight > topHeight) {
                // TODO Add ellipsis on the previous token.
                // prevToken.text =
                const originalLength = contentBlock.lines.length;
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

            let styleTokenWidth = tokenStyle.width;
            let tokenWidthNotSpecified = styleTokenWidth == null || styleTokenWidth === 'auto';

            // Percent width, can be `100%`, can be used in drawing separate
            // line when box width is needed to be auto.
            if (typeof styleTokenWidth === 'string' && styleTokenWidth.charAt(styleTokenWidth.length - 1) === '%') {
                token.percentWidth = styleTokenWidth;
                pendingList.push(token);

                token.contentWidth = measureWidth(ensureFontMeasureInfo(font), token.text);
                // Do not truncate in this case, because there is no user case
                // and it is too complicated.
            }
            else {
                if (tokenWidthNotSpecified) {
                    // FIXME: If image is not loaded and textWidth is not specified, calling
                    // `getBoundingRect()` will not get correct result.
                    const textBackgroundColor = tokenStyle.backgroundColor;
                    let bgImg = textBackgroundColor && (textBackgroundColor as { image: ImageLike }).image;

                    if (bgImg) {
                        bgImg = imageHelper.findExistImage(bgImg);
                        if (imageHelper.isImageReady(bgImg)) {
                            // Update token width from image size.
                            token.width = Math.max(token.width, bgImg.width * tokenHeight / bgImg.height);
                        }
                    }
                }

                const remainTruncWidth = truncate && topWidth != null
                    ? topWidth - lineWidth : null;

                if (remainTruncWidth != null && remainTruncWidth < token.width) {
                    if (!tokenWidthNotSpecified || remainTruncWidth < paddingH) {
                        token.text = '';
                        token.width = token.contentWidth = 0;
                    }
                    else {
                        truncateText2(
                            tmpTruncateOut,
                            token.text, remainTruncWidth - paddingH, font, style.ellipsis,
                            {minChar: style.truncateMinChar}
                        );
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

            // prevToken = token;
        }

        finishLine(line, lineWidth, lineHeight);
    }

    contentBlock.outerWidth = contentBlock.width = retrieve2(topWidth, calculatedWidth);
    contentBlock.outerHeight = contentBlock.height = retrieve2(topHeight, calculatedHeight);
    contentBlock.contentHeight = calculatedHeight;
    contentBlock.contentWidth = calculatedWidth;

    contentBlock.outerWidth += stlPaddingH;
    contentBlock.outerHeight += stlPaddingV;

    for (let i = 0; i < pendingList.length; i++) {
        const token = pendingList[i];
        const percentWidth = token.percentWidth;
        // Should not base on outerWidth, because token can not be placed out of padding.
        token.width = parseInt(percentWidth, 10) / 100 * contentBlock.width;
    }

    return contentBlock;
}

type TokenStyle = TextStyleProps['rich'][string];

function pushTokens(
    block: RichTextContentBlock,
    str: string,
    style: TextStyleProps,
    wrapInfo: WrapInfo,
    styleName?: string
) {
    const isEmptyStr = str === '';
    const tokenStyle: TokenStyle = styleName && style.rich[styleName] || {};
    const lines = block.lines;
    const font = tokenStyle.font || style.font;
    let newLine = false;
    let strLines;
    let linesWidths;

    if (wrapInfo) {
        const tokenPadding = tokenStyle.padding as number[];
        let tokenPaddingH = tokenPadding ? tokenPadding[1] + tokenPadding[3] : 0;
        if (tokenStyle.width != null && tokenStyle.width !== 'auto') {
            // Wrap the whole token if tokenWidth if fixed.
            const outerWidth = parsePercent(tokenStyle.width, wrapInfo.width) + tokenPaddingH;
            if (lines.length > 0) { // Not first line
                if (outerWidth + wrapInfo.accumWidth > wrapInfo.width) {
                    // TODO Support wrap text in token.
                    strLines = str.split('\n');
                    newLine = true;
                }
            }

            wrapInfo.accumWidth = outerWidth;
        }
        else {
            const res = wrapText(str, font, wrapInfo.width, wrapInfo.breakAll, wrapInfo.accumWidth);
            wrapInfo.accumWidth = res.accumWidth + tokenPaddingH;
            linesWidths = res.linesWidths;
            strLines = res.lines;
        }
    }

    if (!strLines) {
        strLines = str.split('\n');
    }

    const fontMeasureInfo = ensureFontMeasureInfo(font);
    for (let i = 0; i < strLines.length; i++) {
        const text = strLines[i];
        const token = new RichTextToken();
        token.styleName = styleName;
        token.text = text;
        token.isLineHolder = !text && !isEmptyStr;

        if (typeof tokenStyle.width === 'number') {
            token.width = tokenStyle.width;
        }
        else {
            token.width = linesWidths
                ? linesWidths[i] // Calculated width in the wrap
                : measureWidth(fontMeasureInfo, text);
        }

        // The first token should be appended to the last line if not new line.
        if (!i && !newLine) {
            const tokens = (lines[lines.length - 1] || (lines[0] = new RichTextLine())).tokens;

            // Consider cases:
            // (1) ''.split('\n') => ['', '\n', ''], the '' at the first item
            // (which is a placeholder) should be replaced by new token.
            // (2) A image backage, where token likes {a|}.
            // (3) A redundant '' will affect textAlign in line.
            // (4) tokens with the same tplName should not be merged, because
            // they should be displayed in different box (with border and padding).
            const tokensLen = tokens.length;
            (tokensLen === 1 && tokens[0].isLineHolder)
                ? (tokens[0] = token)
                // Consider text is '', only insert when it is the "lineHolder" or
                // "emptyStr". Otherwise a redundant '' will affect textAlign in line.
                : ((text || !tokensLen || isEmptyStr) && tokens.push(token));
        }
        // Other tokens always start a new line.
        else {
            // If there is '', insert it as a placeholder.
            lines.push(new RichTextLine([token]));
        }
    }
}


function isAlphabeticLetter(ch: string) {
    // Unicode Character Ranges
    // https://jrgraphix.net/research/unicode_blocks.php
    // The following ranges may not cover all letter ranges but only the more
    // popular ones. Developers could make pull requests when they find those
    // not covered.
    let code = ch.charCodeAt(0);
    return code >= 0x20 && code <= 0x24F // Latin
        || code >= 0x370 && code <= 0x10FF // Greek, Coptic, Cyrilic, and etc.
        || code >= 0x1200 && code <= 0x13FF // Ethiopic and Cherokee
        || code >= 0x1E00 && code <= 0x206F; // Latin and Greek extended
}

const breakCharMap = reduce(',&?/;] '.split(''), function (obj, ch) {
    obj[ch] = true;
    return obj;
}, {} as Dictionary<boolean>);
/**
 * If break by word. For latin languages.
 */
function isWordBreakChar(ch: string) {
    if (isAlphabeticLetter(ch)) {
        if (breakCharMap[ch]) {
            return true;
        }
        return false;
    }
    return true;
}

/**
 * NOTE: The current strategy is that if no enough space, all the text is
 * still displayed, regardless of overflow.
 * A clip path can be used to completely avoid overflow.
 */
function wrapText(
    text: string,
    font: string,
    lineWidth: number,
    isBreakAll: boolean,
    lastAccumWidth: number
) {
    let lines: string[] = [];
    let linesWidths: number[] = [];
    let line = '';
    let currentWord = '';
    let currentWordWidth = 0;
    let accumWidth = 0;
    const fontMeasureInfo = ensureFontMeasureInfo(font);

    for (let i = 0; i < text.length; i++) {

        const ch = text.charAt(i);
        if (ch === '\n') {
            if (currentWord) {
                line += currentWord;
                accumWidth += currentWordWidth;
            }
            lines.push(line);
            linesWidths.push(accumWidth);
            // Reset
            line = '';
            currentWord = '';
            currentWordWidth = 0;
            accumWidth = 0;
            continue;
        }

        const chWidth = measureCharWidth(fontMeasureInfo, ch.charCodeAt(0));
        const inWord = isBreakAll ? false : !isWordBreakChar(ch);

        if (!lines.length
            ? lastAccumWidth + accumWidth + chWidth > lineWidth
            : accumWidth + chWidth > lineWidth
        ) {
            if (!accumWidth) {  // If nothing appended yet.
                if (inWord) {
                    // The word length is still too long for one line
                    // Force break the word
                    lines.push(currentWord);
                    linesWidths.push(currentWordWidth);

                    currentWord = ch;
                    currentWordWidth = chWidth;
                }
                else {
                    // lineWidth is too small for ch
                    lines.push(ch);
                    linesWidths.push(chWidth);
                }
            }
            else if (line || currentWord) {
                if (inWord) {
                    if (!line) {
                        // The one word is still too long for one line
                        // Force break the word
                        // TODO Keep the word?
                        line = currentWord;
                        currentWord = '';
                        currentWordWidth = 0;
                        accumWidth = currentWordWidth;
                    }

                    lines.push(line);
                    linesWidths.push(accumWidth - currentWordWidth);

                    // Break the whole word
                    currentWord += ch;
                    currentWordWidth += chWidth;
                    line = '';
                    accumWidth = currentWordWidth;
                }
                else {
                    // Append lastWord if have
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
            // Append whole word
            if (currentWord) {
                line += currentWord;
                // Reset
                currentWord = '';
                currentWordWidth = 0;
            }

            // Append character
            line += ch;
        }
    }

    // Append last line.
    if (currentWord) {
        line += currentWord;
    }
    if (line) {
        lines.push(line);
        linesWidths.push(accumWidth);
    }

    if (lines.length === 1) {
        // No new line.
        accumWidth += lastAccumWidth;
    }

    return {
        // Accum width of last line
        accumWidth,
        lines: lines,
        linesWidths
    };
}

/**
 * @see {ElementTextConfig['autoOverflowArea']}
 */
export function calcInnerTextOverflowArea(
    out: CalcInnerTextOverflowAreaOut,
    overflowRect: DefaultTextStyle['overflowRect'],
    baseX: number,
    baseY: number,
    textAlign: TextAlign,
    textVerticalAlign: TextVerticalAlign
): void {
    out.baseX = baseX;
    out.baseY = baseY;
    out.outerWidth = out.outerHeight = null;

    if (!overflowRect) {
        return;
    }

    const textWidth = overflowRect.width * 2;
    const textHeight = overflowRect.height * 2;
    BoundingRect.set(
        tmpCITCTextRect,
        adjustTextX(baseX, textWidth, textAlign),
        adjustTextY(baseY, textHeight, textVerticalAlign),
        textWidth,
        textHeight
    );
    // If `overflow: break` and no intersection or intersect but no enough space, we still display all text
    // on the edge regardless of the overflow. Although that might be meaningless in production env, it is
    // logically sound and helps in debug. Therefore we use `intersectOpt.clamp`.
    BoundingRect.intersect(overflowRect, tmpCITCTextRect, null, tmpCITCIntersectRectOpt);
    const outIntersectRect = tmpCITCIntersectRectOpt.outIntersectRect;
    out.outerWidth = outIntersectRect.width;
    out.outerHeight = outIntersectRect.height;
    out.baseX = adjustTextX(outIntersectRect.x, outIntersectRect.width, textAlign, true);
    out.baseY = adjustTextY(outIntersectRect.y, outIntersectRect.height, textVerticalAlign, true);
}
const tmpCITCTextRect = new BoundingRect(0, 0, 0, 0);
const tmpCITCIntersectRectOpt = {outIntersectRect: {}, clamp: true} as BoundingRectIntersectOpt;

export type CalcInnerTextOverflowAreaOut = {
    // The input baseX/baseY or modified baseX/baseY, must exists.
    baseX: number
    baseY: number
    // Calculated outer size based on overflowRect
    // NaN indicates don't draw.
    outerWidth: number | NullUndefined
    outerHeight: number | NullUndefined
};

// For backward compatibility, and possibly loose type.
function formatText(text: unknown): string {
    return text != null ? (text += '') : (text = '');
}

export function tSpanCreateBoundingRect(
    style: Pick<TSpanStyleProps, 'text' | 'font' | 'x' | 'y' | 'textAlign' | 'textBaseline' | 'lineWidth'>,
): BoundingRect {
    // Should follow the same way as `parsePlainText` to guarantee the consistency of the result.
    const text = formatText(style.text);
    const font = style.font;
    const contentWidth = measureWidth(ensureFontMeasureInfo(font), text);
    const contentHeight = getLineHeight(font);

    return tSpanCreateBoundingRect2(
        style,
        contentWidth,
        contentHeight,
        null
    );
}

export function tSpanCreateBoundingRect2(
    style: Pick<TSpanStyleProps, 'x' | 'y' | 'textAlign' | 'textBaseline' | 'lineWidth'>,
    contentWidth: number,
    contentHeight: number,
    forceLineWidth: number | NullUndefined,
): BoundingRect {
    const rect = new BoundingRect(
        adjustTextX(style.x || 0, contentWidth, style.textAlign as TextAlign),
        adjustTextY(style.y || 0, contentHeight, style.textBaseline as TextVerticalAlign),
        /**
         * Text boundary should be the real text width.
         * Otherwise, there will be extra space in the
         * bounding rect calculated.
         */
        contentWidth,
        contentHeight
    );

    const lineWidth = forceLineWidth != null
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

export function tSpanHasStroke(style: TSpanStyleProps): boolean {
    const stroke = style.stroke;
    return stroke != null && stroke !== 'none' && style.lineWidth > 0;
}

