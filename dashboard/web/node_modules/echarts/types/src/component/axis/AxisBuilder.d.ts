import * as graphic from '../../util/graphic.js';
import { AxisBaseModel } from '../../coord/AxisBaseModel.js';
import { ParsedAxisBreak, NullUndefined, DimensionName } from '../../util/types.js';
import { AxisBaseOption, AxisBaseOptionCommon } from '../../coord/axisCommonTypes.js';
import { LabelLayoutWithGeometry } from '../../label/labelLayoutHelper.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import Point from 'zrender/lib/core/Point.js';
import { AxisLabelInfoDetermined } from '../../coord/axisTickLabelBuilder.js';
declare type AxisIndexKey = 'xAxisIndex' | 'yAxisIndex' | 'radiusAxisIndex' | 'angleAxisIndex' | 'singleAxisIndex';
declare type AxisEventData = {
    componentType: string;
    componentIndex: number;
    targetType: 'axisName' | 'axisLabel';
    name?: string;
    value?: string | number;
    dataIndex?: number;
    tickIndex?: number;
} & {
    break?: {
        start: ParsedAxisBreak['vmin'];
        end: ParsedAxisBreak['vmax'];
    };
} & {
    [key in AxisIndexKey]?: number;
};
export declare const getLabelInner: (hostObj: graphic.Text) => {
    labelInfo: AxisLabelInfoDetermined;
    layoutRotation: number;
};
/**
 * @see {AxisBuilder}
 */
export interface AxisBuilderCfg {
    /**
     * @mandatory
     * The origin of the axis, in the global pixel coords.
     */
    position: number[];
    /**
     * @mandatory
     * The rotation of the axis from the "standard axis" ([0, 0]-->[abs(axisExtent[1]-axisExtent[0]), 0]).
     * In radian.
     * Like always, a positive rotation represents rotating anticlockwisely from
     * the "standard axis" , and a negative rotation represents clockwise.
     * e.g.,
     * rotation 0 means an axis towards screen-right.
     * rotation Math.PI/4 means an axis towards screen-top-right.
     */
    rotation: number;
    /**
     * `nameDirection` or `tickDirection` or `labelDirection` are used when
     * `nameLocation` is 'middle' or 'center'.
     * values:
     *  - `1` means ticks or labels are below the "standard axis" ([0, 0]-->[abs(axisExtent[1]-axisExtent[0]), 0]).
     *  - `-1` means they are above the "standard axis".
     */
    nameDirection?: -1 | 1;
    tickDirection?: -1 | 1;
    labelDirection?: -1 | 1;
    /**
     * `labelOffset` means the offset between labels and the axis line, which is
     * useful when 'onZero: true', where the axis line is in the grid rect and
     * labels are outside the grid rect.
     */
    labelOffset?: number;
    /**
     * If not specified, get from axisModel.
     */
    axisLabelShow?: boolean;
    /**
     * Works on axisLine.show: 'auto'. true by default.
     */
    axisLineAutoShow?: boolean;
    /**
     * Works on axisTick.show: 'auto'. true by default.
     */
    axisTickAutoShow?: boolean;
    /**
     * default get from axisModel.
     */
    axisName?: string;
    axisNameAvailableWidth?: number;
    /**
     * by degree, default get from axisModel.
     */
    labelRotate?: number;
    strokeContainThreshold?: number;
    nameTruncateMaxWidth?: number;
    silent?: boolean;
    defaultNameMoveOverlap?: boolean;
}
/**
 * Use it prior to `AxisBuilderCfg`. If settings in `AxisBuilderCfg` need to be preprocessed
 * and shared by different methods, put them here.
 */
interface AxisBuilderCfgDetermined {
    raw: AxisBuilderCfg;
    position: AxisBuilderCfg['position'];
    rotation: AxisBuilderCfg['rotation'];
    nameDirection: AxisBuilderCfg['nameDirection'];
    tickDirection: AxisBuilderCfg['tickDirection'];
    labelDirection: AxisBuilderCfg['labelDirection'];
    silent: AxisBuilderCfg['silent'];
    labelOffset: AxisBuilderCfg['labelOffset'];
    axisName: AxisBaseOptionCommon['name'];
    nameLocation: AxisBaseOption['nameLocation'];
    shouldNameMoveOverlap: boolean;
    showMinorTicks: boolean;
    optionHideOverlap: AxisBaseOption['axisLabel']['hideOverlap'];
}
export declare type AxisBuilderSharedContextRecord = {
    dirVec?: Point;
    transGroup?: AxisBuilder['_transformGroup'];
    labelInfoList?: LabelLayoutWithGeometry[];
    stOccupiedRect?: BoundingRect | NullUndefined;
    nameLayout?: LabelLayoutWithGeometry | NullUndefined;
    nameLocation?: AxisBaseOption['nameLocation'];
    ready: Partial<Record<AxisBuilderAxisPartName, boolean>>;
};
/**
 * A context shared by difference axisBuilder instances.
 * For cross-axes overlap resolving.
 *
 * Lifecycle constraint: should not over a pass of ec main process.
 *  If model is changed, the context must be disposed.
 *
 * @see AxisBuilderLocalContext
 */
