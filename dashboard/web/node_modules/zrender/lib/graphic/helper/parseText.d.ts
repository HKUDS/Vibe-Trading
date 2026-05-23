import { TextAlign, TextVerticalAlign, NullUndefined } from '../../core/types';
import type { DefaultTextStyle, TextStyleProps } from '../Text';
import type { TSpanStyleProps } from '../TSpan';
import BoundingRect from '../../core/BoundingRect';
interface InnerTruncateOption {
    maxIteration?: number;
    minChar?: number;
    placeholder?: string;
    maxIterations?: number;
}
export declare function truncateText(text: string, containerWidth: number, font: string, ellipsis?: string, options?: InnerTruncateOption): string;
export interface PlainTextContentBlock {
    lineHeight: number;
    calculatedLineHeight: number;
    contentWidth: number;
    contentHeight: number;
    width: number;
    height: number;
    outerWidth: number;
    outerHeight: number;
    lines: string[];
    isTruncated: boolean;
}
export declare function parsePlainText(rawText: unknown, style: Omit<TextStyleProps, 'align' | 'verticalAlign'>, defaultOuterWidth: number | NullUndefined, defaultOuterHeight: number | NullUndefined): PlainTextContentBlock;
declare class RichTextToken {
    styleName: string;
    text: string;
    width: number;
    height: number;
    innerHeight: number;
    contentHeight: number;
    contentWidth: number;
    lineHeight: number;
    font: string;
    align: TextAlign;
    verticalAlign: TextVerticalAlign;
    textPadding: number[];
    percentWidth?: string;
    isLineHolder: boolean;
}
declare class RichTextLine {
    lineHeight: number;
    width: number;
    tokens: RichTextToken[];
    constructor(tokens?: RichTextToken[]);
}
export declare class RichTextContentBlock {
    width: number;
    height: number;
    contentWidth: number;
    contentHeight: number;
    outerWidth: number;
    outerHeight: number;
    lines: RichTextLine[];
    isTruncated: boolean;
}
export declare function parseRichText(rawText: unknown, style: Omit<TextStyleProps, 'align' | 'verticalAlign'>, defaultOuterWidth: number | NullUndefined, defaultOuterHeight: number | NullUndefined, topTextAlign: TextAlign): RichTextContentBlock;
export declare function calcInnerTextOverflowArea(out: CalcInnerTextOverflowAreaOut, overflowRect: DefaultTextStyle['overflowRect'], baseX: number, baseY: number, textAlign: TextAlign, textVerticalAlign: TextVerticalAlign): void;
export declare type CalcInnerTextOverflowAreaOut = {
    baseX: number;
    baseY: number;
    outerWidth: number | NullUndefined;
    outerHeight: number | NullUndefined;
};
export declare function tSpanCreateBoundingRect(style: Pick<TSpanStyleProps, 'text' | 'font' | 'x' | 'y' | 'textAlign' | 'textBaseline' | 'lineWidth'>): BoundingRect;
export declare function tSpanCreateBoundingRect2(style: Pick<TSpanStyleProps, 'x' | 'y' | 'textAlign' | 'textBaseline' | 'lineWidth'>, contentWidth: number, contentHeight: number, forceLineWidth: number | NullUndefined): BoundingRect;
export declare function tSpanHasStroke(style: TSpanStyleProps): boolean;
export {};
