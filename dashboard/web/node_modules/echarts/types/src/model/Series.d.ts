import * as zrUtil from 'zrender/lib/core/util.js';
import { DataHost, DimensionName, SeriesOption, ZRColor, ScaleDataValue, SeriesDataType, OptionEncodeValue, ColorBy, DimensionLoose } from '../util/types.js';
import ComponentModel from './Component.js';
import { PaletteMixin } from './mixin/palette.js';
import { DataFormatMixin } from '../model/mixin/dataFormat.js';
import Model from '../model/Model.js';
import GlobalModel from './Global.js';
import { CoordinateSystem } from '../coord/CoordinateSystem.js';
import { ExtendableConstructor, Constructor } from '../util/clazz.js';
import { PipelineContext, SeriesTask, Pipeline } from '../core/Scheduler.js';
import LegendVisualProvider from '../visual/LegendVisualProvider.js';
import SeriesData from '../data/SeriesData.js';
import Axis from '../coord/Axis.js';
import type { BrushCommonSelectorsForSeries, BrushSelectableArea } from '../component/brush/selector.js';
import makeStyleMapper from './mixin/makeStyleMapper.js';
import { SourceManager } from '../data/helper/sourceManager.js';
import { Source } from '../data/Source.js';
import { ECSymbol } from '../util/symbol.js';
import { Group } from '../util/graphic.js';
import { LegendIconParams } from '../component/legend/LegendModel.js';
import { dimPermutations } from '../component/marker/MarkAreaView.js';
import type ChartView from '../view/Chart.js';
export declare const SERIES_UNIVERSAL_TRANSITION_PROP = "__universalTransitionEnabled";
/**
 * NOTICE:
 *  - prefix `__` can be used to avoid conflicts with possible outside subclasses.
 *  - All of these methods are optional - null-check is needed.
 */
