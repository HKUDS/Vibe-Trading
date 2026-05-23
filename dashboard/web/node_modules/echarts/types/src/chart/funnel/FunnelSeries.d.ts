import SeriesModel from '../../model/Series.js';
import { SeriesOption, BoxLayoutOptionMixin, HorizontalAlign, LabelOption, LabelLineOption, ItemStyleOption, OptionDataValueNumeric, StatesOptionMixin, OptionDataItemObject, LayoutOrient, VerticalAlign, SeriesLabelOption, SeriesEncodeOptionMixin, DefaultStatesMixinEmphasis, CallbackDataParams, ComponentOnMatrixOptionMixin, ComponentOnCalendarOptionMixin } from '../../util/types.js';
import GlobalModel from '../../model/Global.js';
import SeriesData from '../../data/SeriesData.js';
declare type FunnelLabelOption = Omit<SeriesLabelOption, 'position'> & {
    position?: LabelOption['position'] | 'outer' | 'inner' | 'center' | 'rightTop' | 'rightBottom' | 'leftTop' | 'leftBottom';
};
interface FunnelStatesMixin {
    emphasis?: DefaultStatesMixinEmphasis;
}
export interface FunnelCallbackDataParams extends CallbackDataParams {
    percent: number;
}
export interface FunnelStateOption<TCbParams = never> {
    itemStyle?: ItemStyleOption<TCbParams>;
    label?: FunnelLabelOption;
    labelLine?: LabelLineOption;
}
export interface FunnelDataItemOption extends FunnelStateOption, StatesOptionMixin<FunnelStateOption, FunnelStatesMixin>, OptionDataItemObject<OptionDataValueNumeric> {
    itemStyle?: ItemStyleOption & {
        width?: number | string;
        height?: number | string;
    };
}
export interface FunnelSeriesOption extends SeriesOption<FunnelStateOption<FunnelCallbackDataParams>, FunnelStatesMixin>, FunnelStateOption<FunnelCallbackDataParams>, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, BoxLayoutOptionMixin, SeriesEncodeOptionMixin {
    type?: 'funnel';
    min?: number;
    max?: number;
    /**
     * Absolute number or percent string
     */
    minSize?: number | string;
    maxSize?: number | string;
    sort?: 'ascending' | 'descending' | 'none';
    orient?: LayoutOrient;
    gap?: number;
    funnelAlign?: HorizontalAlign | VerticalAlign;
    data?: (OptionDataValueNumeric | OptionDataValueNumeric[] | FunnelDataItemOption)[];
}
export declare const SERIES_TYPE_FUNNEL = "funnel";
declare class FunnelSeriesModel extends SeriesModel<FunnelSeriesOption> {
    static readonly type: string;
    readonly type: string;
    init(option: FunnelSeriesOption): void;
    getInitialData(this: FunnelSeriesModel, option: FunnelSeriesOption, ecModel: GlobalModel): SeriesData;
    _defaultLabelLine(option: FunnelSeriesOption): void;
    getDataParams(dataIndex: number): FunnelCallbackDataParams;
    static defaultOption: FunnelSeriesOption;
}
export default FunnelSeriesModel;
