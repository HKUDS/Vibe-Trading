import { HashMap } from 'zrender/lib/core/util.js';
import type GlobalModel from '../model/Global.js';
import type SeriesModel from '../model/Series.js';
import { ComponentSubType, NullUndefined } from '../util/types.js';
import type Axis from './Axis.js';
import { EChartsExtensionInstallRegisters } from '../extension.js';
import type ComponentModel from '../model/Component.js';
import { CoordinateSystem } from './CoordinateSystem.js';
export declare const AXIS_STAT_KEY_DELIMITER = "|&";
export declare type AxisStatPerKeyPerAxis = {
    axis: Axis;
    sers: SeriesModel[];
    serByIdx: SeriesModel[];
    liPosMinGap?: number | typeof LINEAR_POSITIVE_MIN_GAP_NO_VALID_VALUE | typeof LINEAR_POSITIVE_MIN_GAP_SINGLE_VALID_VALUE | NullUndefined;
    metrics?: AxisStatMetrics;
};
export declare const LINEAR_POSITIVE_MIN_GAP_SINGLE_VALID_VALUE = -2;
export declare const LINEAR_POSITIVE_MIN_GAP_NO_VALID_VALUE = -1;
export declare type AxisStatECPrepareCachePerKeyPerAxis = Pick<AxisStatPerKeyPerAxis, 'liPosMinGap'> & {
    serUids?: HashMap<1, ComponentModel['uid']>;
};
export declare type AxisStatKeyedClient = {
    key: AxisStatKey;
    seriesType: ComponentSubType;
    baseAxis?: boolean | NullUndefined;
    coordSysType?: CoordinateSystem['type'] | NullUndefined;
    getMetrics: (axis: Axis) => AxisStatMetrics | NullUndefined;
};
/**
 * Within each individual axis, different groups of relevant series and statistics are
 * designated by a `AxisStatKey`.
 *
 * `AxisStatKey` is a static definition.
 *  In most case a `seriesType` is used as a `AxisStatKey` (See `makeAxisStatKey`).
 *  Sometimes a `seriesType`+`coordSysType` is used as a `AxisStatKey` (See `makeAxisStatKey2`).
 *
 * A <axis, series> pair can only own to one `AxisStatKey`.
 */
export declare type AxisStatKey = string & {
    _: 'AxisStatKey';
};
export declare type AxisStatMetrics = {
    liPosMinGap?: boolean;
};
export declare type AxisStatisticsResult = Pick<AxisStatPerKeyPerAxis, 'liPosMinGap'>;
declare type AxisStatEachSeriesCb = (seriesModel: SeriesModel) => void;
export declare function getAxisStat(axis: Axis, axisStatKey: AxisStatKey): AxisStatisticsResult;
export declare function getAxisStatBySeries(axis: Axis, seriesList: (SeriesModel | NullUndefined)[]): AxisStatisticsResult[];
export declare function eachSeriesOnAxis(axis: Axis, cb: AxisStatEachSeriesCb): void;
/**
 * NOTE:
 *  - series declaration order is respected (some ec option precedence matters, e.g., bar series).
 *  - series filtered out are excluded.
 */
export declare function eachSeriesOnAxisOnKey(axis: Axis, axisStatKey: AxisStatKey, cb: AxisStatEachSeriesCb): void;
export declare function eachSeriesDealForAxisStat(ecModel: GlobalModel, seriesList: SeriesModel[] | NullUndefined, cb: AxisStatEachSeriesCb): void;
/**
 * NOTE:
 *  - series filtered out are excluded.
 */
export declare function countSeriesOnAxisOnKey(axis: Axis, axisStatKey: AxisStatKey): number;
/**
 * NOTICE: Available after `CoordinateSystem['create']` (not included).
 *
 * Query all axes that have at least one associated series (via `associateSeriesWithAxis`)
 * by the given key.
 */
export declare function eachAxisOnKey(ecModel: GlobalModel, axisStatKey: AxisStatKey, cb: (axis: Axis) => void): void;
/**
 * NOTICE: Available after `CoordinateSystem['create']` (not included).
 *
 * Query all `AxisStatKey`s that have at least one associated series (via `associateSeriesWithAxis`)
 * by the given axis.
 */
export declare function eachKeyOnAxis(axis: Axis, cb: (axisStatKey: AxisStatKey) => void): void;
export declare function registerMetricImpl(metricType: keyof AxisStatMetrics, impl: AxisStateMetricImpl): void;
declare type AxisStateMetricImpl = (ecModel: GlobalModel, perKeyPerAxis: AxisStatPerKeyPerAxis, ecPreparePerKeyPerAxis: AxisStatECPrepareCachePerKeyPerAxis) => void;
/**
 * NOTICE:
 *  - It must be called in `CoordinateSystem['create']`, before series filtering.
 *  - It must be called in `seriesIndex` ascending order (series declaration order).
 *    i.e., iterated by `ecModel.eachSeries`.
 *  - Every <axis, series> pair can only call this method once.
 *
 * @see scaleRawExtentInfoCreate in `scaleRawExtentInfo.ts`
 */
export declare function associateSeriesWithAxis(axis: Axis | NullUndefined, seriesModel: SeriesModel, coordSysType: CoordinateSystem['type']): void;
/**
 * NOTICE: Can only be called in "install" stage.
 *
 * See `axisSnippets.ts` for some commonly used clients.
 */
export declare function requireAxisStatistics(registers: EChartsExtensionInstallRegisters, client: AxisStatKeyedClient): void;
export {};
