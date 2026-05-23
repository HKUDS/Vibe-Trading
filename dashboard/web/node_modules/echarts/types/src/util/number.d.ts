import { NullUndefined } from './types.js';
export declare const DEFAULT_PRECISION_FOR_ROUNDING_ERROR = 14;
export declare const mathMin: (...values: number[]) => number;
export declare const mathMax: (...values: number[]) => number;
export declare const mathAbs: (x: number) => number;
export declare const mathRound: (x: number) => number;
export declare const mathFloor: (x: number) => number;
export declare const mathCeil: (x: number) => number;
export declare const mathPow: (x: number, y: number) => number;
export declare const mathLog: (x: number) => number;
export declare const mathLN10: number;
export declare const mathPI: number;
export declare const mathRandom: () => number;
/**
 * Linear mapping a value from domain to range
 * @param  val
 * @param  domain Domain extent domain[0] can be bigger than domain[1]
 * @param  range  Range extent range[0] can be bigger than range[1]
 * @param  clamp Default to be false
 */
export declare function linearMap(val: number, domain: number[], range: number[], clamp?: boolean): number;
/**
 * Preserve the name `parsePercent` for backward compatibility,
 * and it's effectively published as `echarts.number.parsePercent`.
 */
export declare const parsePercent: typeof parsePositionOption;
/**
 * @see {parsePositionSizeOption} and also accept a string preset.
 * @see {PositionSizeOption}
 */
export declare function parsePositionOption(option: unknown, percentBase: number, percentOffset?: number): number;
/**
 * Accept number, or numeric string (`'123'`), or percentage ('100%'), as x/y/width/height pixel number.
 * If null/undefined or invalid, return NaN.
 * (But allow JS type coercion (`+option`) due to backward compatibility)
 * @see {PositionSizeOption}
 */
export declare function parsePositionSizeOption(option: unknown, percentBase: number, percentOffset?: number): number;
/**
 * Perserve the same rule with `parsePositionSizeOption`.
 */
export declare function isPositionSizeOptionPercent(option: unknown): boolean;
/**
 * [Feature_1] Round at specified precision.
 *  FIXME: this is not a general-purpose rounding implementation yet due to `TO_FIXED_SUPPORTED_PRECISION_MAX`.
 *  e.g., `round(1.25 * 1e-150, 151)` has no overflow in IEEE754 64bit float, but can not be handled by
 *  this method.
 *
 * [Feature_2] Support return string to avoid scientific notation like '3.5e-7'.
 *
 * [Feature_3] Fix rounding error of float numbers !!!ONLY SUITABLE FOR SPECIAL CASES!!!.
 *  [CAVEAT]:
 *      Rounding is NEVER a general-purpose solution for rounding errors.
 *      Consider a case: `expect=123.99994999`, `actual=123.99995000` (suppose rounding error occurs).
 *          Calling `round(expect, 4)` gets `123.9999`.
 *          Calling `round(actual, 4)` gets `124.0000`.
 *          A unacceptable result arises, even if the original difference is only `0.00000001` (tiny
 *          and not strongly correlated with the digit pattern).
 *      So the rounding approach works only if:
 *          The digit next to the `precision` won't cross the rounding boundary. Typically, it works if
 *          the digit next to the `precision` is expected to be `0`, and the rounding error is small
 *          enough and impossible to affect that digit (`roundingError < Math.pow(10, -precision) / 2`).
 *      The quantity of a rounding error can be roughly estimated by formula:
 *          `minPrecisionRoundingErrorMayOccur ~= max(0, floor(14 - quantityExponent(val)))`
 *          MEMO: This is derived from:
 *              Let ` EXP52B10 = log10(pow(2, 52)) = 15.65355977452702 `
 *                  (`52` is IEEE754 float64 mantissa bits count)
 *              We require: ` abs(val) * pow(10, precision) < pow(10, EXP52B10) `
 *              Hence: ` precision < EXP52B10 - log10(abs(val)) `
 *              Hence: ` precision = floor( EXP52B10 - log10(abs(val)) ) `
 *              Since: ` quantityExponent(val) = floor(log10(abs(val))) `
 *              Hence: ` precision ~= floor(EXP52B10 - 1 - quantityExponent(val))
 */
export declare function round(x: number | string, precision: number): number;
export declare function round(x: number | string, precision: number, returnStr: false): number;
export declare function round(x: number | string, precision: number, returnStr: true): string;
export declare function roundLegacy(x: number | string, precision?: number): number;
export declare function roundLegacy(x: number | string, precision: number, returnStr: false): number;
export declare function roundLegacy(x: number | string, precision: number, returnStr: true): string;
/**
 * Inplacd asc sort arr.
 * The input arr will be modified.
 */