interface SeriesModel {
    preventIncremental(): boolean;
    __preparePipelineContext(view: ChartView, pipeline: Pick<Pipeline, 'progressiveEnabled' | 'threshold'>): PipelineContext;
    /**
     * If `true`, a default `startValue` (`0`) is used if not specified in ec option,
     * and axis extent will union it.
     * Otherwise, `startValue` will be included in the union of axis extent only if
     * it is explicitly specified in ec option.
     *
     * @see {AxisBaseOptionCommon['startValue']} for more info.
     */
    __requireStartValue(axis: Axis): boolean;
    /**
     * See tooltip.
     * Implement it if needed.
     * @return Point of tooltip. null/undefined can be returned.
     */
    getTooltipPosition(dataIndex: number): number[];
    /**
     * Get data indices for show tooltip content. See tooltip.
     * Implement it if needed.
     */
    getAxisTooltipData(dim: DimensionName[], value: ScaleDataValue, baseAxis: Axis): {
        dataIndices: number[];
        nestestValue: any;
    };
    /**
     * Get position for marker
     */
    getMarkerPosition(value: ScaleDataValue[], dims?: typeof dimPermutations[number], startingAtTick?: boolean): number[];
    /**
     * Get legend icon symbol according to each series type
     */
    getLegendIcon(opt: LegendIconParams): ECSymbol | Group;
    /**
     * See `component/brush/selector.js`
     * Defined the brush selector for this series.
     */
    brushSelector(dataIndex: number, data: SeriesData, selectors: BrushCommonSelectorsForSeries, area: BrushSelectableArea): boolean;
    enableAriaDecal(): void;
}
declare class SeriesModel<Opt extends SeriesOption = SeriesOption> extends ComponentModel<Opt> {
    type: string;
    defaultOption: SeriesOption;
    seriesIndex: number;
    coordinateSystem: CoordinateSystem;
    dataTask: SeriesTask;
    pipelineContext: PipelineContext;
    legendVisualProvider: LegendVisualProvider;
    visualStyleAccessPath: string;
    visualDrawType: 'fill' | 'stroke';
    visualStyleMapper: ReturnType<typeof makeStyleMapper>;
    ignoreStyleOnData: boolean;
    hasSymbolVisual: boolean;
    defaultSymbol: string;
    legendIcon: string;
    [SERIES_UNIVERSAL_TRANSITION_PROP]: boolean;
    private _selectedDataIndicesMap;
    readonly preventUsingHoverLayer: boolean;
    static protoInitialize: void;
    init(option: Opt, parentModel: Model, ecModel: GlobalModel): void;
    /**
     * Util for merge default and theme to option
     */
    mergeDefaultAndTheme(option: Opt, ecModel: GlobalModel): void;
    mergeOption(newSeriesOption: Opt, ecModel: GlobalModel): void;
    fillDataTextStyle(data: ArrayLike<any>): void;
    /**
     * Init a data structure from data related option in series
     * Must be overridden.
     */
    getInitialData(option: Opt, ecModel: GlobalModel): SeriesData;
    /**
     * Append data to list
     */
    appendData(params: {
        data: ArrayLike<any>;
    }): void;
    /**
     * Consider some method like `filter`, `map` need make new data,
     * We should make sure that `seriesModel.getData()` get correct
     * data in the stream procedure. So we fetch data from upstream
     * each time `task.perform` called.
     */
    getData(dataType?: SeriesDataType): SeriesData<this>;
    getAllData(): ({
        data: SeriesData;
        type?: SeriesDataType;
    })[];
    setData(data: SeriesData): void;
    getEncode(): zrUtil.HashMap<OptionEncodeValue, string>;
    getSourceManager(): SourceManager;
    getSource(): Source;
    /**
     * Get data before processed
     */
    getRawData(): SeriesData;
    getColorBy(): ColorBy;
    isColorBySeries(): boolean;
    /**
     * Get base axis if has coordinate system and has axis.
     * By default use coordSys.getBaseAxis();
     * Can be overridden for some chart.
     * @return {type} description
     */
    getBaseAxis(): Axis;
    /**
     * Retrieve the index of nearest value in the view coordinate.
     * Data position is compared with each axis's dataToCoord.
     *
     * @param axisDim axis dimension
     * @param dim data dimension
     * @param value
     * @param [maxDistance=Infinity] The maximum distance in view coordinate space
     * @return If and only if multiple indices has
     *         the same value, they are put to the result.
     */
    indicesOfNearest(axisDim: DimensionName, dim: DimensionLoose, value: number, maxDistance?: number): number[];
    /**
     * Default tooltip formatter
     *
     * @param dataIndex
     * @param multipleSeries
     * @param dataType
     * @param renderMode valid values: 'html'(by default) and 'richText'.
     *        'html' is used for rendering tooltip in extra DOM form, and the result
     *        string is used as DOM HTML content.
     *        'richText' is used for rendering tooltip in rich text form, for those where
     *        DOM operation is not supported.
     * @return formatted tooltip with `html` and `markers`
     *        Notice: The override method can also return string
     */
    formatTooltip(dataIndex: number, multipleSeries?: boolean, dataType?: SeriesDataType): ReturnType<DataFormatMixin['formatTooltip']>;
    isAnimationEnabled(): boolean;
    restoreData(): void;
    getColorFromPalette(name: string, scope: any, requestColorNum?: number): ZRColor;
    /**
     * Use `data.mapDimensionsAll(coordDim)` instead.
     * @deprecated
     */
    coordDimToDataDim(coordDim: DimensionName): DimensionName[];
    /**
     * Get progressive rendering count each step
     */
    getProgressive(): number | false;
    /**
     * Get progressive rendering count each step
     */
    getProgressiveThreshold(): number;
    select(innerDataIndices: number[], dataType?: SeriesDataType): void;
    unselect(innerDataIndices: number[], dataType?: SeriesDataType): void;
    toggleSelect(innerDataIndices: number[], dataType?: SeriesDataType): void;
    getSelectedDataIndices(): number[];
    isSelected(dataIndex: number, dataType?: SeriesDataType): boolean;
    isUniversalTransitionEnabled(): boolean;
    private _innerSelect;
    private _initSelectedMapFromData;
    static registerClass(clz: Constructor): Constructor;
}
interface SeriesModel<Opt extends SeriesOption = SeriesOption> extends DataFormatMixin, PaletteMixin<Opt>, DataHost {
    /**
     * Get dimension to render shadow in dataZoom component
     */
    getShadowDim?(): string;
}
export declare type SeriesModelConstructor = typeof SeriesModel & ExtendableConstructor;
export default SeriesModel;
