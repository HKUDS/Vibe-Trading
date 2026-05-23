import type Axis from '../../coord/Axis.js';
import { AxisStatKey, AxisStatMetrics } from '../../coord/axisStatistics.js';
import { CoordinateSystem } from '../../coord/CoordinateSystem.js';
import { AxisContainShapeHandler } from '../../coord/scaleRawExtentInfo.js';
import { ComponentSubType } from '../../util/types.js';
/**
 * Require `requireAxisStatistics`.
 *
 * Simply expand `Scale` extent by half bandWidth.
 * Do nothing if an `OrdinalScale` has `boundaryGap: true`.
 */
export declare function createBandWidthBasedAxisContainShapeHandler(axisStatKey: AxisStatKey): AxisContainShapeHandler;
/**
 * A pre-built `makeAxisStatKey`.
 * See `makeAxisStatKey2`. Use two functions rather than a optional parameter to impose checking.
 */
export declare function makeAxisStatKey(seriesType: ComponentSubType): AxisStatKey;
export declare function makeAxisStatKey2(seriesType: ComponentSubType, coordSysType: CoordinateSystem['type']): AxisStatKey;
/**
 * A pre-built `getMetrics`.
 */
export declare function createMetricsNonOrdinalLinearPositiveMinGap(axis: Axis): AxisStatMetrics;
