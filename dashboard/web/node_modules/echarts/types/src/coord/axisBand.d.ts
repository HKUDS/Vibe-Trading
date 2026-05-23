import { NullUndefined } from '../util/types.js';
import type Axis from './Axis.js';
import { AxisStatKey } from './axisStatistics.js';
import type SeriesModel from '../model/Series.js';
export declare type AxisBandWidthResult = {
    w: number;
    w2: number;
};
declare type CalculateBandWidthOpt = {
    fromStat?: {
        key?: AxisStatKey;
        sers?: (SeriesModel | NullUndefined)[] | NullUndefined;
    };
    min?: number;
};
/**
 * NOTICE:
 *  - Require the axis pixel extent and the scale extent as inputs. But they
 *    can be not precise for approximation.
 *  - Can only be called after "data processing" stage.
 *
 * PENDING:
 *  Currently `bandWidth` can not be specified by users explicitly. But if we
 *  allow that in future, these issues must be considered:
 *    - Can only allow specifying a band width in data scale rather than pixel.
 *    - LogScale needs to be considered - band width can only be specified on linear
 *      (but before break) scale, similar to `axis.interval`.
 *
 * A band is required on:
 *  - series group band width in bar/boxplot/candlestick/...;
 *  - tooltip axisPointer type "shadow";
 *  - etc.
 */
export declare function calcBandWidth(axis: Axis, opt?: CalculateBandWidthOpt | NullUndefined): AxisBandWidthResult;
export {};
