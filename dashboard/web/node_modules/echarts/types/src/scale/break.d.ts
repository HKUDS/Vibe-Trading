import { AxisLabelFormatterExtraParams } from '../coord/axisCommonTypes.js';
import type { NullUndefined, ParsedAxisBreak, ParsedAxisBreakList, AxisBreakOption, AxisBreakOptionIdentifierInAxis, ScaleTick, VisualAxisBreak } from '../util/types.js';
import { ValueTransformLookupOpt } from './helper.js';
import type Scale from './Scale.js';
import { ScaleMapper } from './scaleMapper.js';
/**
 * @file The facade of scale break.
 *  Separate the impl to reduce code size.
 *
 * @caution
 *  Must not import `scale/breakImpl.ts` directly or indirectly.
 *  Must not implement anything in this file.
 */
export interface BreakScaleMapper extends ScaleMapper {
    readonly breaks: ParsedAxisBreakList;
    hasBreaks(): boolean;
    calcNiceTickMultiple(tickVal: number, estimateNiceMultiple: (tickVal: number, brkEnd: number) => number): number;
}
export declare type AxisBreakParsingResult = {
    breaks: ParsedAxisBreakList;
};
export declare type ParseBreakOptionOpt = {
    noNegative?: boolean;
};
export declare type ParseAxisBreakOptionInwardTransformOut = {
    lookup: ValueTransformLookupOpt['lookup'];
    original?: AxisBreakParsingResult;
    transformed?: AxisBreakParsingResult;
};
/**
 * Whether to remove any normal ticks that are too close to axis breaks.
 *  - 'auto': Default. Remove any normal ticks that are too close to axis breaks.
 *  - 'no': Do nothing pruning.
 *  - 'exclude_scale_bound': Prune but keep scale extent boundary.
 * For example:
 *  - For splitLine, if remove the tick on extent, split line on the boundary of cartesian
 *   will not be displayed, causing weird effect.
 *  - For labels, scale extent boundary should be pruned if in break, otherwise duplicated
 *   labels will displayed.
 */
export declare type ParamPruneByBreak = 'auto' | 'no' | 'preserve_extent_bound' | NullUndefined;
declare type BreakScaleHelper = {
    createBreakScaleMapper(breakParsed: AxisBreakParsingResult | NullUndefined, initialExtent: number[] | NullUndefined): BreakScaleMapper;
    pruneTicksByBreak<TItem extends ScaleTick | number>(pruneByBreak: ParamPruneByBreak, ticks: TItem[], breaks: ParsedAxisBreakList, getValue: (item: TItem) => number, interval: number, scaleExtent: number[]): void;
    addBreaksToTicks(ticks: ScaleTick[], breaks: ParsedAxisBreakList, scaleExtent: number[], getTimeProps?: (clampedBrk: ParsedAxisBreak) => ScaleTick['time']): void;
    parseAxisBreakOption(breakOptionList: AxisBreakOption[] | NullUndefined, scale: {
        parse: Scale['parse'];
    }, opt?: {
        noNegative: boolean;
    }): AxisBreakParsingResult;
    identifyAxisBreak(brk: AxisBreakOption, identifier: AxisBreakOptionIdentifierInAxis): boolean;
    serializeAxisBreakIdentifier(identifier: AxisBreakOptionIdentifierInAxis): string;
    retrieveAxisBreakPairs<TItem, TReturnIdx extends boolean>(itemList: TItem[], getVisualAxisBreak: (item: TItem) => VisualAxisBreak | NullUndefined, returnIdx: TReturnIdx): (TReturnIdx extends false ? TItem[][] : number[][]);
    getTicksBreakOutwardTransform(scale: ScaleMapper, tick: ScaleTick, outermostBreaks: ParsedAxisBreakList, lookup: ValueTransformLookupOpt['lookup']): {
        tickVal: number | NullUndefined;
        vBreak: VisualAxisBreak | NullUndefined;
    } | NullUndefined;
    parseAxisBreakOptionInwardTransform(breakOptionList: AxisBreakOption[] | NullUndefined, scale: Scale, parseOpt: ParseBreakOptionOpt, lookupStartIdx: number, out: ParseAxisBreakOptionInwardTransformOut): void;
    makeAxisLabelFormatterParamBreak(extraParam: AxisLabelFormatterExtraParams | NullUndefined, vBreak: VisualAxisBreak | NullUndefined): AxisLabelFormatterExtraParams | NullUndefined;
};
export declare function registerScaleBreakHelperImpl(impl: BreakScaleHelper): void;
export declare function getScaleBreakHelper(): BreakScaleHelper | NullUndefined;
export declare function simplyParseBreakOption(scale: {
    parse: Scale['parse'];
}, opt: {
    breakOption?: AxisBreakOption[] | NullUndefined;
    breakParsed?: AxisBreakParsingResult | NullUndefined;
}): AxisBreakParsingResult | NullUndefined;
export declare function getBreaksUnsafe(scale: Scale): ParsedAxisBreakList;
export declare function hasBreaks(scale: Scale): boolean;
export {};
