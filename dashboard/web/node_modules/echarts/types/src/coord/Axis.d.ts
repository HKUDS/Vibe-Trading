import { AxisLabelsComputingContext, AxisLabelInfoDetermined } from './axisTickLabelBuilder.js';
import Scale, { ScaleGetTicksOpt } from '../scale/Scale.js';
import { DimensionName, NullUndefined, ScaleDataValue, ScaleTick } from '../util/types.js';
import Model from '../model/Model.js';
import { AxisBaseOption, AxisTickOptionUnion, CategoryAxisBaseOption, CategoryTickLabelSplitBuildingOption, OptionAxisType } from './axisCommonTypes.js';
import { AxisBaseModel } from './AxisBaseModel.js';
export interface AxisTickCoord {
    coord: number;
    tickValue: ScaleTick['value'];
    onBand?: boolean;
}
/**
 * Base class of Axis.
 *
 * Lifetime: recreate for each main process.
 * [NOTICE]: Some caches is stored on the axis instance (e.g., `axisTickLabelBuilder.ts`, `scaleRawExtentInfo.ts`),
 *  which is based on this lifetime.
 */
declare class Axis {
    /**
     * Axis type
     *  - 'category'
     *  - 'value'
     *  - 'time'
     *  - 'log'
     */
    type: OptionAxisType;
    readonly dim: DimensionName;
    scale: Scale;
    private _extent;
    model: AxisBaseModel;
    onBand: CategoryAxisBaseOption['boundaryGap'];
    inverse: AxisBaseOption['inverse'];
    __alignTo: Axis | NullUndefined;
    constructor(dim: DimensionName, scale: Scale, extent: [number, number]);
    /**
     * If axis extent contain given coord
     */
    contain(coord: number): boolean;
    /**
     * If axis extent contain given data
     */
    containData(data: ScaleDataValue): boolean;
    /**
     * Get coord extent.
     */
    getExtent(): [number, number];
    /**
     * Set coord extent
     */
    setExtent(start: number, end: number): void;
    /**
     * Convert data to coord. Data is the rank if it has an ordinal scale
     */
    dataToCoord(data: ScaleDataValue, clamp?: boolean): number;
    /**
     * Convert coord to data. Data is the rank if it has an ordinal scale
     */
    coordToData(coord: number, clamp?: boolean): number;
    /**
     * Convert pixel point to data in axis
     */
    pointToData(point: number[], clamp?: boolean): number;
    /**
     * Different from `zrUtil.map(axis.getTicks(), axis.dataToCoord, axis)`,
     * `axis.getTicksCoords` considers `onBand`, which is used by
     * `boundaryGap:true` of category axis and splitLine and splitArea.
     * @param opt.tickModel default: axis.model.getModel('axisTick')
     */
    getTicksCoords(opt?: {
        tickModel?: Model<CategoryTickLabelSplitBuildingOption>;
        breakTicks?: ScaleGetTicksOpt['breakTicks'];
        pruneByBreak?: ScaleGetTicksOpt['pruneByBreak'];
    }): AxisTickCoord[];
    getMinorTicksCoords(): AxisTickCoord[][];
    getViewLabels(ctx?: AxisLabelsComputingContext): AxisLabelInfoDetermined[];
    getLabelModel(): Model<AxisBaseOption['axisLabel']>;
    /**
     * Notice here we only get the default tick model. For splitLine
     * or splitArea, we should pass the splitLineModel or splitAreaModel
     * manually when calling `getTicksCoords`.
     * In GL, this method may be overridden to:
     * `axisModel.getModel('axisTick', grid3DModel.getModel('axisTick'));`
     */
    getTickModel(): Model<AxisTickOptionUnion>;
    /**
     * @deprecated Use `calcBandWidth` instead.
     */
    getBandWidth(): number;
    /**
     * Get axis rotate, by degree.
     */
    getRotate: () => number;
    /**
     * Only be called in category axis.
     * Can be overridden, consider other axes like in 3D.
     * @return Auto interval for category axis tick and label
     */
    calculateCategoryInterval(ctx?: AxisLabelsComputingContext): number;
}
export default Axis;
