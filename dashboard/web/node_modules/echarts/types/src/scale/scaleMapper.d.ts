import { NullUndefined } from '../util/types.js';
import { AxisBreakParsingResult, BreakScaleMapper } from './break.js';
import type { ValueTransformLookupOpt } from './helper.js';
import { DataSanitizationFilter } from '../data/helper/dataValueHelper.js';
/**
 * Illustration:
 *  SCALE_EXTENT_KIND_EFFECTIVE:     |------------|     (always exist)
 *  SCALE_EXTENT_KIND_MAPPING:   |---|------------|--|  (present only when it is specified by `setExtent2`)
 *
 *  - [SCALE_EXTENT_KIND_EFFECTIVE]:
 *    It is a portion of a scale extent that is functional on most features, including:
 *      - All tick/label-related calculation.
 *      - `dataZoom` controlled ends.
 *      - Cartesian2D `clampData`.
 *      - line series start.
 *      - heatmap series range.
 *      - markerArea range.
 *      - etc.
 *    `SCALE_EXTENT_KIND_EFFECTIVE` always exists.
 *
 *  - [SCALE_EXTENT_KIND_MAPPING]:
 *    It is an expanded extent from ends of `SCALE_EXTENT_KIND_EFFECTIVE` to accommodate shapes at edges to
 *    avoid overflow. They can be typically used by bar/candlestick series on category axis with
 *    `boundaryGap: false`, or on other numeric axes. ec option `xxxAxis.containShape` is the switch.
 *    In this case, we need to:
 *      - Do not render ticks and labels in the portion "SCALE_EXTENT_KIND_MAPPING - SCALE_EXTENT_KIND_EFFECTIVE",
 *        since they are considered meaningless there.
 *      - Prevent "nice strategy" from triggering unexpectedly by the "contain shape expansion".
 *        Otherwise, for example, the original extent is `[0, 1000]`, then the expanded
 *        extent, say `[-5, 1000]`, can cause a considerable negative expansion by "nice",
 *        like `[-200, 10000]`, which is commonly unexpected. And it is exacerbated in LogScale.
 *      - Prevent the min/max tick label from displaying, since they are commonly meaningless
 *        and probably misleading.
 *    Therefore, `SCALE_EXTENT_KIND_MAPPING` is only used for:
 *      - mapping between data and pixel, such as,
 *        - `scaleMapper.normalize/scale`;
 *        - Cartesian2D `calcAffineTransform` (a quick path of `scaleMapper.normalize/scale`).
 *      - `grid` boundary related calculation in view rendering, such as, `barGrid` calculates
 *        `barWidth` for numeric scales based on the data extent.
 *      - Axis line position determination (such as `canOnZeroToAxis`);
 *      - `axisPointer` triggering (otherwise users may be confused if using `SCALE_EXTENT_KIND_EFFECTIVE`).
 *    `SCALE_EXTENT_KIND_MAPPING` can be absent, which can be used to determine whether it is used.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare type ScaleExtentKind = typeof SCALE_EXTENT_KIND_EFFECTIVE | typeof SCALE_EXTENT_KIND_MAPPING;
export declare const SCALE_EXTENT_KIND_EFFECTIVE = 0;
export declare const SCALE_EXTENT_KIND_MAPPING = 1;
/**
 * - [SCALE_MAPPER_DEPTH_OUT_OF_BREAK]:
 *   In `transformIn`, it transforms a value from the outermost space to the space before break being applied.
 *   In `transformOut`, it transforms a value from the space before break being applied to the outermost space.
 *   Typically nice axis ticks are picked in that space due to the current design of nice ticks
 *   algorithm, while size related features may use `SCALE_MAPPER_DEPTH_INNERMOST`.
 * - [SCALE_MAPPER_DEPTH_INNERMOST]:
 *   Currently only linear space is used as the innermost space.
 */
