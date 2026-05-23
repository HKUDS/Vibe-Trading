import Scale, { ScaleGetTicksOpt } from './Scale.js';
import IntervalScale from './Interval.js';
import { ScaleTick, NullUndefined, AxisBreakOption } from '../util/types.js';
import { IntervalScaleGetLabelOpt } from './helper.js';
import { DecoratedScaleMapperMethods } from './scaleMapper.js';
declare type LogScaleSetting = {
    logBase: number | NullUndefined;
    breakOption: AxisBreakOption[] | NullUndefined;
};
/**
 * @final NEVER inherit me!
 */
declare class LogScale extends Scale<LogScale> {
    static type: string;
    readonly type: "log";
    readonly base: number;
    /**
     * `powStub` is used to save original values, i.e., values before logarithm
     * applied, such as raw extent and raw breaks.
     * NOTE: Logarithm transform is probably not inversible by rounding error, which
     * may cause min/max tick is displayed like `5.999999999999999`. The extent in
     * powStub is used to get the original precise extent for this issue.
     *
     * [CAVEAT] `powStub` and `intervalStub` should be modified synchronously.
     */
    readonly powStub: IntervalScale;
    /**
     * `intervalStub` provides linear tick arrangement (logarithm applied).
     * @see {powStub}
     */
    readonly intervalStub: IntervalScale;
    private _lookup;
    constructor(setting: LogScaleSetting);
    getTicks(opt?: ScaleGetTicksOpt): ScaleTick[];
    getMinorTicks(splitNumber: number): number[][];
    getLabel(data: ScaleTick, opt?: IntervalScaleGetLabelOpt): string;
    static mapperMethods: DecoratedScaleMapperMethods<LogScale>;
}
export default LogScale;
