import { HashMap } from 'zrender/lib/core/util.js';
import Scale from '../scale/Scale.js';
import { AxisBaseModel } from './AxisBaseModel.js';
import { DimensionIndex, DimensionName, NullUndefined } from '../util/types.js';
import type GlobalModel from '../model/Global.js';
import type Axis from './Axis.js';
import { AxisStatKey } from './axisStatistics.js';
export declare const AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE = 1;
export declare const AXIS_EXTENT_INFO_BUILD_FROM_DATA_ZOOM = 2;
declare const AXIS_EXTENT_INFO_BUILD_FROM_EMPTY = 3;
export declare type AxisExtentInfoBuildFrom = typeof AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE | typeof AXIS_EXTENT_INFO_BUILD_FROM_DATA_ZOOM | typeof AXIS_EXTENT_INFO_BUILD_FROM_EMPTY;
/**
 * It is originally created as `ScaleRawExtentResultFinal['fixMinMax']` and may be
 * modified in the subsequent process.
 * It suggests axes to use `scaleRawExtentResult.min/max` directly as their bounds,
 * instead of expanding the extent by some "nice strategy". But axes may refuse to
 * comply with it in some special cases, for example, when their scale extents are
 * invalid, or when they need to be expanded to visually contain series bars.
 *
 * In `ScaleRawExtentResultFinal['fixMinMax']`, it is `true` iff:
 *  - ec option `xxxAxis.min/max` are specified, or
 *  - `scaleRawExtentResult.zoomFixMinMax[]` are `true`.
 *  - `min` `max` are expanded by `AxisContainShapeHandler`.
 *
 * In the subsequent process, it may be modified to `true` for customization.
 */
export declare type ScaleExtentFixMinMax = boolean[];
/**
 * Return the min max before `dataZoom` applied.
 * This is `noZoomEffMM`, corresponding to `SCALE_EXTENT_KIND_EFFECTIVE`.
 */
export declare type ScaleRawExtentResultForZoom = number[];
export declare type ScaleRawExtentResultFinal = Pick<ScaleRawExtentInternal, 'fixMM' | 'zoomFixMM' | 'isBlank' | 'incl0' | 'tggAxInv' | 'ctnShp'> & {
    effMM: number[];
};
declare type ScaleRawExtentResultOthers = Pick<ScaleRawExtentInternal, 'startValue'>;
/**
 * CAVEAT: MUST NOT be modified outside!
 */
interface ScaleRawExtentInternal {
    scale: Scale;
    noZoomEffMM: number[];
    dataMM: number[];
    zoomMM: (number | NullUndefined)[];
    fixMM: ScaleExtentFixMinMax;
    zoomFixMM: ScaleExtentFixMinMax;
    startValue: number | NullUndefined;
    isBlank: boolean;
    incl0: boolean;
    tggAxInv: boolean;
    ctnShp: boolean;
}
export declare type AxisContainShapeHandler = (axis: Axis, ecModel: GlobalModel) => number[] | NullUndefined;
export declare class ScaleRawExtentInfo {
    private _i;
    readonly from: AxisExtentInfoBuildFrom;
    constructor(scale: Scale, model: AxisBaseModel, dataExtent: number[], requireStartValue: boolean, requireContainShape: boolean);
    makeNoZoom(): ScaleRawExtentResultForZoom;
    makeFinal(): ScaleRawExtentResultFinal;
    makeRenderInfo(): ScaleRawExtentResultOthers;
    /**
     * NOTICE:
     *  - Do not set them if the percent are 0% or 100%. (See `AxisProxy['reset']`.)
     *  - The caller must ensure `start <= end` and the range is equal or less then `noZoomEffMM`.
     *    (See `AxisProxy['calculateDataWindow']`.)
     *  - The outcome `_zoomMM` may have both `NullUndefined` and a finite value, like `[undefined, 123]`.
     */
    setZoomMM(idxMinMax: 0 | 1, val: number | NullUndefined): void;
}
/**
 * This supports union extent on case like: pie (or other similar series)
 * lays out on cartesian2d.
 * @see scaleRawExtentInfoCreate
 */
