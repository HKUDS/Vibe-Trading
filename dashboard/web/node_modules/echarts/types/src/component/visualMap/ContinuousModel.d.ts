import VisualMapModel, { VisualMapOption } from './VisualMapModel.js';
import { ItemStyleOption } from '../../util/types.js';
declare type VisualState = VisualMapModel['stateList'][number];
export interface ContinuousVisualMapOption extends VisualMapOption {
    align?: 'auto' | 'left' | 'right' | 'top' | 'bottom';
    /**
     * This prop effect default component type determine
     * @see echarts/component/visualMap/typeDefaulter.
     */
    calculable?: boolean;
    /**
     * selected range. In default case `range` is `[min, max]`
     * and can auto change along with user interaction or action "selectDataRange",
     * until user specified a range.
     * @see unboundedRange for the special case when `range[0]` or `range[1]` touch `min` or `max`.
     */
    range?: number[];
    /**
     * Whether to treat the range as unbounded when `range` touches `min` or `max`.
     * - `true`:
     *   when `range[0]` <= `min`, the actual range becomes `[-Infinity, range[1]]`;
     *   when `range[1]` >= `max`, the actual range becomes `[range[0], Infinity]`.
     *   NOTE:
     *     - This provides a way to ensure all data can be considered in-range when `min`/`max`
     *       are not precisely known.
     *     - Default is `true` for backward compatibility.
     *     - Piecewise VisualMap does not need it, since it can define unbounded range in each piece,
     *       such as "< 12", ">= 300".
     * - `false`:
     *   Disable the unbounded range behavior.
     *   Use case: `min`/`max` reflect the normal data range, and some outlier data should always be
     *   treated as out of range.
     */
    unboundedRange?: boolean;
    /**
     * Whether to enable hover highlight.
     */
    hoverLink?: boolean;
    /**
     * The extent of hovered data.
     */
    hoverLinkDataSize?: number;
    /**
     * Whether trigger hoverLink when hover handle.
     * If not specified, follow the value of `realtime`.
     */
    hoverLinkOnHandle?: boolean;
    handleIcon?: string;
    handleSize?: string | number;
    handleStyle?: ItemStyleOption;
    indicatorIcon?: string;
    indicatorSize?: string | number;
    indicatorStyle?: ItemStyleOption;
    emphasis?: {
        handleStyle?: ItemStyleOption;
    };
}
/**
 * @deprecated Use `ContinuousVisualMapOption` instead.
 */
export declare type ContinousVisualMapOption = ContinuousVisualMapOption;
declare class ContinuousModel extends VisualMapModel<ContinuousVisualMapOption> {
    static type: "visualMap.continuous";
    type: "visualMap.continuous";
    /**
     * @override
     */
    optionUpdated(newOption: ContinuousVisualMapOption, isInit: boolean): void;
    /**
     * @protected
     * @override
     */
    resetItemSize(): void;
    /**
     * @private
     */
    _resetRange(): void;
    /**
     * @protected
     * @override
     */
    completeVisualOption(): void;
    /**
     * @override
     */
    setSelected(selected: number[]): void;
    /**
     * @public
     */
    getSelected(): [number, number];
    /**
     * @override
     */
    getValueState(value: number): VisualState;
    findTargetDataIndices(range: number[]): {
        seriesId: string;
        dataIndex: number[];
    }[];
    /**
     * @implement
     */
    getVisualMeta(getColorVisual: (value: number, valueState: VisualState) => string): {
        stops: {
            value: number;
            color: string;
        }[];
        outerColors: string[];
    };
    static defaultOption: ContinuousVisualMapOption;
}
export default ContinuousModel;
