import Scale, { ScaleGetTicksOpt } from './Scale.js';
import { IntervalScaleGetLabelOpt } from './helper.js';
import { ScaleTick, ScaleDataValue, NullUndefined, AxisBreakOption } from '../util/types.js';
import { AxisBreakParsingResult } from './break.js';
import { ScaleMapperGeneric } from './scaleMapper.js';
export declare type IntervalScaleConfig = {
    interval: IntervalScaleConfigParsed['interval'];
    intervalPrecision?: IntervalScaleConfigParsed['intervalPrecision'] | NullUndefined;
    intervalCount?: IntervalScaleConfigParsed['intervalCount'] | NullUndefined;
    niceExtent?: IntervalScaleConfigParsed['niceExtent'] | NullUndefined;
};
declare type IntervalScaleConfigParsed = {
    /**
     * Step of ticks.
     */
    interval: number;
    intervalPrecision: number;
    /**
     * `_intervalCount` effectively specifies the number of "nice segments". This is for special cases,
     * such as `alignTicks: true` and min max are fixed. In this case, `_interval` may be specified with
     * a "not-nice" value and needs to be rounded with `_intervalPrecision` for better appearance. Then
     * merely accumulating `_interval` may generate incorrect number of ticks due to cumulative errors.
     * So `_intervalCount` is required to specify the expected nice ticks number.
     * Should ensure `_intervalCount >= -1`,
     *  where `-1` means no nice tick (e.g., `_extent: [5.2, 5.8], _interval: 1`),
     *  and `0` means only one nice tick (e.g., `_extent: [5, 5.8], _interval: 1`).
     * @see setInterval
     */
    intervalCount: number | NullUndefined;
    /**
     * Should ensure:
     *  `_extent[0] <= _niceExtent[0] && _niceExtent[1] <= _extent[1]`
     * But NOTICE:
     *  `_niceExtent[0] - _niceExtent[1] <= _interval`, rather than always `< 0`,
     *  because `_niceExtent` is typically calculated by
     *  `[ Math.ceil(_extent[0] / _interval) * _interval, Math.floor(_extent[1] / _interval) * _interval ]`.
     *  e.g., `_extent: [5.2, 5.8]` with interval `1` will get `_niceExtent: [6, 5]`.
     *  e.g., `_extent: [5, 5.8]` with interval `1` will get `_niceExtent: [5, 5]`.
     *  e.g., `_extent: [5.7, 5.7]` with interval `1` will get `_niceExtent: [6, 5]`.
     * @see setInterval
     */
    niceExtent: number[] | NullUndefined;
};
declare type IntervalScaleSetting = {
    breakOption?: AxisBreakOption[] | NullUndefined;
    breakParsed?: AxisBreakParsingResult | NullUndefined;
};
/**
 * @final NEVER inherit me!
 */
interface IntervalScale extends ScaleMapperGeneric<IntervalScale> {
}
declare class IntervalScale extends Scale<IntervalScale> {
    static type: string;
    type: "interval";
    private _cfg;
    constructor(setting?: IntervalScaleSetting);
    static parse(val: ScaleDataValue): number;
    getConfig(): IntervalScaleConfigParsed;
    setConfig(cfg: IntervalScaleConfig): void;
    /**
     * In ascending order.
     */
    getTicks(opt?: ScaleGetTicksOpt): ScaleTick[];
    getMinorTicks(splitNumber: number): number[][];
    getLabel(tick: ScaleTick, opt?: IntervalScaleGetLabelOpt): string;
}
export default IntervalScale;
