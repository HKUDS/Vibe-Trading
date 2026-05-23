import IntervalScale, { IntervalScaleConfig } from '../scale/Interval.js';
import Scale from '../scale/Scale.js';
import Model from '../model/Model.js';
import { AxisBaseModel } from './AxisBaseModel.js';
import LogScale from '../scale/Log.js';
import type Axis from './Axis.js';
import { AxisBaseOption, CategoryAxisBaseOption, LogAxisBaseOption, AxisBaseOptionCommon, OptionAxisType, CategoryTickLabelSplitBuildingOption } from './axisCommonTypes.js';
import SeriesData from '../data/SeriesData.js';
import { DimensionName, NullUndefined, ScaleTick } from '../util/types.js';
import { ScaleExtentFixMinMax } from './scaleRawExtentInfo.js';
import { AxisModelExtendedInCreator } from './axisModelCreator.js';
export declare function determineAxisType(model: Model<Pick<AxisBaseOption, 'type'>>): OptionAxisType;
export declare function createScaleByModel(model: Model<{
    type?: string;
} & Pick<LogAxisBaseOption, 'logBase'> & Pick<AxisBaseOptionCommon, 'breaks'>> & Partial<Pick<AxisModelExtendedInCreator, 'getOrdinalMeta' | 'getCategories'>>, type: OptionAxisType, coordSysSupportAxisBreaks: boolean): Scale;
/**
 * Check if the axis cross a specific value.
 */
export declare function getScaleValuePositionKind(scale: Scale, value: number, considerMappingExtent: boolean): ScaleValuePositionKind;
export declare type ScaleValuePositionKind = typeof SCALE_VALUE_POSITION_KIND_INSIDE | typeof SCALE_VALUE_POSITION_KIND_EDGE | typeof SCALE_VALUE_POSITION_KIND_OUTSIDE;
export declare const SCALE_VALUE_POSITION_KIND_INSIDE = 1;
export declare const SCALE_VALUE_POSITION_KIND_EDGE = 2;
export declare const SCALE_VALUE_POSITION_KIND_OUTSIDE = 3;
export declare function discourageOnAxisZero(axis: Axis): void;
/**
 * `true`: Prevent orthoganal axes from positioning at the zero point of this axis.
 */
export declare function isOnAxisZeroDiscouraged(axis: Axis): boolean;
/**
 * @param axis
 * @return Label formatter function.
 *         param: {number} tickValue,
 *         param: {number} idx, the index in all ticks.
 *                         If category axis, this param is not required.
 *         return: {string} label string.
 */
export declare function makeLabelFormatter(axis: Axis): (tick: ScaleTick, idx?: number) => string;
export declare function getAxisRawValue<TIsCategory extends boolean>(axis: Axis, tick: ScaleTick): TIsCategory extends true ? string : number;
/**
 * @param model axisLabelModel or axisTickModel
 */
export declare function getOptionCategoryInterval(model: Model<CategoryTickLabelSplitBuildingOption>): CategoryAxisBaseOption['axisLabel']['interval'];
/**
 * Set `categoryInterval` as 0 implicitly indicates that
 * show all labels regardless of overlap.
 * @param {Object} axis axisModel.axis
 */
export declare function shouldShowAllLabels(axis: Axis): boolean;
export declare function getDataDimensionsOnAxis(data: SeriesData, axisDim: string): DimensionName[];
export declare function isNameLocationCenter(nameLocation: AxisBaseOptionCommon['nameLocation']): boolean;
export declare function shouldAxisShow(axisModel: AxisBaseModel): boolean;
export declare function retrieveAxisBreaksOption(model: Model<Pick<AxisBaseOptionCommon, 'breaks'>>, axisType: OptionAxisType, coordSysSupportAxisBreaks: boolean): AxisBaseOptionCommon['breaks'];
export declare function updateIntervalOrLogScaleForNiceOrAligned(scale: IntervalScale | LogScale, fixMinMax: ScaleExtentFixMinMax, oldIntervalExtent: number[], newIntervalExtent: number[], oldOutermostExtent: number[] | NullUndefined, cfg: IntervalScaleConfig): void;
export declare function getTickValueOutermost(scale: Scale, tick: ScaleTick): number;
export declare function isAxisOnBand(scale: Scale, axisModel: AxisBaseModel): boolean;
