import { SeriesOption, SeriesOnCartesianOptionMixin, SeriesOnPolarOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, SeriesOnGeoOptionMixin, SeriesOnSingleOptionMixin, OptionDataValue, RoamOptionMixin, SeriesLabelOption, ItemStyleOption, LineStyleOption, SymbolOptionMixin, BoxLayoutOptionMixin, CircleLayoutOptionMixin, SeriesLineLabelOption, StatesOptionMixin, GraphEdgeItemObject, OptionDataValueNumeric, CallbackDataParams, DefaultEmphasisFocus } from '../../util/types.js';
import SeriesModel from '../../model/Series.js';
import GlobalModel from '../../model/Global.js';
import SeriesData from '../../data/SeriesData.js';
import Graph from '../../data/Graph.js';
import { LineDataVisual } from '../../visual/commonVisualTypes.js';
interface ExtraEmphasisState {
    /**
     * For focus on nodes:
     * - self: Focus self node, and all edges connected to it.
     * - adjacency: Focus self nodes and two edges (source and target)
     *   connected to the focused node.
     *
     * For focus on edges:
     * - self: Focus self edge, and all nodes connected to it.
     * - adjacency: Focus self edge and all edges connected to it and all
     *   nodes connected to these edges.
     */
    focus?: DefaultEmphasisFocus | 'adjacency';
}
interface ChordStatesMixin {
    emphasis?: ExtraEmphasisState;
}
interface ChordEdgeStatesMixin {
    emphasis?: ExtraEmphasisState;
}
declare type ChordDataValue = OptionDataValue | OptionDataValue[];
export interface ChordItemStyleOption<TCbParams = never> extends ItemStyleOption<TCbParams> {
    borderRadius?: (number | string)[] | number | string;
}
export interface ChordNodeStateOption<TCbParams = never> {
    itemStyle?: ChordItemStyleOption<TCbParams>;
    label?: ChordNodeLabelOption;
}
export interface ChordNodeItemOption extends ChordNodeStateOption, StatesOptionMixin<ChordNodeStateOption, ChordStatesMixin> {
    id?: string;
    name?: string;
    value?: ChordDataValue;
}
export interface ChordEdgeLineStyleOption extends LineStyleOption {
    curveness?: number;
}
export interface ChordNodeLabelOption extends Omit<SeriesLabelOption<CallbackDataParams>, 'position'> {
    silent?: boolean;
    position?: SeriesLabelOption['position'] | 'outside';
}
export interface ChordEdgeStateOption {
    lineStyle?: ChordEdgeLineStyleOption;
    label?: SeriesLineLabelOption;
}
export interface ChordEdgeItemOption extends ChordEdgeStateOption, StatesOptionMixin<ChordEdgeStateOption, ChordEdgeStatesMixin>, GraphEdgeItemObject<OptionDataValueNumeric> {
    value?: number;
}
export interface ChordSeriesOption extends SeriesOption<ChordNodeStateOption<CallbackDataParams>, ChordStatesMixin>, SeriesOnCartesianOptionMixin, SeriesOnPolarOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, SeriesOnGeoOptionMixin, SeriesOnSingleOptionMixin, SymbolOptionMixin<CallbackDataParams>, RoamOptionMixin, BoxLayoutOptionMixin, CircleLayoutOptionMixin {
    type?: 'chord';
    coordinateSystem?: 'none';
    legendHoverLink?: boolean;
    clockwise?: boolean;
    startAngle?: number;
    endAngle?: number | 'auto';
    padAngle?: number;
    minAngle?: number;
    data?: (ChordNodeItemOption | ChordDataValue)[];
    nodes?: (ChordNodeItemOption | ChordDataValue)[];
    edges?: ChordEdgeItemOption[];
    links?: ChordEdgeItemOption[];
    edgeLabel?: SeriesLineLabelOption;
    label?: ChordNodeLabelOption;
    itemStyle?: ChordItemStyleOption<CallbackDataParams>;
    lineStyle?: ChordEdgeLineStyleOption;
    emphasis?: {
        focus?: Exclude<ChordNodeItemOption['emphasis'], undefined>['focus'];
        scale?: boolean | number;
        label?: SeriesLabelOption;
        edgeLabel?: SeriesLabelOption;
        itemStyle?: ItemStyleOption;
        lineStyle?: LineStyleOption;
    };
    blur?: {
        label?: SeriesLabelOption;
        edgeLabel?: SeriesLabelOption;
        itemStyle?: ItemStyleOption;
        lineStyle?: LineStyleOption;
    };
    select?: {
        label?: SeriesLabelOption;
        edgeLabel?: SeriesLabelOption;
        itemStyle?: ItemStyleOption;
        lineStyle?: LineStyleOption;
    };
}
export declare const SERIES_TYPE_CHORD = "chord";
declare class ChordSeriesModel extends SeriesModel<ChordSeriesOption> {
    static readonly type: string;
    readonly type: string;
    init(option: ChordSeriesOption): void;
    mergeOption(option: ChordSeriesOption): void;
    getInitialData(option: ChordSeriesOption, ecModel: GlobalModel): SeriesData;
    getGraph(): Graph;
    getEdgeData(): SeriesData<ChordSeriesModel, LineDataVisual>;
    formatTooltip(dataIndex: number, multipleSeries: boolean, dataType: string): import("../../component/tooltip/tooltipMarkup").TooltipMarkupNameValueBlock;
    getDataParams(dataIndex: number, dataType: 'node' | 'edge'): CallbackDataParams;
    static defaultOption: ChordSeriesOption;
}
export default ChordSeriesModel;
