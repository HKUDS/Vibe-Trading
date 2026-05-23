import { TimeUnit } from '../util/time.js';
import Scale, { ScaleGetTicksOpt } from './Scale.js';
import { TimeScaleTick, ScaleTick, AxisBreakOption, NullUndefined } from '../util/types.js';
import { TimeAxisLabelFormatterParsed } from '../coord/axisCommonTypes.js';
import { LocaleOption } from '../core/locale.js';
import Model from '../model/Model.js';
import type { ScaleCalcNiceMethod } from '../coord/axisNiceTicks.js';
import { ScaleMapperGeneric } from './scaleMapper.js';
declare type TimeScaleSetting = {
    locale: Model<LocaleOption>;
    useUTC: boolean;
    breakOption: AxisBreakOption[] | NullUndefined;
};
/**
 * @final NEVER inherit me!
 */
interface TimeScale extends ScaleMapperGeneric<TimeScale> {
}
declare class TimeScale extends Scale<TimeScale> {
    static type: string;
    readonly type: "time";
    private _locale;
    private _useUTC;
    private _approxInterval;
    private _interval;
    private _minLevelUnit;
    constructor(setting: TimeScaleSetting);
    /**
     * Get label is mainly for other components like dataZoom, tooltip.
     */
    getLabel(tick: ScaleTick): string;
    getFormattedLabel(tick: ScaleTick, idx: number, labelFormatter: TimeAxisLabelFormatterParsed): string;
    getTicks(opt?: ScaleGetTicksOpt): TimeScaleTick[];
    getMinorTicks(splitNumber: number): number[][];
    setTimeInterval(opt: {
        interval: number;
        approxInterval: number;
        minLevelUnit: TimeUnit;
    }): void;
    static parse(val: number | string | Date): number;
}
export declare const calcNiceForTimeScale: ScaleCalcNiceMethod;
export default TimeScale;
