import type IntervalScale from './Interval.js';
import type LogScale from './Log.js';
import type Scale from './Scale.js';
import type TimeScale from './Time.js';
import { NullUndefined, ScaleTick } from '../util/types.js';
import type OrdinalScale from './Ordinal.js';
import { ScaleExtentFixMinMax, ScaleRawExtentResultFinal } from '../coord/scaleRawExtentInfo.js';
declare type intervalScaleNiceTicksResult = {
    interval: number;
    intervalPrecision: number;
    niceTickExtent: [number, number];
};
export declare type IntervalScaleGetLabelOpt = {
    precision?: 'auto' | number;
    pad?: boolean;
};
/**
 * See also method `nice` in `src/util/number.ts`.
 */
export declare function isIntervalOrLogScale(scale: Scale): scale is (LogScale | IntervalScale);
export declare function isIntervalOrTimeScale(scale: Scale): scale is (IntervalScale | TimeScale);
export declare function isIntervalScale(scale: Scale): scale is IntervalScale;
export declare function isTimeScale(scale: Scale): scale is TimeScale;
export declare function isLogScale(scale: Scale): scale is LogScale;
export declare function isOrdinalScale(scale: Scale): scale is OrdinalScale;
/**
 * @param extent Both extent[0] and extent[1] should be valid number.
 *               Should be extent[0] < extent[1].
 * @param splitNumber splitNumber should be >= 1.
 */
export declare function intervalScaleNiceTicks(extent: number[], spanWithBreaks: number, splitNumber: number, minInterval?: number, maxInterval?: number): intervalScaleNiceTicksResult;
/**
 * The input `niceInterval` should be generated
 * from `nice` method in `src/util/number.ts`, or
 * from `increaseInterval` itself.
 */
export declare function increaseInterval(niceInterval: number): number;
export declare function getIntervalPrecision(niceInterval: number): number;
/**
 * Lookup table to avoid rounding error - if the value before transformed is in `lookup.from[i]`,
 * return `lookup.to[i]` directly without transform.
 * Rounding errors typically arise in logarithm transform, which can cause the tick to be displayed
 * like `5.999999999999999` when it is expected to be `6`.
 */
export declare type ValueTransformLookupOpt = {
    lookup?: {
        from: number[];
        to: number[];
    } | NullUndefined;
};
/**
 * NOTE:
 *  - If `val` is `NaN`, return `NaN`.
 *  - If `val` is `0`, return `-Infinity`.
 *  - If `val` is negative, return `NaN`.
 *
 * @see {DataStore#getDataExtent} It handles non-positive values for logarithm scale.
 */
export declare function logScaleLogTick(val: number, base: number): number;
/**
 * Cumulative rounding errors cause the logarithm operation to become non-invertible by simply exponentiation.
 *  - `Math.pow(10, integer)` itself has no rounding error. But,
 *  - If `linearTickVal` is generated internally by `calcNiceTicks`, it may be still "not nice" (not an integer)
 *    when it is `extent[i]`.
 *  - If `linearTickVal` is generated outside (e.g., by `scaleCalcAlign`) and set by `setExtent`,
 *    `logScaleLogTick` may already have introduced rounding errors even for "nice" values.
 * But invertible is required when the original `extent[i]` need to be respected, or "nice" ticks need to be
 * displayed instead of something like `5.999999999999999`, which is addressed in this function.
 * See also `#4158`.
 *
 * [CAUTION]:
 *  Monotonicity may be broken on extent ends - callers must make sure it does not matter.
 */
export declare function logScalePowTick(linearTickVal: number, base: number, opt: ValueTransformLookupOpt | NullUndefined): number;
/**
 * For `IntervalScale`, convert `rawExtent` to:
 *  - Be no non-finite number.
 *  - Be `extent[0] < extent[1]`- no equal; otherwise, additional handling is required
 *    in "nice" and "align" ticks.
 */
export declare function intervalScaleEnsureValidExtent(rawExtent: number[], fixMinMax: ScaleExtentFixMinMax, rawExtentResult?: ScaleRawExtentResultFinal | NullUndefined): number[];
export declare function extentDiffers(extent1: number[], extent2: number[]): boolean[];
export declare function ensureValidSplitNumber(rawSplitNumber: number | NullUndefined, defaultSplitNumber: number): number;
/**
 * NOTE: The result can have only one item, e.g., when `extent[0] === extent[1]`
 * and `categoryInterval === 0`.
 */
export declare function ordinalScaleCreateTicks(ordinalScale: OrdinalScale, categoryInterval: number, addItem: (tick: ScaleTick, isExtentBoundary: boolean) => void): void;
export {};