export declare function scaleRawExtentInfoEnableBoxCoordSysUsage(axisLike: {
    scale: Scale;
    dim: DimensionName;
}, coordSysDimIdxMap: HashMap<DimensionIndex, DimensionName> | NullUndefined): void;
/**
 * @usage
 *  class SomeCoordSys {
 *      static create() {
 *          ecModel.eachSeries(function (seriesModel) {
 *              associateSeriesWithAxis(axis1, seriesModel, ...);
 *              associateSeriesWithAxis(axis2, seriesModel, ...);
 *              // ...
 *          });
 *      }
 *      update() {
 *          scaleRawExtentInfoCreate(axis1);
 *          scaleRawExtentInfoCreate(axis2);
 *      }
 *  }
 *  class AxisProxy {
 *      reset() {
 *          scaleRawExtentInfoCreate(axis1);
 *      }
 *  }
 *
 * NOTICE:
 *  - `associateSeriesWithAxis`(in `axisStatistics.ts`) should be called in:
 *    - Coord sys create method.
 *  - `scaleRawExtentInfoCreate` should be typically called in:
 *    - `dataZoom` processor. It requires processing like:
 *      1. Filter series data by dataZoom1;
 *      2. Union the filtered data and init the extent of the orthogonal axes, which is the 100% of dataZoom2;
 *      3. Filter series data by dataZoom2;
 *      4. ...
 *    - Coord sys update method, for other axes that not covered by `dataZoom`.
 *      NOTE: If a `dataZoom` covers this series, this data and its extent has been dataZoom-filtered.
 *      Therefore this handling should not before `dataZoom`.
 *  - The callback of `min`/`max` in ec option should NOT be called multiple times,
 *    therefore, we initialize `ScaleRawExtentInfo` uniformly in `scaleRawExtentInfoCreate`.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare function scaleRawExtentInfoCreate(axis: Axis, from: AxisExtentInfoBuildFrom): void;
/**
 * See `axisSnippets.ts` for some commonly used handlers.
 *
 * FIXME:
 *  `boundaryGap: true` (i.e., `onBand: true` in code) has long been supported on category axis.
 *  And it is implemented in different code and not merged to this implementation yet.
 */
export declare function registerAxisContainShapeHandler(axisStatKey: AxisStatKey, handler: AxisContainShapeHandler): void;
/**
 * Prepare axis scale extent before "nice".
 * Item of returned array can only be number (including Infinity and NaN).
 */
export declare function adoptScaleRawExtentInfoAndPrepare(scale: Scale, model: AxisBaseModel, ecModel: GlobalModel | NullUndefined, axis: Axis | NullUndefined, externalDataExtent: number[] | NullUndefined): ScaleRawExtentResultFinal;
/**
 * This implements ec option `someAxis.containShape`. That is, expand scale extent slightly to
 * ensure shapes of specific series are fully contained in the axis extent without overflow.
 *
 * NOTICE:
 *  Scale extent (data extent) and axis pixel extent (pixel extent) and are required as inputs.
 *    - See BAND_WIDTH_USED_SCALE_LINEAR_SPAN.
 *    - Axis pixel extent has been set outside, though it may be modified later (e.g., via `outerBounds`).
 *
 * @tutorial [AXIS_CONTAIN_SHAPE_PROCESSING_ORDER]
 *  This is a trade-off between the following 2 approaches:
 *    - Steps: (the current implementation)
 *        1. Process `dataZoom` based on a full window `noZoomEffMM`.
 *        2. Perform "nice" or "align" scale, where `intervalScaleEnsureValidExtent`-ish may be performed to
 *           expand extent to avoid `extent[0] === extent[1]`.
 *        3. Calculate linear supplement of containShape based on the final result.
 *      Cons:
 *        - Abrupt changes occur when zooming away from 0% or 100%.
 *        - Edge shapes are clipped in "dataZoom shadow".
 *    - Steps: (discarded)
 *        1. Calculate linear supplement of containShape based on `noZoomEffMM` and
 *           `intervalScaleEnsureValidExtent`-ish.
 *        2. Process `dataZoom` based on a full window `noZoomEffMM + linearSupplement`.
 *        3. Perform "nice"/"align" scale.
 *      Cons:
 *        - Input `startValue: 0` (in ec option or action) does not corresponds to `0%`, which is unacceptable.
 *        - Not easy to perform `intervalScaleEnsureValidExtent`-ish before "nice"/"align" processing.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare function adoptScaleExtentKindMapping(axis: Axis, scale: Scale, rawExtentResult: ScaleRawExtentResultFinal, ecModel: GlobalModel): void;
export {};