export declare type ScaleMapperDepthOpt = {
    depth?: NullUndefined | typeof SCALE_MAPPER_DEPTH_OUT_OF_BREAK | typeof SCALE_MAPPER_DEPTH_INNERMOST;
};
export declare const SCALE_MAPPER_DEPTH_OUT_OF_BREAK = 2;
export declare const SCALE_MAPPER_DEPTH_INNERMOST = 3;
export declare type ScaleMapperTransformOutOpt = (ScaleMapperDepthOpt & ValueTransformLookupOpt);
export declare type ScaleMapperTransformInOpt = ScaleMapperDepthOpt;
/**
 * @tutorial [SCALE_COMPOSITION_AND_TRANSFORMATION]:
 *  `ScaleMapper` is designed for multiple steps of numeric transformations from a certain space to a linear space,
 *  or vice versa. Each steps is implemented as a `ScaleMapper`, and composed like a decorator pattern. And some
 *  steps, such as "axis breaks transfromation", can be skipped when no breaks for performance consideration.
 *  Currently we support:
 *    - step#0: extent based linear scaling.
 *              This is implemented in `LinearScaleMapper`.
 *              It is mixed into `IntervalScale`, `TimeScale`;
 *              and it is also composited into `BreakScaleMapper`, `OrdinalScale`, `LogScale`.
 *    - step#1: axis breaks.
 *              This is implemented in `BreakScaleMapper`.
 *              This step may be absent if no breaks.
 *    - step#2: logarithmic (implemented in `LogScale`), or
 *              ordinal-related handling, or
 *              others to be supported, such as asinh ...
 *  Illustration of some currently supported cases:
 *    - linear_space(in an IntervalScale)
 *    - break_space(in an IntervalScale method bound by a BreakScaleMapper)
 *       └─break_transform─► linear_space(in a LinearScaleMapper owned by a BreakScaleMapper)
 *    - log_space(in a LogScale)
 *       └─log_transform─► linear_space(in an IntervalScale)
 *    - log_space(in a LogScale)
 *       └─log_transform─► break_space(in an IntervalScale method bound by a BreakScaleMapper)
 *                          └─break_transform─► linear_space(in a LinearScaleMapper owned by a BreakScaleMapper)
 *    - linear_space(in a TimeScale)
 *    - break_space(in a TimeScale method bound by a BreakScaleMapper)
 *       └─break_transform─► linear_space(in a LinearScaleMapper owned by a BreakScaleMapper)
 *    - category_values(in a OrdinalScale)
 *       └─category_to_numeric─► linear_space(in a LinearScaleMapper owned by a BreakScaleMapper)
 *
 *
 * @tutorial [SCALE_EXTENT_CONSTRUCTION]:
 *  The full construction processing of the scale extent in EC_FULL_UPDATE_CYCLE:
 *  - step#1. At `CoordinateSystem#create` stage, requirements of collecting series data extents are
 *            committed to `associateSeriesWithAxis`, and `Scale` instances are created.
 *  - step#2. Call `scaleRawExtentInfoCreate` to really collect series data extent and create
 *            `ScaleRawExtentInfo` instances to manage extent related configurations
 *              - at "data processing" stage for dataZoom controlled axes, if any, or
 *              - at "CoordinateSystem#update" stage for all other axes.
 *  - step#3. Perform "nice" (see `scaleCalcNice`) or "align" (see `scaleCalcAlign`) strategies to
 *            modify the original extent from `ScaleRawExtentInfo` instance, if needed, at
 *            "CoordinateSystem#update" stage.
 *  - step#4. `calcContainShape` is performed. Set `SCALE_EXTENT_KIND_MAPPING` if needed.
 *            See AXIS_CONTAIN_SHAPE_PROCESSING_ORDER for more details.
 *
 */
