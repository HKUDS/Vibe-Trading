import type Axis from '../coord/Axis.js';
import Axis2D from '../coord/cartesian/Axis2D.js';
import type SingleAxis from '../coord/single/SingleAxis.js';
import type SeriesModel from '../model/Series.js';
export declare function needFixJitter(seriesModel: SeriesModel, axis: Axis): boolean;
export declare type JitterData = {
    fixedCoord: number;
    floatCoord: number;
    r: number;
};
/**
 * Fix jitter for overlapping data points.
 *
 * @param fixedAxis The axis whose coord doesn't change with jitter.
 * @param fixedCoord The coord of fixedAxis.
 * @param floatCoord The coord of the other axis, which should be changed with jittering.
 * @param radius The radius of the data point, considering the symbol is a circle.
 * @returns updated floatCoord.
 */
export declare function fixJitter(fixedAxis: Axis2D | SingleAxis, fixedCoord: number, floatCoord: number, radius: number): number;
