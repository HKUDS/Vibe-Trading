import Axis2D from '../coord/cartesian/Axis2D.js';
import { StageHandler, NullUndefined } from '../util/types.js';
import { EChartsExtensionInstallRegisters } from '../extension.js';
import { AxisBandWidthResult } from '../coord/axisBand.js';
import { BaseBarSeriesSubType } from './barCommon.js';
interface BarGridLayoutAxisInfo {
    seriesInfo: BarGridLayoutAxisSeriesInfo[];
    bandWidthResult: AxisBandWidthResult;
}
interface BarGridLayoutAxisSeriesInfo {
    barWidth: number;
    barMaxWidth: number;
    barMinWidth: number;
    barGap: number | string;
    defaultBarGap?: number | string;
    barCategoryGap: number | string;
    stackId: StackId;
}
declare type StackId = string & {
    _: 'barGridStackId';
};
export interface BarGridLayoutOptionForCustomSeries {
    count: number;
    barWidth?: number | string;
    barMaxWidth?: number | string;
    barMinWidth?: number | string;
    barGap?: number | string;
    barCategoryGap?: number | string;
}
interface BarGridLayoutOption extends BarGridLayoutOptionForCustomSeries {
    axis: Axis2D;
}
declare type BarWidthAndOffsetOnAxis = Record<StackId, BarGridLayoutResultItemInternal>;
export declare type BarGridColumnLayoutOnAxis = BarGridLayoutAxisInfo & {
    columnMap: BarWidthAndOffsetOnAxis;
};
declare type BarGridLayoutResultItemInternal = {
    bandWidth: BarGridLayoutAxisInfo['bandWidthResult']['w'];
    offset: number;
    width: number;
};
declare type BarGridLayoutResultItem = BarGridLayoutResultItemInternal & {
    offsetCenter: number;
};
export declare type BarGridLayoutResultForCustomSeries = BarGridLayoutResultItem[] | NullUndefined;
/**
 * Return null/undefined if not 'category' axis.
 *
 * PENDING: The layout on non-'category' axis relies on `bandWidth`, which is calculated
 * based on the `linearPositiveMinGap` of series data. This strategy is somewhat heuristic
 * and will not be public to custom series until required in future. Additionally, more ec
 * options may be introduced for that, because it requires `requireAxisStatistics` to be
 * called on custom series that requires this feature.
 */
export declare function computeBarLayoutForCustomSeries(opt: BarGridLayoutOption): BarGridLayoutResultForCustomSeries;
export declare function createCrossSeriesLayoutHandler(seriesType: BaseBarSeriesSubType): StageHandler;
export declare function createProgressiveLayout(seriesType: string): StageHandler;
export declare function registerBarGridAxisHandlers(registers: EChartsExtensionInstallRegisters): void;
export {};
