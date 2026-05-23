import { LayoutRect } from '../../util/layout.js';
import Cartesian2D from './Cartesian2D.js';
import Axis2D from './Axis2D.js';
import { ParsedModelFinder } from '../../util/model.js';
import GridModel from './GridModel.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { CoordinateSystemMaster } from '../CoordinateSystem.js';
import { ScaleDataValue } from '../../util/types.js';
declare type Cartesian2DDimensionName = 'x' | 'y';
declare type FinderAxisIndex = {
    xAxisIndex?: number;
    yAxisIndex?: number;
};
declare class Grid implements CoordinateSystemMaster {
    readonly type: string;
    private _coordsMap;
    private _coordsList;
    private _axesMap;
    private _axesList;
    private _rect;
    readonly model: GridModel;
    readonly axisPointerEnabled = true;
    name: string;
    static dimensions: string[];
    readonly dimensions: string[];
    static dimIdxMap: import("zrender/lib/core/util").HashMap<number, string>;
    constructor(gridModel: GridModel, ecModel: GlobalModel, api: ExtensionAPI);
    getRect(): LayoutRect;
    update(ecModel: GlobalModel, api: ExtensionAPI): void;
    /**
     * Resize the grid.
     *
     * [NOTE]
     * If both "grid.containLabel/grid.contain" and pixel-required-data-processing (such as, "dataSampling")
     * exist, circular dependency occurs in logic.
     * The final compromised sequence is:
     *  1. Calculate "axis.extent" (pixel extent) and AffineTransform based on only "grid layout options".
     *      Not accurate if "grid.containLabel/grid.contain" is required, but it is a compromise to avoid
     *      circular dependency.
     *  2. Perform "series data processing" (where "dataSampling" requires "axis.extent").
     *  3. Calculate "scale.extent" (data extent) based on "processed series data".
     *  4. Modify "axis.extent" for "grid.containLabel/grid.contain":
     *      4.1. Calculate "axis labels" based on "scale.extent".
     *      4.2. Modify "axis.extent" by the bounding rects of "axis labels and names".
     */
    resize(gridModel: GridModel, api: ExtensionAPI, beforeDataProcessing?: boolean): void;
    getAxis(dim: Cartesian2DDimensionName, axisIndex?: number): Axis2D;
    getAxes(): Axis2D[];
    /**
     * Usage:
     *      grid.getCartesian(xAxisIndex, yAxisIndex);
     *      grid.getCartesian(xAxisIndex);
     *      grid.getCartesian(null, yAxisIndex);
     *      grid.getCartesian({xAxisIndex: ..., yAxisIndex: ...});
     *
     * When only xAxisIndex or yAxisIndex given, find its first cartesian.
     */
    getCartesian(finder: FinderAxisIndex): Cartesian2D;
    getCartesian(xAxisIndex?: number, yAxisIndex?: number): Cartesian2D;
    getCartesians(): Cartesian2D[];
    /**
     * @implements
     */
    convertToPixel(ecModel: GlobalModel, finder: ParsedModelFinder, value: ScaleDataValue | ScaleDataValue[]): number | number[];
    /**
     * @implements
     */
    convertFromPixel(ecModel: GlobalModel, finder: ParsedModelFinder, value: number | number[]): number | number[];
    private _findConvertTarget;
    /**
     * @implements
     */
    containPoint(point: number[]): boolean;
    /**
     * Initialize cartesian coordinate systems
     */
    private _initCartesian;
    /**
     * @param dim 'x' or 'y' or 'auto' or null/undefined
     */
    getTooltipAxes(dim: Cartesian2DDimensionName | 'auto'): {
        baseAxes: Axis2D[];
        otherAxes: Axis2D[];
    };
    static create(ecModel: GlobalModel, api: ExtensionAPI): Grid[];
}
export declare type LegacyLayOutGridByContainLabel = (axesList: Axis2D[], gridRect: LayoutRect) => void;
export declare function registerLegacyGridContainLabelImpl(impl: LegacyLayOutGridByContainLabel): void;
export default Grid;
