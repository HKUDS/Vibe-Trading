import { ComponentOption, CircleLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin } from '../../util/types.js';
import ComponentModel from '../../model/Component.js';
import type Polar from './Polar.js';
import { AngleAxisModel, RadiusAxisModel } from './AxisModel.js';
export interface PolarOption extends ComponentOption, CircleLayoutOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin {
    mainType?: 'polar';
}
export declare const COORD_SYS_TYPE_POLAR = "polar";
export declare const COMPONENT_TYPE_POLAR = "polar";
declare class PolarModel extends ComponentModel<PolarOption> {
    static type: string;
    type: string;
    static dependencies: string[];
    coordinateSystem: Polar;
    findAxisModel(axisType: 'angleAxis'): AngleAxisModel;
    findAxisModel(axisType: 'radiusAxis'): RadiusAxisModel;
    static defaultOption: PolarOption;
}
export default PolarModel;
