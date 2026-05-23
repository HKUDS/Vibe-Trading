import Axis from '../../coord/Axis.js';
import Scale from '../../scale/Scale.js';
import TimelineModel from './TimelineModel.js';
import { LabelOption } from '../../util/types.js';
import Model from '../../model/Model.js';
export declare type TimelineAxisType = 'category' | 'time' | 'value';
/**
 * Extend axis 2d
 */
declare class TimelineAxis extends Axis {
    type: TimelineAxisType;
    model: TimelineModel;
    constructor(dim: string, scale: Scale, coordExtent: [number, number], axisType: TimelineAxisType);
    /**
     * @override
     */
    getLabelModel(): Model<LabelOption<{
        positionExtra: never;
    }>>;
    /**
     * @override
     */
    isHorizontal(): boolean;
}
export default TimelineAxis;
