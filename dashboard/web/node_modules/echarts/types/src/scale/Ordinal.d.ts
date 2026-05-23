/**
 * Linear continuous scale
 * http://en.wikipedia.org/wiki/Level_of_measurement
 */
import Scale from './Scale.js';
import OrdinalMeta from '../data/OrdinalMeta.js';
import { OrdinalNumber, OrdinalSortInfo, ScaleTick } from '../util/types.js';
import { CategoryAxisBaseOption } from '../coord/axisCommonTypes.js';
import { DecoratedScaleMapperMethods, ScaleMapper, ScaleMapperGeneric } from './scaleMapper.js';
declare type OrdinalScaleSetting = {
    ordinalMeta?: OrdinalMeta | CategoryAxisBaseOption['data'];
    extent?: number[];
};
/**
 * @final NEVER inherit me!
 */
interface OrdinalScale extends ScaleMapperGeneric<OrdinalScale> {
    _mapper: ScaleMapper;
}
declare class OrdinalScale extends Scale<OrdinalScale> {
    static type: string;
    readonly type: "ordinal";
    private _ordinalMeta;
    /**
     * For example:
     * Given original ordinal data:
     * ```js
     * option = {
     *     xAxis: {
     *         // Their raw ordinal numbers are:
     *         //      0    1    2    3    4    5
     *         data: ['a', 'b', 'c', 'd', 'e', 'f']
     *     },
     *     yAxis: {}
     *     series: {
     *         type: 'bar',
     *         data: [
     *             ['d', 110], // ordinalNumber: 3
     *             ['c', 660], // ordinalNumber: 2
     *             ['f', 220], // ordinalNumber: 5
     *             ['e', 550]  // ordinalNumber: 4
     *         ],
     *         realtimeSort: true
     *     }
     * };
     * ```
     * After realtime sorted (order by yValue desc):
     * ```js
     * _ordinalNumbersByTick: [
     *     2, // tick: 0, yValue: 660
     *     5, // tick: 1, yValue: 220
     *     3, // tick: 2, yValue: 110
     *     4, // tick: 3, yValue: 550
     *     0, // tick: 4, yValue: -
     *     1, // tick: 5, yValue: -
     * ],
     * _ticksByOrdinalNumber: [
     *     4, // ordinalNumber: 0, yValue: -
     *     5, // ordinalNumber: 1, yValue: -
     *     0, // ordinalNumber: 2, yValue: 660
     *     2, // ordinalNumber: 3, yValue: 110
     *     3, // ordinalNumber: 4, yValue: 550
     *     1, // ordinalNumber: 5, yValue: 220
     * ]
     * ```
     * NOTICE:
     *  - The index of `_ordinalNumbersByTick` is "tick number", i.e., `tick.value`,
     *    rather than the index of `scale.getTicks()`. They are not the same when
     *    `_extent[0]` is delibrately set to be not zero, or `axisTick/axisLabel.interval` > 0.
     *  - Currently we only support that the index of `_ordinalNumbersByTick` is
     *    from `0` to `ordinalMeta.categories.length - 1`.
     *  - `OrdinalNumber` is always from `0` to `ordinalMeta.categories.length - 1`.
     *
     * @see `Ordinal['getRawOrdinalNumber']`
     * @see `OrdinalSortInfo`
     */
    private _ordinalNumbersByTick;
    /**
     * This is the inverted map of `_ordinalNumbersByTick`.
     * The index is `OrdinalNumber`, which is from `0` to `ordinalMeta.categories.length - 1`.
     * after `_ticksByOrdinalNumber` is initialized.
     *
     * @see `Ordinal['_ordinalNumbersByTick']`
     * @see `Ordinal['_getTickNumber']`
     * @see `OrdinalSortInfo`
     */
    private _ticksByOrdinalNumber;
    constructor(setting: OrdinalScaleSetting);
    private static parse;
    static decoratedMethods: DecoratedScaleMapperMethods<OrdinalScale>;
    /**
     * PENDING: currently this method is not used.
     * `makeCategoryTicks` is effectively used.
     */
    getTicks(): ScaleTick[];
    getMinorTicks(splitNumber: number): number[][];
    /**
     * @see `Ordinal['_ordinalNumbersByTick']`
     */
    setSortInfo(info: OrdinalSortInfo): void;
    private _getTickNumber;
    /**
     * @usage
     * ```js
     * const ordinalNumber = ordinalScale.getRawOrdinalNumber(tick.value);
     * // case0
     * const rawOrdinalValue = axisModel.getCategories()[ordinalNumber];
     * // case1
     * const rawOrdinalValue = this._ordinalMeta.categories[ordinalNumber];
     * // case2
     * const coord = axis.dataToCoord(ordinalNumber);
     * ```
     *
     * value may be out of range, e.g., when axis max is larger than `ordinalMeta.categories.length`,
     * where ordinal numbers are used as tick value directly.
     */
    getRawOrdinalNumber(tickValue: ScaleTick['value']): OrdinalNumber;
    /**
     * Get item on tick
     */
    getLabel(tick: ScaleTick): string;
    /**
     * NOTICE: This is different from `.getOrdinalMeta().length` when extent
     * is specified by `xxxAxis.min/max` or by `dataZoom`.
     */
    count(): number;
    getOrdinalMeta(): OrdinalMeta;
}
export default OrdinalScale;
