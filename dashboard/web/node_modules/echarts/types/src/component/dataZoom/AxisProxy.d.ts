import GlobalModel from '../../model/Global.js';
import SeriesModel from '../../model/Series.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { NullUndefined } from '../../util/types.js';
import DataZoomModel from './DataZoomModel.js';
import { AxisBaseModel } from '../../coord/AxisBaseModel.js';
import { DataZoomAxisDimension } from './helper.js';
import { ScaleRawExtentResultForZoom } from '../../coord/scaleRawExtentInfo.js';
interface MinMaxSpan {
    minSpan: number;
    maxSpan: number;
    minValueSpan: number;
    maxValueSpan: number;
}
export interface AxisProxyWindow {
    value: ScaleRawExtentResultForZoom;
    percent: number[];
    percentInverted: number[];
    valuePrecision: number;
}
/**
 * Operate single axis.
 * One axis can only operated by one axis operator.
 * Different dataZoomModels may be defined to operate the same axis.
 * (i.e. 'inside' data zoom and 'slider' data zoom components)
 * So dataZoomModels share one axisProxy in that case.
 */
declare class AxisProxy {
    ecModel: GlobalModel;
    private _dimName;
    private _axisIndex;
    private _window;
    private _extent;
    private _minMaxSpan;
    /**
     * The host `dataZoom` model. An axis may be controlled by multiple `dataZoom`s,
     * but only the first declared `dataZoom` is the host.
     */
    private _dataZoomModel;
    constructor(dimName: DataZoomAxisDimension, axisIndex: number, dataZoomModel: DataZoomModel, ecModel: GlobalModel);
    /**
     * Whether the axisProxy is hosted by dataZoomModel.
     */
    hostedBy(dataZoomModel: DataZoomModel): boolean;
    /**
     * @return `getWindow().value` can only have NaN or finite value.
     */
    getWindow(): AxisProxyWindow;
    getTargetSeriesModels(): SeriesModel<import("../../util/types").SeriesOption<unknown, import("../../util/types").DefaultStatesMixin>>[];
    getAxisModel(): AxisBaseModel;
    getMinMaxSpan(): MinMaxSpan;
    /**
     * [CAVEAT] Keep this method pure, so that it can be called multiple times.
     */
    calculateDataWindow(opt: {
        start?: number;
        end?: number;
        startValue?: number | string | Date;
        endValue?: number | string | Date;
    }): AxisProxyWindow;
    /**
     * Notice: reset should not be called before series.restoreData() is called,
     * so it is recommended to be called in "process stage" but not "model init
     * stage".
     */
    reset(dataZoomModel: DataZoomModel, alignToPercentInverted: number[] | NullUndefined): void;
    filterData(dataZoomModel: DataZoomModel, api: ExtensionAPI): void;
    private _updateMinMaxSpan;
}
export default AxisProxy;