export declare function asc<T extends number[]>(arr: T): T;
/**
 * Get precision.
 * e.g. `getPrecisionSafe(100.123)` return `3`.
 * e.g. `getPrecisionSafe(100)` return `0`.
 */
export declare function getPrecision(val: string | number): number;
/**
 * Get precision with slow but safe method
 * e.g. `getPrecisionSafe(100.123)` return `3`.
 * e.g. `getPrecisionSafe(100)` return `0`.
 */
export declare function getPrecisionSafe(val: string | number): number;
/**
 * @deprecated Use `getAcceptableTickPrecision` instead. See bad case in `test/ut/spec/util/number.test.ts`
 * NOTE: originally introduced in commit `ff93e3e7f9ff24902e10d4469fd3187393b05feb`
 *
 * Minimal discernible data precision according to a single pixel.
 */
export declare function getPixelPrecision(dataExtent: [number, number], pixelExtent: [number, number]): number;
/**
 * This method chooses a reasonable "data" precision that can be used in `round` method.
 * A reasonable precision is suitable for display; it may cause cumulative error but acceptable.
 *
 * "data" is linearly mapped to pixel according to the ratio determined by `dataSpan` and `pxSpan`.
 * The diff from the original "data" to the rounded "data" (with the result precision) should be
 * equal or less than `pxDiffAcceptable`, which is typically `1` pixel.
 * And the result precision should be as small as possible for a concise display.
 *
 * [NOTICE]: using arbitrary parameters is NOT preferable - a discernible misalign (e.g., over 1px)
 *  may occur, especially when `splitLine` is displayed.
 *
 * PENDING: Only the linear case is addressed for now; other mapping methods (like logarithm) will
 *  not be covered until necessary.
 */
export declare function getAcceptableTickPrecision(dataExtent: number[], pxSpan: number, pxDiffAcceptable: number | NullUndefined): number;
/**
 * Get a data of given precision, assuring the sum of percentages
 * in valueList is 1.
 * The largest remainder method is used.
 * https://en.wikipedia.org/wiki/Largest_remainder_method
 *
 * @param valueList a list of all data
 * @param idx index of the data to be processed in valueList
 * @param precision integer number showing digits of precision
 * @return percent ranging from 0 to 100
 */
export declare function getPercentWithPrecision(valueList: number[], idx: number, precision: number): number;
/**
 * Get a data of given precision, assuring the sum of percentages
 * in valueList is 1.
 * The largest remainder method is used.
 * https://en.wikipedia.org/wiki/Largest_remainder_method
 *
 * @param valueList a list of all data
 * @param precision integer number showing digits of precision
 * @return {Array<number>}
 */
export declare function getPercentSeats(valueList: number[], precision: number): number[];
/**
 * Solve the floating point adding problem like 0.1 + 0.2 === 0.30000000000000004
 * See <http://0.30000000000000004.com/>
 */
export declare function addSafe(val0: number, val1: number): number;
export declare const MAX_SAFE_INTEGER: number;
/**
 * To 0 - 2 * PI, considering negative radian.
 */
export declare function remRadian(radian: number): number;
/**
 * @param {type} radian
 * @return {boolean}
 */
export declare function isRadianAroundZero(val: number): boolean;
/**
 * @param value valid type: number | string | Date, otherwise return `new Date(NaN)`
 *   These values can be accepted:
 *   + An instance of Date, represent a time in its own time zone.
 *   + Or string in a subset of ISO 8601, only including:
 *     + only year, month, date: '2012-03', '2012-03-01', '2012-03-01 05', '2012-03-01 05:06',
 *     + separated with T or space: '2012-03-01T12:22:33.123', '2012-03-01 12:22:33.123',
 *     + time zone: '2012-03-01T12:22:33Z', '2012-03-01T12:22:33+8000', '2012-03-01T12:22:33-05:00',
 *     all of which will be treated as local time if time zone is not specified
 *     (see <https://momentjs.com/>).
 *   + Or other string format, including (all of which will be treated as local time):
 *     '2012', '2012-3-1', '2012/3/1', '2012/03/01',
 *     '2009/6/12 2:00', '2009/6/12 2:05:08', '2009/6/12 2:05:08.123'
 *   + a timestamp, which represent a time in UTC.
 * @return date Never be null/undefined. If invalid, return `new Date(NaN)`.
 */
