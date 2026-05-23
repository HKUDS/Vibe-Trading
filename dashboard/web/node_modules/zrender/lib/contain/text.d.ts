import BoundingRect, { RectLike } from '../core/BoundingRect';
import { TextAlign, TextVerticalAlign, BuiltinTextPosition } from '../core/types';
import LRU from '../core/LRU';
export declare function getWidth(text: string, font: string): number;
export interface FontMeasureInfo {
    font: string;
    strWidthCache: LRU<number>;
    asciiWidthMap: number[] | null | undefined;
    asciiWidthMapTried: boolean;
    stWideCharWidth: number;
    asciiCharWidth: number;
}
export declare function ensureFontMeasureInfo(font: string): FontMeasureInfo;
export declare function measureCharWidth(fontMeasureInfo: FontMeasureInfo, charCode: number): number;
export declare function measureWidth(fontMeasureInfo: FontMeasureInfo, text: string): number;
export declare function innerGetBoundingRect(text: string, font: string, textAlign?: TextAlign, textBaseline?: TextVerticalAlign): BoundingRect;
export declare function getBoundingRect(text: string, font: string, textAlign?: TextAlign, textBaseline?: TextVerticalAlign): BoundingRect;
export declare function adjustTextX(x: number, width: number, textAlign: TextAlign, inverse?: boolean): number;
export declare function adjustTextY(y: number, height: number, verticalAlign: TextVerticalAlign, inverse?: boolean): number;
export declare function getLineHeight(font?: string): number;
export declare function measureText(text: string, font?: string): {
    width: number;
};
export declare function parsePercent(value: number | string, maxValue: number): number;
export interface TextPositionCalculationResult {
    x: number;
    y: number;
    align: TextAlign;
    verticalAlign: TextVerticalAlign;
}
export declare function calculateTextPosition(out: TextPositionCalculationResult, opts: {
    position?: BuiltinTextPosition | (number | string)[];
    distance?: number;
    global?: boolean;
}, rect: RectLike): TextPositionCalculationResult;
