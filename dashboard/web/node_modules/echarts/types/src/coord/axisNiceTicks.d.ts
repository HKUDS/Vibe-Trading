import type { AxisBaseModel } from './AxisBaseModel.js';
import type { NumericAxisBaseOptionCommon } from './axisCommonTypes.js';
import Scale from '../scale/Scale.js';
import { ScaleExtentFixMinMax, ScaleRawExtentResultFinal } from './scaleRawExtentInfo.js';
import { NullUndefined } from '../util/types.js';
import type GlobalModel from '../model/Global.js';
import type Axis from './Axis.js';
export declare type ScaleCalcNiceMethod = (scale: Scale, opt: ScaleCalcNiceMethodOpt) => void;
declare type ScaleCalcNiceMethodOpt = {
    splitNumber?: number | NullUndefined;
    minInterval?: number | NullUndefined;
    maxInterval?: number | NullUndefined;
    userInterval?: number | NullUndefined;
    userIntervalUseLegacy?: boolean | NullUndefined;
    fixMinMax?: ScaleExtentFixMinMax | NullUndefined;
    rawExtentResult?: ScaleRawExtentResultFinal | NullUndefined;
};
/**
 * NOTE: See the summary of the process of extent determination in the comment of `scaleMapper.setExtent`.
 *
 * Calculate a "nice" extent and "nice" ticks configs based on the current scale extent and ec options.
 * scale extent will be modified, and config may be set to the scale.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare function scaleCalcNice(axisLike: {
    scale: Scale;
    model: AxisBaseModel;
}): void;
/**
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export declare function scaleCalcNice2(scale: Scale, model: AxisBaseModel<NumericAxisBaseOptionCommon>, axis: Axis | NullUndefined, ecModel: GlobalModel | NullUndefined, externalDataExtent: number[] | NullUndefined): void;
export declare function scaleCalcNiceDirectly(scale: Scale, opt: ScaleCalcNiceMethodOpt): void;
export {};
