/**
 * Helper for model references.
 * There are many manners to refer axis/coordSys.
 */
import { HashMap } from 'zrender/lib/core/util.js';
import SeriesModel from './Series.js';
import type { AxisBaseModel } from '../coord/AxisBaseModel.js';
import { AxisBaseOptionCommon } from '../coord/axisCommonTypes.js';
/**
 * @class
 * For example:
 * {
 *     coordSysName: 'cartesian2d',
 *     coordSysDims: ['x', 'y', ...],
 *     axisMap: HashMap({
 *         x: xAxisModel,
 *         y: yAxisModel
 *     }),
 *     categoryAxisMap: HashMap({
 *         x: xAxisModel,
 *         y: undefined
 *     }),
 *     // The index of the first category axis in `coordSysDims`.
 *     // `null/undefined` means no category axis exists.
 *     firstCategoryDimIndex: 1,
 *     // To replace user specified encode.
 * }
 */
export declare class SeriesModelCoordSysInfo {
    coordSysName: string;
    coordSysDims: string[];
    axisMap: HashMap<AxisBaseModel<AxisBaseOptionCommon>, string | number>;
    categoryAxisMap: HashMap<AxisBaseModel<AxisBaseOptionCommon>, string | number>;
    firstCategoryDimIndex: number;
    constructor(coordSysName: string);
}
export declare function getCoordSysInfoBySeries(seriesModel: SeriesModel): SeriesModelCoordSysInfo;
