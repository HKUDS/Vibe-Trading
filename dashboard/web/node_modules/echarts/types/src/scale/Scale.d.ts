import * as clazzUtil from '../util/clazz.js';
import { ScaleDataValue, ScaleTick, NullUndefined, ParsedValueNumeric } from '../util/types.js';
import { ScaleRawExtentInfo } from '../coord/scaleRawExtentInfo.js';
import { BreakScaleMapper, ParamPruneByBreak } from './break.js';
import { AxisScaleType } from '../coord/axisCommonTypes.js';
import { ScaleMapperGeneric } from './scaleMapper.js';
export declare type ScaleGetTicksOpt = {
    expandToNicedExtent?: boolean;
    pruneByBreak?: ParamPruneByBreak;
    breakTicks?: 'only_break' | 'none' | NullUndefined;
};
/**
 * @see ScaleMapper for the hierarchy structure.
 */
interface Scale<This = unknown> extends ScaleMapperGeneric<This> {
}
declare abstract class Scale<This = unknown> {
    type: AxisScaleType;
    /**
     * CAUTION: Do not visit it directly - use helper methods in `scale/break.ts` instead.
     */
    readonly brk: BreakScaleMapper | NullUndefined;
    private _isBlank;
    readonly rawExtentInfo: ScaleRawExtentInfo | NullUndefined;
    /**
     * Parse input `val` (typicall from ec option or API) to its corresponding
     * numeric representation.
     *
     * NOTICE:
     *  - The implementation must have no side-effect.
     *  - Must be available in constructor.
     *  - Must ensure the return is a number.
     *    `null`/`undefined` is not allowed.
     *    `NaN` represents invalid data.
     *  - Regarding `extent`:
     *    - In `OrdinalScale`, the extent and `ordinalMeta` has been finally determined
     *      before the constructor being called, and parse can reply on them
     *    - In other scales, the extent is not finally determined, and `parse` must not
     *      rely on them, otherwise, the result would be wrong if it is used earlier
     *      (like in `dataZoom`).
     */
    parse: (val: ScaleDataValue) => ParsedValueNumeric;
    /**
     * When axis extent depends on data and no data exists,
     * axis ticks should not be drawn, which is named 'blank'.
     *
     * @final NEVER override!
     */
    isBlank(): boolean;
    /**
     * When axis extent depends on data and no data exists,
     * axis ticks should not be drawn, which is named 'blank'.
     *
     * @final NEVER override!
     */
    setBlank(isBlank: boolean): void;
    /**
     * @return label of the tick.
     */
    abstract getLabel(tick: ScaleTick): string;
    /**
     * Create ticks. The result can be modified by the caller.
     */
    abstract getTicks(opt?: ScaleGetTicksOpt): ScaleTick[];
    /**
     * Create minor ticks. The result can be modified by the caller.
     */
    abstract getMinorTicks(splitNumber: number): number[][];
    static registerClass: clazzUtil.ClassManager['registerClass'];
    static getClass: clazzUtil.ClassManager['getClass'];
}
export default Scale;
