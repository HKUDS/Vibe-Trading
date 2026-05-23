import type Axis from '../coord/Axis.js';
import { AxisStatKey } from '../coord/axisStatistics.js';
import { EChartsExtensionInstallRegisters } from '../extension.js';
export declare type BaseBarSeriesSubType = typeof SERIES_TYPE_BAR | typeof SERIES_TYPE_PICTORIAL_BAR;
export declare const SERIES_TYPE_BAR = "bar";
export declare const SERIES_TYPE_PICTORIAL_BAR = "pictorialBar";
export declare function requireAxisStatisticsForBaseBar(registers: EChartsExtensionInstallRegisters, axisStatKey: AxisStatKey, seriesType: BaseBarSeriesSubType, coordSysType: 'cartesian2d' | 'polar'): void;
export declare function getStartValue(baseAxis: Axis): number;
