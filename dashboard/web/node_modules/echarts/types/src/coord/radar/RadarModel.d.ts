import ComponentModel from '../../model/Component.js';
import { ComponentOption, CircleLayoutOptionMixin, LabelOption, ColorString, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin } from '../../util/types.js';
import { AxisBaseOption, CategoryAxisBaseOption, ValueAxisBaseOption } from '../axisCommonTypes.js';
import { AxisBaseModel } from '../AxisBaseModel.js';
import type Radar from './Radar.js';
import { CoordinateSystemHostModel } from '../../coord/CoordinateSystem.js';
export declare const COORD_SYS_TYPE_RADAR = "radar";
export declare const COMPONENT_TYPE_RADAR = "radar";
export declare const SERIES_TYPE_RADAR = "radar";
export declare const RADAR_DEFAULT_SPLIT_NUMBER = 5;
export interface RadarIndicatorOption {
    name?: string;
    /**
     * @deprecated Use `name` instead.
     */
    text?: string;
    min?: number;
    max?: number;
    color?: ColorString;
    axisType?: 'value' | 'log';
}
export interface RadarOption extends ComponentOption, CircleLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin {
    mainType?: 'radar';
    startAngle?: number;
    clockwise?: boolean;
    shape?: 'polygon' | 'circle';
    axisLine?: AxisBaseOption['axisLine'];
    axisTick?: AxisBaseOption['axisTick'];
    axisLabel?: AxisBaseOption['axisLabel'];
    splitLine?: AxisBaseOption['splitLine'];
    splitArea?: AxisBaseOption['splitArea'];
    axisName?: {
        show?: boolean;
        formatter?: string | ((name?: string, indicatorOpt?: InnerIndicatorAxisOption) => string);
    } & LabelOption;
    axisNameGap?: number;
    triggerEvent?: boolean;
    scale?: boolean;
    splitNumber?: number;
    boundaryGap?: CategoryAxisBaseOption['boundaryGap'] | ValueAxisBaseOption['boundaryGap'];
    indicator?: RadarIndicatorOption[];
}
export declare type InnerIndicatorAxisOption = AxisBaseOption & {
    showName?: boolean;
};
declare class RadarModel extends ComponentModel<RadarOption> implements CoordinateSystemHostModel {
    static readonly type = "radar";
    readonly type = "radar";
    coordinateSystem: Radar;
    private _indicatorModels;
    optionUpdated(): void;
    getIndicatorModels(): AxisBaseModel<InnerIndicatorAxisOption>[];
    static defaultOption: RadarOption;
}
export default RadarModel;
