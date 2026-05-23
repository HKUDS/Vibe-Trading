import SingleAxisModel from './AxisModel.js';
import { AxisBuilderCfg } from '../../component/axis/AxisBuilder.js';
interface LayoutResult {
    position: AxisBuilderCfg['position'];
    rotation: AxisBuilderCfg['rotation'];
    labelRotate: AxisBuilderCfg['labelRotate'];
    labelDirection: AxisBuilderCfg['labelDirection'];
    tickDirection: AxisBuilderCfg['tickDirection'];
    nameDirection: AxisBuilderCfg['nameDirection'];
    z2: number;
}
export declare function layout(axisModel: SingleAxisModel, opt?: {
    labelInside?: boolean;
}): LayoutResult;
export {};
