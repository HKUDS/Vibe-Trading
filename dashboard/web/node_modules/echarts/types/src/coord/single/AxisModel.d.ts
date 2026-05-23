import ComponentModel from '../../model/Component.js';
import { AxisModelExtendedInCreator } from '../axisModelCreator.js';
import { AxisModelCommonMixin } from '../axisModelCommonMixin.js';
import Single from './Single.js';
import SingleAxis from './SingleAxis.js';
import { AxisBaseOption } from '../axisCommonTypes.js';
import { BoxLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, LayoutOrient } from '../../util/types.js';
import { AxisBaseModel } from '../AxisBaseModel.js';
export declare const COORD_SYS_TYPE_SINGLE = "single";
export declare const COORD_SYS_TYPE_SINGLE_AXIS_COMPATIBLE = "singleAxis";
export declare const COMPONENT_TYPE_SINGLE_AXIS = "singleAxis";
export declare type SingleAxisPosition = 'top' | 'bottom' | 'left' | 'right';
export declare type SingleAxisOption = AxisBaseOption & BoxLayoutOptionMixin & {
    mainType?: 'singleAxis';
    position?: SingleAxisPosition;
    orient?: LayoutOrient;
} & ComponentOnCalendarOptionMixin & ComponentOnMatrixOptionMixin;
declare class SingleAxisModel extends ComponentModel<SingleAxisOption> implements AxisBaseModel<SingleAxisOption> {
    static type: string;
    type: string;
    static readonly layoutMode = "box";
    axis: SingleAxis;
    coordinateSystem: Single;
    getCoordSysModel(): this;
    static defaultOption: SingleAxisOption;
}
interface SingleAxisModel extends AxisModelCommonMixin<SingleAxisOption>, AxisModelExtendedInCreator {
}
export default SingleAxisModel;
