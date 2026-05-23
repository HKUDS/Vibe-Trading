import SeriesModel from '../../model/Series.js';
import { SeriesOption, LineStyleOption, SeriesLabelOption, SymbolOptionMixin, ItemStyleOption, AreaStyleOption, OptionDataValue, StatesOptionMixin, OptionDataItemObject, SeriesEncodeOptionMixin, CallbackDataParams, DefaultStatesMixinEmphasis, SeriesOnRadarOptionMixin } from '../../util/types.js';
import GlobalModel from '../../model/Global.js';
import SeriesData from '../../data/SeriesData.js';
import Radar from '../../coord/radar/Radar.js';
declare type RadarSeriesDataValue = OptionDataValue[];
interface RadarStatesMixin {
    emphasis?: DefaultStatesMixinEmphasis;
}
export interface RadarSeriesStateOption<TCbParams = never> {
    lineStyle?: LineStyleOption;
    areaStyle?: AreaStyleOption;
    label?: SeriesLabelOption;
    itemStyle?: ItemStyleOption<TCbParams>;
}
export interface RadarSeriesDataItemOption extends SymbolOptionMixin, RadarSeriesStateOption<CallbackDataParams>, StatesOptionMixin<RadarSeriesStateOption<CallbackDataParams>, RadarStatesMixin>, OptionDataItemObject<RadarSeriesDataValue> {
}
export interface RadarSeriesOption extends SeriesOption<RadarSeriesStateOption, RadarStatesMixin>, RadarSeriesStateOption, SeriesOnRadarOptionMixin, SymbolOptionMixin<CallbackDataParams>, SeriesEncodeOptionMixin {
    type?: 'radar';
    coordinateSystem?: 'radar';
    data?: (RadarSeriesDataItemOption | RadarSeriesDataValue)[];
}
export declare const SERIES_TYPE_RADAR = "radar";
declare class RadarSeriesModel extends SeriesModel<RadarSeriesOption> {
    static readonly type: string;
    readonly type: string;
    static dependencies: string[];
    coordinateSystem: Radar;
    hasSymbolVisual: boolean;
    init(option: RadarSeriesOption): void;
    getInitialData(option: RadarSeriesOption, ecModel: GlobalModel): SeriesData;
    formatTooltip(dataIndex: number, multipleSeries?: boolean, dataType?: string): import("../../component/tooltip/tooltipMarkup").TooltipMarkupSection;
    getTooltipPosition(dataIndex: number): number[];
    static defaultOption: RadarSeriesOption;
}
export default RadarSeriesModel;
