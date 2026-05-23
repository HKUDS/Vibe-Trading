import PieSeriesModel from './PieSeries.js';
export declare const pieLayoutStageHandler: import("../../util/types").StageHandler;
export declare const getSeriesLayoutData: (hostObj: PieSeriesModel) => {
    startAngle: number;
    endAngle: number;
    clockwise: boolean;
    cx: number;
    cy: number;
    r: number;
    r0: number;
};
