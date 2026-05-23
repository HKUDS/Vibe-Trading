import SeriesModel from '../../model/Series.js';
import { WhiskerBoxCommonMixin } from '../helper/whiskerBoxCommon.js';
import { SeriesOption, SeriesOnCartesianOptionMixin, LayoutOrient, ItemStyleOption, ZRColor, ColorString, SeriesLabelOption, SeriesLargeOptionMixin, StatesOptionMixin, SeriesEncodeOptionMixin, DefaultEmphasisFocus, OptionDataValue } from '../../util/types.js';
import SeriesData from '../../data/SeriesData.js';
import Cartesian2D from '../../coord/cartesian/Cartesian2D.js';
import { BrushCommonSelectorsForSeries } from '../../component/brush/selector.js';
import type Axis2D from '../../coord/cartesian/Axis2D.js';
declare type CandlestickDataValue = OptionDataValue[];
interface CandlestickItemStyleOption extends ItemStyleOption {
    color0?: ZRColor;
    borderColor0?: ColorString;
    borderColorDoji?: ZRColor;
}
export interface CandlestickStateOption {
    itemStyle?: CandlestickItemStyleOption;
    label?: SeriesLabelOption;
}
export interface CandlestickDataItemOption extends CandlestickStateOption, StatesOptionMixin<CandlestickStateOption, ExtraStateOption> {
    cursor?: string;
    value: CandlestickDataValue;
}
interface ExtraStateOption {
    emphasis?: {
        focus?: DefaultEmphasisFocus;
        scale?: boolean;
    };
}
export interface CandlestickSeriesOption extends SeriesOption<CandlestickStateOption, ExtraStateOption>, CandlestickStateOption, SeriesOnCartesianOptionMixin, SeriesLargeOptionMixin, SeriesEncodeOptionMixin {
    type?: 'candlestick';
    coordinateSystem?: 'cartesian2d';
    layout?: LayoutOrient;
    clip?: boolean;
    barMaxWidth?: number | string;
    barMinWidth?: number | string;
    barWidth?: number | string;
    data?: (CandlestickDataValue | CandlestickDataItemOption)[];
}
export declare const SERIES_TYPE_CANDLESTICK = "candlestick";
declare class CandlestickSeriesModel extends SeriesModel<CandlestickSeriesOption> {
    static readonly type: string;
    readonly type: string;
    static readonly dependencies: string[];
    coordinateSystem: Cartesian2D;
    dimensions: string[];
    defaultValueDimensions: {
        name: string;
        defaultTooltip: boolean;
    }[];
    static defaultOption: CandlestickSeriesOption;
    /**
     * Get dimension for shadow in dataZoom
     * @return dimension name
     */
    getShadowDim(): string;
    brushSelector(dataIndex: number, data: SeriesData, selectors: BrushCommonSelectorsForSeries): boolean;
}
interface CandlestickSeriesModel extends WhiskerBoxCommonMixin<CandlestickSeriesOption> {
    getBaseAxis(): Axis2D;
}
export default CandlestickSeriesModel;