export declare function parseDate(value: unknown): Date;
/**
 * Quantity of a number. e.g. 0.1, 1, 10, 100
 *
 * @param val
 * @return
 */
export declare function quantity(val: number): number;
/**
 * Exponent of the quantity of a number
 * e.g., 9876 equals to 9.876*10^3, so quantityExponent(9876) is 3
 * e.g., 0.09876 equals to 9.876*10^-2, so quantityExponent(0.09876) is -2
 *
 * @param val non-negative value
 * @return
 */
export declare function quantityExponent(val: number): number;
export declare const NICE_MODE_ROUND: 1;
export declare const NICE_MODE_MIN: 2;
/**
 * find a “nice” number approximately equal to x. Round the number if 'round',
 * take ceiling if 'round'. The primary observation is that the “nicest”
 * numbers in decimal are 1, 2, and 5, and all power-of-ten multiples of these numbers.
 *
 * See "Nice Numbers for Graph Labels" of Graphic Gems.
 *
 * @param  val Non-negative value.
 * @return Niced number
 */
export declare function nice(val: number, mode?: boolean | typeof NICE_MODE_ROUND | typeof NICE_MODE_MIN): number;
/**
 * This code was copied from "d3.js"
 * <https://github.com/d3/d3/blob/9cc9a875e636a1dcf36cc1e07bdf77e1ad6e2c74/src/arrays/quantile.js>.
 * See the license statement at the head of this file.
 * @param ascArr
 */
export declare function quantile(ascArr: number[], p: number): number;
declare type IntervalItem = {
    interval: [number, number];
    close: [0 | 1, 0 | 1];
};
/**
 * Order intervals asc, and split them when overlap.
 * expect(numberUtil.reformIntervals([
 *     {interval: [18, 62], close: [1, 1]},
 *     {interval: [-Infinity, -70], close: [0, 0]},
 *     {interval: [-70, -26], close: [1, 1]},
 *     {interval: [-26, 18], close: [1, 1]},
 *     {interval: [62, 150], close: [1, 1]},
 *     {interval: [106, 150], close: [1, 1]},
 *     {interval: [150, Infinity], close: [0, 0]}
 * ])).toEqual([
 *     {interval: [-Infinity, -70], close: [0, 0]},
 *     {interval: [-70, -26], close: [1, 1]},
 *     {interval: [-26, 18], close: [0, 1]},
 *     {interval: [18, 62], close: [0, 1]},
 *     {interval: [62, 150], close: [0, 1]},
 *     {interval: [150, Infinity], close: [0, 0]}
 * ]);
 * @param list, where `close` mean open or close
 *        of the interval, and Infinity can be used.
 * @return The origin list, which has been reformed.
 */
export declare function reformIntervals(list: IntervalItem[]): IntervalItem[];
/**
 * [Numeric is defined as]:
 *     `parseFloat(val) == val`
 * For example:
 * numeric:
 *     typeof number except NaN, '-123', '123', '2e3', '-2e3', '011', 'Infinity', Infinity,
 *     and they rounded by white-spaces or line-terminal like ' -123 \n ' (see es spec)
 * not-numeric:
 *     null, undefined, [], {}, true, false, 'NaN', NaN, '123ab',
 *     empty string, string with only white-spaces or line-terminal (see es spec),
 *     0x12, '0x12', '-0x12', 012, '012', '-012',
 *     non-string, ...
 *
 * @test See full test cases in `test/ut/spec/util/number.js`.
 * @return Must be a typeof number. If not numeric, return NaN.
 */
export declare function numericToNumber(val: unknown): number;
/**
 * Definition of "numeric": see `numericToNumber`.
 */
export declare function isNumeric(val: unknown): val is number;
/**
 * Use random base to prevent users hard code depending on
 * this auto generated marker id.
 * @return An positive integer.
 */
export declare function getRandomIdBase(): number;
/**
 * Get the greatest common divisor.
 *
 * @param {number} a one number
 * @param {number} b the other number
 */
export declare function getGreatestCommonDividor(a: number, b: number): number;
/**
 * Get the least common multiple.
 *
 * @param {number} a one number
 * @param {number} b the other number
 */
export declare function getLeastCommonMultiple(a: number, b: number): number;
/**
 * NOTICE: Assume the input `val` is number or null/undefined, no type check, no support of BitInt.
 * Therefore, it is NOT suitable for processing user input, but sufficient for
 * internal usage in most cases.
 * For platform-agnosticism, `Number.isFinite` is not used.
 */
export declare function isNullableNumberFinite(val: number | NullUndefined): boolean;
export {};