export interface ScaleMapper extends ScaleMapperGeneric<ScaleMapper> {
}
export interface ScaleMapperGeneric<This> {
    /**
     * Enable a fast path in large data traversal - the call of `transformIn`/`transformOut`
     * can be omitted, and this is the most case.
     */
    needTransform(this: This): boolean;
    /**
     * Normalize a value to linear [0, 1], return 0.5 if extent span is 0.
     * The typical logic is:
     *  `transformIn_self` -> `transformIn_inner` -> ... to the innermost space,
     *  then do linear normalization based on innermost extent.
     */
    normalize: (this: This, val: number) => number;
    /**
     * Scale a normalized value to extent. It's the inverse of `normalize`.
     */
    scale: (this: This, val: number) => number;
    /**
     * [NOTICE]:
     *  - This method must be available since the instance is constructed.
     *  - This method has nothing to do with extent - transforming out of extent is supported.
     *
     * This method transforms a value forward into a inner space.
     * The typical logic is:
     *  `transformIn_self` -> `transformIn_inner` -> ... to the innermost space.
     * In most cases axis ticks are laid out in linear space, and some features
     * (such as LogScale, axis breaks) transform values from their own spaces into linear space.
     */
    transformIn: (this: This, val: number, opt: ScaleMapperTransformInOpt | NullUndefined) => number;
    /**
     * [NOTICE]:
     *  - This method must be available since the instance is constructed.
     *  - This method has nothing to do with extent - transforming out of extent is supported.
     *
     * The inverse method of `transformIn`.
     */
    transformOut: (this: This, val: number, opt: ScaleMapperTransformOutOpt | NullUndefined) => number;
    /**
     * Whether the extent contains the given value.
     */
    contain: (this: This, val: number) => boolean;
    /**
     * [NOTICE]:
     *  In EC_FULL_UPDATE_CYCLE, scale extent is finally determined at `coordSys#update` stage.
     *
     * Get a clone of the scale extent.
     * An extent is always in an increase order.
     * It always returns an array - never be a null/undefined.
     *
     * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
     */
    getExtent(this: This): number[];
    /**
     * [NOTICE]:
     *  Callers must NOT modify the return.
     *
     * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
     */
    getExtentUnsafe(this: This, kind: ScaleExtentKind, depth: ScaleMapperDepthOpt['depth'] | NullUndefined): number[] | NullUndefined;
    /**
     * [NOTICE]:
     *  The caller must ensure `start <= end` and both are finite number!
     *
     * `setExtent` is identical to `setExtent2(SCALE_EXTENT_KIND_EFFECTIVE)`.
     *
     * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
     */
    setExtent(this: This, start: number, end: number): void;
    setExtent2(this: This, kind: ScaleExtentKind, start: number, end: number): void;
    /**
     * Filter for sanitization.
     */
    getFilter?: () => DataSanitizationFilter;
    /**
     * NOTICE:
     *  - Should not sanitize invalid values (e.g., NaN, Infinity, null, undefined),
     *    since it probably has special meaning, and always properly handled in every Scale.
     *  - Should not depend on the current `extent`, since it can be used before `extent` determined.
     *
     * Sanitize a value if possible. For example, for LogScale, the negative part will be clampped.
     * This provides some permissiveness to ec option like `xxxAxis.min/max`.
     */
    sanitize?: ((this: This, value: number | NullUndefined, dataExtent: number[]) => number | NullUndefined) | NullUndefined;
    /**
     * If not provided, use `0`.
     */
    getDefaultStartValue?: (() => number) | NullUndefined;
    /**
     * Restrict the modification behavior of a scale for robustness. e.g., avoid subsequently
     * modifying `SCALE_EXTENT_KIND_EFFECTIVE` but no sync to `SCALE_EXTENT_KIND_MAPPING`.
     */
    freeze(this: This): void;
}
export declare function initBreakOrLinearMapper(mapper: ScaleMapper | NullUndefined, breakParsed: AxisBreakParsingResult | NullUndefined, initialExtent: number[] | NullUndefined): {
    brk: BreakScaleMapper | NullUndefined;
    mapper: ScaleMapper;
};
export declare type DecoratedScaleMapperMethods<THost extends ScaleMapper> = Omit<ScaleMapperGeneric<THost>, 'freeze'>;
export declare function decorateScaleMapper<THost extends ScaleMapper>(host: THost, decoratedMapperMethods: Omit<ScaleMapperGeneric<THost>, 'freeze'>): void;
export declare function enableScaleMapperFreeze(host: ScaleMapper, subMapper: ScaleMapper): void;
export declare function getScaleExtentForTickUnsafe(mapper: ScaleMapper): number[];
export declare function getScaleExtentForMappingUnsafe(mapper: ScaleMapper, depth: ScaleMapperDepthOpt['depth'] | NullUndefined): number[];
export declare function getScaleLinearSpanForMapping(mapper: ScaleMapper): number;
export declare function getScaleLinearSpanEffective(mapper: ScaleMapper): number;
export declare function initLinearScaleMapper(mapper: ScaleMapper | NullUndefined, initialExtent: number[] | NullUndefined): ScaleMapper;
