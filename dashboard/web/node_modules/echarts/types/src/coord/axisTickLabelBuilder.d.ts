import type Axis from './Axis.js';
import Model from '../model/Model.js';
import { CategoryTickLabelSplitBuildingOption } from './axisCommonTypes.js';
import { ScaleTick } from '../util/types.js';
import { ScaleGetTicksOpt } from '../scale/Scale.js';
export declare type AxisLabelInfoDetermined = {
    formattedLabel: string;
    rawLabel: string;
    tick: ScaleTick;
};
interface AxisCategoryTicksCreated {
    ticks: ScaleTick[];
    tickCategoryInterval?: number;
}
declare type AxisTicksCreated = AxisCategoryTicksCreated;
export declare const AxisTickLabelComputingKind: {
    readonly estimate: 1;
    readonly determine: 2;
};
export declare type AxisTickLabelComputingKind = (typeof AxisTickLabelComputingKind)[keyof typeof AxisTickLabelComputingKind];
export interface AxisLabelsComputingContext {
    out: {
        noPxChangeTryDetermine: (() => boolean)[];
    };
    kind: AxisTickLabelComputingKind;
}
export declare function createAxisLabelsComputingContext(kind: AxisTickLabelComputingKind): AxisLabelsComputingContext;
/**
 * CAUTION: Do not modify the result.
 */
export declare function createAxisLabels(axis: Axis, ctx: AxisLabelsComputingContext): {
    labels: AxisLabelInfoDetermined[];
};
/**
 * CAUTION: Do not modify the result.
 *
 * @param tickModel For example, can be axisTick, splitLine, splitArea.
 */
export declare function createAxisTicks(axis: Axis, tickModel: Model<CategoryTickLabelSplitBuildingOption>, opt?: Pick<ScaleGetTicksOpt, 'breakTicks' | 'pruneByBreak'>): AxisTicksCreated;
/**
 * Calculate interval for category axis ticks and labels.
 * Use a strategy to try to avoid overlapping.
 * To get precise result, at least one of `getRotate` and `isHorizontal`
 * should be implemented in axis.
 */
export declare function calculateCategoryInterval(axis: Axis, ctx: AxisLabelsComputingContext): number;
export {};