export declare class AxisBuilderSharedContext {
    /**
     * [CAUTION] Do not modify this data structure outside this class.
     */
    recordMap: {
        [axisDimension: DimensionName]: AxisBuilderSharedContextRecord[];
    };
    constructor(resolveAxisNameOverlap: AxisBuilderSharedContext['resolveAxisNameOverlap']);
    ensureRecord(axisModel: AxisBaseModel): AxisBuilderSharedContextRecord;
    /**
     * Overlap resolution strategy. May vary for different coordinate systems.
     */
    readonly resolveAxisNameOverlap: (cfg: AxisBuilderCfgDetermined, ctx: AxisBuilderSharedContext | NullUndefined, axisModel: AxisBaseModel, nameLayoutInfo: LabelLayoutWithGeometry, // The existing has been ensured.
    nameMoveDirVec: Point, thisRecord: AxisBuilderSharedContextRecord) => void;
}
/**
 * The default resolver does not involve other axes within the same coordinate system.
 */
export declare const resolveAxisNameOverlapDefault: AxisBuilderSharedContext['resolveAxisNameOverlap'];
export declare function moveIfOverlapByLinearLabels(baseLayoutInfoList: LabelLayoutWithGeometry[], baseDirVec: Point, movableLayoutInfo: LabelLayoutWithGeometry, moveDirVec: Point): void;
/**
 * @caution
 * - Ensure it is called after the data processing stage finished.
 * - It might be called before `CahrtView#render`, sush as called at `CoordinateSystem#update`,
 *  thus ensure the result the same whenever it is called.
 *
 * A builder for a straight-line axis.
 *
 * A final axis is translated and rotated from a "standard axis".
 * So opt.position and opt.rotation is required.
 *
 * A "standard axis" is the axis [0,0]-->[abs(axisExtent[1]-axisExtent[0]),0]
 * for example: [0,0]-->[50,0]
 */
declare class AxisBuilder {
    private _axisModel;
    private _cfg;
    private _local;
    private _shared;
    readonly group: graphic.Group;
    /**
     * `_transformGroup.transform` is ready to visit. (but be `NullUndefined` if no transform.)
     */
    private _transformGroup;
    private _api;
    /**
     * [CAUTION]: axisModel.axis.extent/scale must be ready to use.
     */
    constructor(axisModel: AxisBaseModel, api: ExtensionAPI, opt: AxisBuilderCfg, shared?: AxisBuilderSharedContext);
    /**
     * Regarding axis label related configurations, only the change of label.x/y is supported; other
     * changes are not necessary and not performant. To be specific, only `axis.position`
     * (and consequently `labelOffset`) and `axis.extent` can be changed, and assume everything in
     * `axisModel` are not changed.
     * Axis line related configurations can be changed since this method can only be called
     * before they are created.
     */
    updateCfg(opt: Pick<AxisBuilderCfg, 'position' | 'labelOffset'>): void;
    /**
     * [CAUTION] For debug usage. Never change it outside!
     */
    __getRawCfg(): AxisBuilderCfg;
    private _resetCfgDetermined;
    build(axisPartNameMap?: AxisBuilderAxisPartMap, extraParams?: {}): AxisBuilder;
    /**
     * Currently only get text align/verticalAlign by rotation.
     * NO `position` is involved, otherwise it have to be performed for each `updateAxisLabelChangableProps`.
     */
    static innerTextLayout(axisRotation: number, textRotation: number, direction: number): {
        rotation: number;
        textAlign: import("zrender/lib/core/types").TextAlign;
        textVerticalAlign: import("zrender/lib/core/types").TextVerticalAlign;
    };
    static makeAxisEventDataBase(axisModel: AxisBaseModel): AxisEventData;
    static isLabelSilent(axisModel: AxisBaseModel): boolean;
}
declare const AXIS_BUILDER_AXIS_PART_NAMES: readonly ["axisLine", "axisTickLabelEstimate", "axisTickLabelDetermine", "axisName"];
declare type AxisBuilderAxisPartName = typeof AXIS_BUILDER_AXIS_PART_NAMES[number];
export declare type AxisBuilderAxisPartMap = {
    [axisPartName in AxisBuilderAxisPartName]?: boolean;
};
export default AxisBuilder;
