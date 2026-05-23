/**
 * [Notice]:
 * Consider custom bundle on demand, chart specified
 * or component specified types and constants should
 * not put here. Only common types and constants can
 * be put in this file.
 */
import Group from 'zrender/lib/graphic/Group.js';
import Element, { ElementEvent, ElementTextConfig } from 'zrender/lib/Element.js';
import type { DataFormatMixin } from '../model/mixin/dataFormat.js';
import type GlobalModel from '../model/Global.js';
import type ExtensionAPI from '../core/ExtensionAPI.js';
import type SeriesModel from '../model/Series.js';
import { HashMap } from 'zrender/lib/core/util.js';
import { TaskPlanCallbackReturn, TaskProgressParams } from '../core/task.js';
import type SeriesData from '../data/SeriesData.js';
import { Dictionary, ElementEventName, ImageLike, TextAlign, TextVerticalAlign } from 'zrender/lib/core/types.js';
import { PatternObject } from 'zrender/lib/graphic/Pattern.js';
import type { TooltipMarker } from './format.js';
import { AnimationEasing } from 'zrender/lib/animation/easing.js';
import { LinearGradientObject } from 'zrender/lib/graphic/LinearGradient.js';
import { RadialGradientObject } from 'zrender/lib/graphic/RadialGradient.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import { TSpanStyleProps } from 'zrender/lib/graphic/TSpan.js';
import { PathStyleProps } from 'zrender/lib/graphic/Path.js';
import { ImageStyleProps } from 'zrender/lib/graphic/Image.js';
import ZRText, { TextStyleProps } from 'zrender/lib/graphic/Text.js';
import type { Source } from '../data/Source.js';
import type Model from '../model/Model.js';
import type { DataStoreDimensionType } from '../data/DataStore.js';
import type { DimensionUserOuputEncode } from '../data/helper/dimensionHelper.js';
import type { PrimaryTimeUnit } from './time.js';
import type ChartView from '../view/Chart.js';
import type ComponentModel from '../model/Component.js';
import type View from '../coord/View.js';
import type ComponentView from '../view/Component.js';
export { Dictionary };
export declare type RendererType = 'canvas' | 'svg';
/**
 * NOTICE: For historical reason, echarts and zrender have not enabled TS config
 * `strictNullChecks` yet. Therefore, a explicitly declared `NullUndefined` can
 * indicate a variable can be `null` or `undefined` without more investigation,
 * but a variable without `NullUndefined` may also be `null` or `undefined`,
 * which has to be determined by the implementation.
 */
export declare type NullUndefined = null | undefined;
export declare const UNDEFINED_STR = "undefined";
export declare type LayoutOrient = 'vertical' | 'horizontal';
export declare type HorizontalAlign = 'left' | 'center' | 'right';
export declare type VerticalAlign = 'top' | 'middle' | 'bottom';
export declare type ColorString = string;
export declare type ZRColor = ColorString | LinearGradientObject | RadialGradientObject | PatternObject;
export declare type ZRLineType = 'solid' | 'dotted' | 'dashed' | number | number[];
export declare type ZRFontStyle = 'normal' | 'italic' | 'oblique';
export declare type ZRFontWeight = 'normal' | 'bold' | 'bolder' | 'lighter' | number;
export declare type ZREasing = AnimationEasing;
export declare type ZRTextAlign = TextAlign;
export declare type ZRTextVerticalAlign = TextVerticalAlign;
export declare type ZRElementEvent = ElementEvent;
export declare type ZRRectLike = RectLike;
export declare type ZRStyleProps = PathStyleProps | ImageStyleProps | TSpanStyleProps | TextStyleProps;
export declare type ZRElementEventName = ElementEventName | 'globalout';
export declare type ComponentFullType = string;
export declare type ComponentMainType = keyof ECUnitOption & string;
export declare type ComponentSubType = Exclude<ComponentOption['type'], undefined>;
/**
 * Use `parseClassType` to parse componentType declaration to componentTypeInfo.
 * For example:
 * componentType declaration: 'a.b', get componentTypeInfo {main: 'a', sub: 'b'}.
 * componentType declaration: '', get componentTypeInfo {main: '', sub: ''}.
 */
export interface ComponentTypeInfo {
    main: ComponentMainType;
    sub: ComponentSubType;
}
export declare const COMPONENT_MAIN_TYPE_SERIES = "series";
export interface ECElement extends Element {
    highDownSilentOnTouch?: boolean;
    onHoverStateChange?: (toState: DisplayState) => void;
    hoverState?: 0 | 1 | 2;
    selected?: boolean;
    z2EmphasisLift?: number;
    z2SelectLift?: number;
    /**
     * Force enable animation.
     * This property is useful when an ignored/invisible/removed element
     * should have label animation, like the case in the bar-racing charts.
     * `forceLabelAnimation` has higher priority than `disableLabelAnimation`.
     */
    forceLabelAnimation?: boolean;
    /**
     * Force disable animation.
     * `forceLabelAnimation` has higher priority than `disableLabelAnimation`.
     */
    disableLabelAnimation?: boolean;
    /**
     * Force disable overall layout
     */
    disableLabelLayout?: boolean;
    /**
     * Force disable morphing
     */
    disableMorphing?: boolean;
    /**
     * Force disable triggering tooltip
     */
    tooltipDisabled?: boolean;
}
export interface DataHost {
    getData(dataType?: SeriesDataType): SeriesData;
}
export interface DataModel extends Model<unknown>, DataHost, DataFormatMixin {
    getDataParams(dataIndex: number, dataType?: SeriesDataType, el?: Element): CallbackDataParams;
}
interface PayloadItem {
    excludeSeriesId?: OptionId | OptionId[];
    animation?: PayloadAnimationPart;
    [other: string]: any;
}
export interface Payload extends PayloadItem {
    type: string;
    escapeConnect?: boolean;
    batch?: PayloadItem[];
}
export interface HighlightPayload extends Payload {
    type: 'highlight';
    notBlur?: boolean;
}
export interface DownplayPayload extends Payload {
    type: 'downplay';
    notBlur?: boolean;
}
export interface PayloadAnimationPart {
    duration?: number;
    easing?: AnimationEasing;
    delay?: number;
}
export interface SelectChangedEvent extends ECActionRefinedEvent {
    type: 'selectchanged';
    isFromClick: boolean;
    fromAction: 'select' | 'unselect' | 'toggleSelected';
    fromActionPayload: Payload;
    selected: {
        seriesIndex: number;
        dataType?: SeriesDataType;
        dataIndex: number[];
    }[];
}
/**
 * @deprecated Backward compat.
 */
export interface SelectChangedPayload extends Payload {
    type: 'selectchanged';
    isFromClick: boolean;
    fromAction: 'select' | 'unselect' | 'toggleSelected';
    fromActionPayload: Payload;
    selected: {
        seriesIndex: number;
        dataType?: SeriesDataType;
        dataIndex: number[];
    }[];
}
export interface ViewRootGroup extends Group {
    __ecComponentInfo?: {
        mainType: string;
        index: number;
    };
}
export interface ECElementEvent extends ECEventData, CallbackDataParams {
    type: ZRElementEventName;
    event?: ElementEvent;
}
/**
 * The echarts event type to user.
 * Also known as packedEvent.
 */
export interface ECActionEvent extends ECEventData {
    type: string;
    componentType?: string;
    componentIndex?: number;
    seriesIndex?: number;
    escapeConnect?: boolean;
    batch?: ECEventData[];
}
/**
 * TODO: not applicable in `ECEventProcessor` yet.
 */
export interface ECActionRefinedEvent extends ECActionEvent {
    type: string;
    fromAction: string;
    fromActionPayload: Payload;
}
export declare type ECActionRefinedEventContent<TRefinedEvent extends ECActionRefinedEvent> = Omit<TRefinedEvent, 'type' | 'fromAction' | 'fromActionPayload'>;
export interface ECEventData {
    [key: string]: any;
}
export interface EventQueryItem {
    [key: string]: any;
}
export interface NormalizedEventQuery {
    cptQuery: EventQueryItem;
    dataQuery: EventQueryItem;
    otherQuery: EventQueryItem;
}
/**
 * The rule of creating "public event" and "event for connect":
 *  - If `refineEvent` provided,
 *      `refineEvent` creates the "public event",
 *      and "event for connect" is created internally by replicating the payload.
 *      This is because `makeActionFromEvent` requires the content of event to be
 *      the same as the original payload, while `refineEvent` creates a user-friend
 *      event that differs from the original payload.
 *  - Else if `ActionHandler` returns an object,
 *      it is both the "public event" and the "event for connect".
 *      (@deprecated, but keep this mechanism for backward compatibility).
 *  - Else,
 *      replicate the payload as both the "public event" and "event for connect".
 */
export interface ActionInfo {
    type: string;
    event?: string;
    update?: string;
    action?: ActionHandler;
    refineEvent?: ActionRefineEvent;
    publishNonRefinedEvent?: boolean;
    componentQuery?: boolean;
}
export interface ActionHandler {
    (payload: Payload, ecModel: GlobalModel, api: ExtensionAPI): void | ECEventData;
}
export interface ActionRefineEvent {
    (actionResultBatch: ECEventData[], payload: Payload, ecModel: GlobalModel, api: ExtensionAPI): {
        eventContent: ECActionRefinedEventContent<ECActionRefinedEvent>;
    };
}
export declare type ActionUpdateComponentQuery = {
    mainType: ComponentMainType;
    indexList: number[];
}[];
export interface OptionPreprocessor {
    (option: ECUnitOption, isTheme: boolean): void;
}
export interface PostUpdater {
    (ecModel: GlobalModel, api: ExtensionAPI): void;
}
export interface StageHandlerReset {
    (seriesModel: SeriesModel, ecModel: GlobalModel, api: ExtensionAPI, payload?: Payload): StageHandlerProgressExecutor | StageHandlerProgressExecutor[] | void;
}
export interface StageHandlerOverallReset {
    (ecModel: GlobalModel, api: ExtensionAPI, payload?: Payload): void;
}
export interface StageHandler {
    /**
     * Indicate that the "series stage task" will be piped for all series
     * (filtered series is included iff `performRawSeries: true`).
     *
     * OVERALL_STAGE_TASK (See `overallReset`) can not set `createOnAllSeries: true`.
     */
    createOnAllSeries?: boolean;
    /**
     * Indicate that the task will only be piped in the pipeline of this type of series.
     * (filtered series is included iff `performRawSeries: true`).
     * It is available for both `reset` and `overallReset`.
     */
    seriesType?: string;
    /**
     * Indicate that the task will only be piped in the pipeline of the returned series.
     * It is called in EC_PREPARE, before `CoordinateSystem['create']`.
     * It is available for both `reset` and `overallReset`.
     */
    getTargetSeries?: (ecModel: GlobalModel, api: ExtensionAPI) => HashMap<SeriesModel>;
    /**
     * If `true`, filtered series will also be "performed".
     */
    performRawSeries?: boolean;
    /**
     * Called only when this task in a pipeline.
     */
    plan?: StageHandlerPlan;
    /**
     * If `overallReset` is specified, an OVERALL_STAGE_TASK will be created.
     *
     * @tutorial [OVERALL_STAGE_TASK]
     *  An OVERALL_STAGE_TASK resides across multiple pipelines, and is associated with
     *  pipelines by "stub"s, which deliver messages like "dirty" and "output end".
     *  OVERALL_STAGE_TASK does not support `progess` method.
     *
     * The `overallReset` method is called iff this task is "dirty" (See `Task['dirty']`).
     * See EC_TASK_DIRTY for a summary of possible `dirty()` calls.
     *
     * @see dirtyOnOverallProgress If a OVERALL_STAGE_TASK need to handle series data.
     */
    overallReset?: StageHandlerOverallReset;
    /**
     * If `reset` is specified, a SERIES_STAGE_TASK will be created.
     *
     * @tutorial [SERIES_STAGE_TASK]
     *  A SERIES_STAGE_TASK is owned by a pipeline and is specific to a single series.
     *
     * The `reset` method is called iff this task is "dirty" (See `Task['dirty']`).
     * See EC_TASK_DIRTY for a summary of possible `dirty()` calls.
     *
     * NOTICE: `dirtyOnOverallProgress: true` cause that the corresponding `overallReset`
     *  and `reset` of downsteams tasks may also be called in EC_PROGRESSIVE_CYCLE.
     *  But in this case, `CoordinateSystem#create` and `CoordinateSystem#update` are not called.
     *  Only lifecycle like `coordsys:aftercreate` can be ensured to be only called in EC_FULL_UPDATE
     *  of EC_FULL_UPDATE_CYCLE and EC_PARTIAL_UPDATE_CYCLE, but not in EC_PROGRESSIVE_CYCLE and
     *  EC_APPEND_DATA_CYCLE.
     */
    reset?: StageHandlerReset;
    /**
     * This is a temporary mechanism primarily for a dataZoom case in `appendData`.
     *
     * Ordinarily, `overallReset` is NOT called in progress in the subsequent frames, which is suitable
     * for most OVERALL_STAGE_TASK, where no series data related operations is performed (e.g., color
     * palette task).
     * But some certain OVERALL_STAGE_TASK need to handle series data, where `dirtyOnOverallProgress: true`
     * is required. It allows all pipelines to be blocked until this stage, thereby no `overallReset` call
     * being omitted. (See PerformStageTaskOpt['block'] for its meaning.) (e.g., dataZoom task)
     *
     * NOTE_IMPL: It will set this OVERALL_STAGE_TASK dirty when the pipeline progress.
     * Moreover, to avoid calling the OVERALL_STAGE_TASK each frame (too frequent),
     * it block the pipeline until this stage (via `task.__block`).
     */
    dirtyOnOverallProgress?: boolean;
}
export interface StageHandlerInternal extends StageHandler {
    uid: string;
    visualType?: 'layout' | 'visual';
    __prio: number;
    __raw: StageHandler | StageHandlerOverallReset;
    isVisual?: boolean;
    isLayout?: boolean;
}
export declare type StageHandlerProgressParams = TaskProgressParams;
export interface StageHandlerProgressExecutor {
    dataEach?: (data: SeriesData, idx: number) => void;
    progress?: (params: StageHandlerProgressParams, data: SeriesData) => void;
}
export declare type StageHandlerPlanReturn = TaskPlanCallbackReturn;
export interface StageHandlerPlan {
    (seriesModel: SeriesModel, ecModel: GlobalModel, api: ExtensionAPI, payload?: Payload): StageHandlerPlanReturn;
}
export interface LoadingEffectCreator {
    (api: ExtensionAPI, cfg: object): LoadingEffect;
}
export interface LoadingEffect extends Element {
    resize: () => void;
}
/**
 * 'html' is used for rendering tooltip in extra DOM form, and the result
 * string is used as DOM HTML content.
 * 'richText' is used for rendering tooltip in rich text form, for those where
 * DOM operation is not supported.
 */
export declare type TooltipRenderMode = 'html' | 'richText';
export declare type TooltipOrderMode = 'valueAsc' | 'valueDesc' | 'seriesAsc' | 'seriesDesc';
export declare type OrdinalRawValue = string | number;
export declare type OrdinalNumber = number;
/**
 * @usage
 * For example,
 *  ```js
 *  { ordinalNumbers: [2, 5, 3, 4] }
 *  ```
 *  means that "ordinal number" 2 should be displayed on `tick.value` 0,
 *  "ordinal number" 5 should be displayed on `tick.value` 1, ...
 * NOTICE:
 *  - The index/key of `ordinalNumbers` is "tick.value" rather than the index of
 *    `scale.getTicks()`. They are differnet when `axis.min` is set to be not zero,
 *    or `axisTick/axisLabel.interval > 0`.
 *  - The value of `ordinalNumbers` must be a valid `OrdinalNumber`;
 *    null/undefined is not supported.
 *  - `OrdinalNumber` is always from `0` to `ordinalMeta.categories.length - 1`.
 */
export declare type OrdinalSortInfo = {
    ordinalNumbers: OrdinalNumber[];
};
/**
 * `OptionDataValue` is the primitive value in `series.data` or `dataset.source`.
 * `OptionDataValue` are parsed (see `src/data/helper/dataValueHelper.parseDataValue`)
 * into `ParsedValue` and stored into `data/SeriesData` storage.
 * Note:
 * (1) The term "parse" does not mean `src/scale/Scale['parse']`(@see `ScaleDataValue`).
 * (2) If a category dimension is not mapped to any axis, its raw value will NOT be
 * parsed to `OrdinalNumber` but keep the original `OrdinalRawValue` in `src/data/SeriesData` storage.
 */
export declare type ParsedValue = ParsedValueNumeric | OrdinalRawValue;
export declare type ParsedValueNumeric = number | OrdinalNumber;
/**
 * `ScaleDataValue` represents the user input axis value in echarts API.
 * (For example, used `axis.min`/`axis.max` in echarts option, `convertToPixel`).
 * NOTICE:
 *  `ScaleDataValue` is slightly different from `OptionDataValue` for historical reason.
 *  `ScaleDataValue` should be parsed by `src/scale/Scale['parse']`.
 *  `OptionDataValue` should be parsed by `src/data/helper/dataValueHelper.parseDataValue`.
 * FIXME:
 *  Make `ScaleDataValue` `OptionDataValue` consistent? Since numeric string (like `'123'`) is accepted
 *  in `series.data` and is effectively accepted in some axis relevant option (e.g., `axis.min/max`),
 *  `type ScaleDataValue` should also include it for consistency. But it might bring some breaking in
 *  TS interface (user callback) and need comprehensive checks for all of the parsing of `ScaleDataValue`.
 */
export declare type ScaleDataValue = ParsedValueNumeric | OrdinalRawValue | Date;
/**
 * - `ScaleDataValue`:
 *   e.g. geo accept that primitive input, like `convertToPixel('some_place')`;
 *   Some coord sys, such as 'cartesian2d', also supports that for only query only a single axis.
 * - `ScaleDataValue[]`:
 *   This is the most common case, each array item represent each data in
 *   every dimension required by the coord sys. e.g., `[12, 98]` represents `[xData, yData]`.
 * - `(ScaleDataValue[])[]`:
 *   represents `[data_range_x, data_range_y]`. e.g., `dataToPoint([[5, 600], [8889, 9000]])`,
 *   represents data range `[5, 600]` in x, and `[8889, 9000]` in y.
 *   Can be also `[5, [8999, 9000]]`.
 */
export declare type CoordinateSystemDataCoord = (ScaleDataValue | NullUndefined) | (ScaleDataValue | NullUndefined)[] | (ScaleDataValue | ScaleDataValue[] | NullUndefined)[];
export declare type AxisBreakOption = {
    start: ScaleDataValue;
    end: ScaleDataValue;
    gap?: number | string;
    isExpanded?: boolean;
};
export declare type AxisBreakOptionIdentifierInAxis = Pick<AxisBreakOption, 'start' | 'end'>;
export declare type ParsedAxisBreakList = ParsedAxisBreak[];
export declare type ParsedAxisBreak = {
    breakOption: AxisBreakOption;
    vmin: number;
    vmax: number;
    gapParsed: {
        type: 'tpAbs' | 'tpPrct';
        val: number;
    };
    gapReal: number | NullUndefined;
};
export declare type VisualAxisBreak = {
    type: 'vmin' | 'vmax';
    parsedBreak: ParsedAxisBreak;
};
export declare type AxisLabelFormatterExtraBreakPart = {
    break?: {
        type: 'start' | 'end';
        start: ParsedAxisBreak['vmin'];
        end: ParsedAxisBreak['vmax'];
    };
};
export interface ScaleTick {
    /**
     * This is a number corresponding to the the original business value,
     * that is, a value in the "outmost" space, the result of `Scale['parse']`.
     *
     * NOTICE:
     *  - In `LogScale`, this the value in the pow space (the original space).
     *  - In `TimeScale`, this is a timestamp.
     *  - In `OrdinalScale`, this is NOT an `OrdinalNumber`, since `OrdinalSortInfo` exists.
     *    This `value` is effectively an `OrdinalNumber` before being sorted.
     *    Should use the conversion `const tickValue = getTickValueOutermost(scale, tick)`
     *    accordingly, e.g., as the input of user callbacks, `dataToCoord` and `scale.normalize`.
     *    PENDING:
     *      And this case is not properly covered by `scaleMapping` polymorphism as `LogScale`
     *      does - the manual call of `getTickValueOutermost` is still required everywhere.
     *    Note use cases below:
     *      - `axis.min/max` should be specified in "unsorted" space.
     *      - Futher position calculation requires values in "unsorted" space, such as
     *        `splitLine`, `splitArea`, minor ticks, etc.
     *      - `anid` (animation id) requires a value in "unsorted" space, since the animation
     *        typically represents the location (in `axisTick`, `splitLine` and `splitArea`,
     *        especially when `boundaryGap: true`).
     *      - Axis label requires a value in "sorted" space.
     *      - User interactions (tooltip, axis pointer, etc.) gets values in "sorted" space.
     */
    value: number;
    break?: VisualAxisBreak;
    time?: TimeScaleTick['time'];
    notNice?: boolean | NullUndefined;
    offInterval?: boolean | NullUndefined;
}
export interface TimeScaleTick extends ScaleTick {
    time: {
        /**
         * Level information is used for label formatting.
         * `level` is 0 or undefined by default, with higher value indicating greater significant.
         * For example, a time axis may contain labels like: Jan, 8th, 16th, 23th, Feb, and etc.
         * In this case, month labels like Jan and Feb should be displayed in a more significant
         * way than days. The tick labels are:
         *      labels: `Jan  8th  16th  23th  Feb`
         *      levels: `1    0    0     0     1  `
         * The label formatter can be configured as `{[timeUnit]: string | string[]}`, where the
         * timeUnit is determined by the tick value itself by `time.ts#getUnitFromValue`, while
         * the `level` is the index under that time unit. (i.e., `formatter[timeUnit][level]`).
         */
        level: number;
        /**
         * An upper and lower time unit that is suggested to be displayed.
         * Terms upper/lower means, such as 'year' is "upper" and 'month' is "lower".
         * This is just suggestion. Time units that are out of this range can also be displayed.
         */
        upperTimeUnit: PrimaryTimeUnit;
        lowerTimeUnit: PrimaryTimeUnit;
    };
}
/**
 * Return type of API `CoordinateSystem['dataToLayout']`, expose to users.
 */
export interface CoordinateSystemDataLayout {
    rect?: RectLike;
    contentRect?: RectLike;
    matrixXYLocatorRange?: number[][];
}
export declare type DimensionIndex = number;
export declare type DimensionIndexLoose = DimensionIndex | string;
export declare type DimensionName = string;
export declare type DimensionLoose = DimensionName | DimensionIndexLoose;
export declare type DimensionType = DataStoreDimensionType;
export declare const VISUAL_DIMENSIONS: HashMap<number, keyof DataVisualDimensions>;
export interface DataVisualDimensions {
    tooltip?: DimensionIndex | false;
    label?: DimensionIndex;
    itemName?: DimensionIndex;
    itemId?: DimensionIndex;
    itemGroupId?: DimensionIndex;
    itemChildGroupId?: DimensionIndex;
    seriesName?: DimensionIndex;
}
export declare type DimensionDefinition = {
    type?: DataStoreDimensionType;
    name?: DimensionName;
    displayName?: string;
};
export declare type DimensionDefinitionLoose = DimensionDefinition['name'] | DimensionDefinition;
export declare const SOURCE_FORMAT_ORIGINAL: "original";
export declare const SOURCE_FORMAT_ARRAY_ROWS: "arrayRows";
export declare const SOURCE_FORMAT_OBJECT_ROWS: "objectRows";
export declare const SOURCE_FORMAT_KEYED_COLUMNS: "keyedColumns";
export declare const SOURCE_FORMAT_TYPED_ARRAY: "typedArray";
export declare const SOURCE_FORMAT_UNKNOWN: "unknown";
export declare type SourceFormat = typeof SOURCE_FORMAT_ORIGINAL | typeof SOURCE_FORMAT_ARRAY_ROWS | typeof SOURCE_FORMAT_OBJECT_ROWS | typeof SOURCE_FORMAT_KEYED_COLUMNS | typeof SOURCE_FORMAT_TYPED_ARRAY | typeof SOURCE_FORMAT_UNKNOWN;
export declare const SERIES_LAYOUT_BY_COLUMN: "column";
export declare const SERIES_LAYOUT_BY_ROW: "row";
export declare type SeriesLayoutBy = typeof SERIES_LAYOUT_BY_COLUMN | typeof SERIES_LAYOUT_BY_ROW;
export declare type OptionSourceHeader = boolean | 'auto' | number;
export declare type SeriesDataType = 'main' | 'node' | 'edge';
/**
 * [ECUnitOption]:
 * An object that contains definitions of components
 * and other properties. For example:
 *
 * ```ts
 * let option: ECUnitOption = {
 *
 *     // Single `title` component:
 *     title: {...},
 *
 *     // Two `visualMap` components:
 *     visualMap: [{...}, {...}],
 *
 *     // Two `series.bar` components
 *     // and one `series.pie` component:
 *     series: [
 *         {type: 'bar', data: [...]},
 *         {type: 'bar', data: [...]},
 *         {type: 'pie', data: [...]}
 *     ],
 *
 *     // A property:
 *     backgroundColor: '#421ae4'
 *
 *     // A property object:
 *     textStyle: {
 *         color: 'red',
 *         fontSize: 20
 *     }
 * };
 * ```
 */
export declare type ECUnitOption = {
    baseOption?: unknown;
    options?: unknown;
    media?: unknown;
    timeline?: ComponentOption | ComponentOption[];
    backgroundColor?: ZRColor;
    darkMode?: boolean | 'auto';
    textStyle?: GlobalTextStyleOption;
    useUTC?: boolean;
    hoverLayerThreshold?: number;
    legacyViewCoordSysCenterBase?: boolean;
    legacyMinMaxDontInverseAxis?: boolean;
    [key: string]: ComponentOption | ComponentOption[] | Dictionary<unknown> | unknown;
    stateAnimation?: AnimationOption;
} & AnimationOptionMixin & ColorPaletteOptionMixin;
/**
 * [ECOption]:
 * An object input to echarts.setOption(option).
 * May be an 'option: ECUnitOption',
 * or may be an object contains multi-options. For example:
 *
 * ```ts
 * let option: ECOption = {
 *     baseOption: {
 *         title: {...},
 *         legend: {...},
 *         series: [
 *             {data: [...]},
 *             {data: [...]},
 *             ...
 *         ]
 *     },
 *     timeline: {...},
 *     options: [
 *         {title: {...}, series: {data: [...]}},
 *         {title: {...}, series: {data: [...]}},
 *         ...
 *     ],
 *     media: [
 *         {
 *             query: {maxWidth: 320},
 *             option: {series: {x: 20}, visualMap: {show: false}}
 *         },
 *         {
 *             query: {minWidth: 320, maxWidth: 720},
 *             option: {series: {x: 500}, visualMap: {show: true}}
 *         },
 *         {
 *             option: {series: {x: 1200}, visualMap: {show: true}}
 *         }
 *     ]
 * };
 * ```
 */
export interface ECBasicOption extends ECUnitOption {
    baseOption?: ECUnitOption;
    timeline?: ComponentOption | ComponentOption[];
    options?: ECUnitOption[];
    media?: MediaUnit[];
}
export declare type OptionSourceData<VAL extends OptionDataValue = OptionDataValue, ORIITEM extends OptionDataItemOriginal<VAL> = OptionDataItemOriginal<VAL>> = OptionSourceDataOriginal<VAL, ORIITEM> | OptionSourceDataObjectRows<VAL> | OptionSourceDataArrayRows<VAL> | OptionSourceDataKeyedColumns<VAL> | OptionSourceDataTypedArray;
export declare type OptionDataItemOriginal<VAL extends OptionDataValue = OptionDataValue> = VAL | VAL[] | OptionDataItemObject<VAL>;
export declare type OptionSourceDataOriginal<VAL extends OptionDataValue = OptionDataValue, ORIITEM extends OptionDataItemOriginal<VAL> = OptionDataItemOriginal<VAL>> = ArrayLike<ORIITEM>;
export declare type OptionSourceDataObjectRows<VAL extends OptionDataValue = OptionDataValue> = Array<Dictionary<VAL>>;
export declare type OptionSourceDataArrayRows<VAL extends OptionDataValue = OptionDataValue> = Array<Array<VAL>>;
export declare type OptionSourceDataKeyedColumns<VAL extends OptionDataValue = OptionDataValue> = Dictionary<ArrayLike<VAL>>;
export declare type OptionSourceDataTypedArray = ArrayLike<number>;
export declare type OptionDataItem = OptionDataValue | Dictionary<OptionDataValue> | OptionDataValue[] | OptionDataItemObject<OptionDataValue>;
export declare type OptionDataItemObject<T> = {
    id?: OptionId;
    name?: OptionName;
    groupId?: OptionId;
    childGroupId?: OptionId;
    value?: T[] | T;
    selected?: boolean;
};
export declare type OptionId = string | number;
export declare type OptionName = string | number;
export interface GraphEdgeItemObject<VAL extends OptionDataValue> extends OptionDataItemObject<VAL> {
    /**
     * Name or index of source node.
     */
    source?: string | number;
    /**
     * Name or index of target node.
     */
    target?: string | number;
}
export declare type OptionDataValue = string | number | Date | null | undefined;
export declare type OptionDataValueNumeric = number | '-';
export declare type OptionDataValueCategory = string;
export declare type OptionDataValueDate = Date | string | number;
export declare type ModelOption = any;
export declare type ThemeOption = Dictionary<any>;
export declare type DisplayState = 'normal' | 'emphasis' | 'blur' | 'select';
export declare type DisplayStateNonNormal = Exclude<DisplayState, 'normal'>;
export declare type DisplayStateHostOption = {
    emphasis?: Dictionary<any>;
    [key: string]: any;
};
export interface OptionEncodeVisualDimensions {
    tooltip?: OptionEncodeValue;
    label?: OptionEncodeValue;
    itemName?: OptionEncodeValue;
    itemId?: OptionEncodeValue;
    seriesName?: OptionEncodeValue;
    itemGroupId?: OptionEncodeValue;
    childGroupdId?: OptionEncodeValue;
}
export interface OptionEncode extends OptionEncodeVisualDimensions {
    [coordDim: string]: OptionEncodeValue | undefined;
}
export declare type OptionEncodeValue = DimensionLoose | DimensionLoose[];
export declare type EncodeDefaulter = (source: Source, dimCount: number) => OptionEncode;
export interface CallbackDataParams {
    componentType: string;
    componentSubType: string;
    componentIndex: number;
    seriesType?: string;
    seriesIndex?: number;
    seriesId?: string;
    seriesName?: string;
    name: string;
    dataIndex: number;
    data: OptionDataItem;
    dataType?: SeriesDataType;
    value: OptionDataItem | OptionDataValue;
    color?: ZRColor;
    borderColor?: string;
    dimensionNames?: DimensionName[];
    encode?: DimensionUserOuputEncode;
    marker?: TooltipMarker;
    status?: DisplayState;
    dimensionIndex?: number;
    percent?: number;
    $vars: string[];
}
export declare type InterpolatableValue = ParsedValue | ParsedValue[];
export declare type DecalDashArrayX = number | (number | number[])[];
export declare type DecalDashArrayY = number | number[];
export interface DecalObject {
    symbol?: string | string[];
    symbolSize?: number;
    symbolKeepAspect?: boolean;
    color?: string;
    backgroundColor?: string;
    dashArrayX?: DecalDashArrayX;
    dashArrayY?: DecalDashArrayY;
    rotation?: number;
    maxTileWidth?: number;
    maxTileHeight?: number;
}
export interface InnerDecalObject extends DecalObject {
    dirty?: boolean;
}
export interface MediaQuery {
    minWidth?: number;
    maxWidth?: number;
    minHeight?: number;
    maxHeight?: number;
    minAspectRatio?: number;
    maxAspectRatio?: number;
}
export declare type MediaUnit = {
    query?: MediaQuery;
    option: ECUnitOption;
};
export declare type ComponentLayoutMode = {
    type?: 'box';
    ignoreSize?: boolean | boolean[];
};
export declare type PaletteOptionMixin = ColorPaletteOptionMixin;
export interface ColorPaletteOptionMixin {
    color?: ZRColor | ZRColor[];
    colorLayer?: ZRColor[][];
}
/**
 * Mixin of option set to control the box layout of each component.
 */
export interface BoxLayoutOptionMixin {
    width?: PositionSizeOption;
    height?: PositionSizeOption;
    top?: PositionSizeOption;
    right?: PositionSizeOption;
    bottom?: PositionSizeOption;
    left?: PositionSizeOption;
}
/**
 * Need to be parsed by `parsePositionOption` or `parsePositionSizeOption`.
 * Accept number, or numeric string (`'123'`), or percentage ('100%'), as x/y/width/height pixel number.
 * If null/undefined or invalid, return NaN.
 */
export declare type PositionSizeOption = number | string;
export interface CircleLayoutOptionMixin<TNuance extends {
    centerExtra: unknown;
} = {
    centerExtra: never;
}> {
    center?: (number | string)[] | TNuance['centerExtra'];
    radius?: (number | string)[] | number | string;
}
export interface ShadowOptionMixin {
    shadowBlur?: number;
    shadowColor?: ColorString;
    shadowOffsetX?: number;
    shadowOffsetY?: number;
}
export interface BorderOptionMixin {
    borderColor?: ZRColor;
    borderWidth?: number;
    borderType?: ZRLineType;
    borderCap?: CanvasLineCap;
    borderJoin?: CanvasLineJoin;
    borderDashOffset?: number;
    borderMiterLimit?: number;
}
export declare type ColorBy = 'series' | 'data';
export interface SunburstColorByMixin {
    colorBy?: ColorBy;
}
export declare type AnimationDelayCallbackParam = {
    count: number;
    index: number;
};
export declare type AnimationDurationCallback = (idx: number) => number;
export declare type AnimationDelayCallback = (idx: number, params?: AnimationDelayCallbackParam) => number;
export interface AnimationOption {
    duration?: number;
    easing?: AnimationEasing;
    delay?: number;
}
/**
 * Mixin of option set to control the animation of series.
 */
export interface AnimationOptionMixin {
    /**
     * If enable animation
     */
    animation?: boolean;
    /**
     * Disable animation when the number of elements exceeds the threshold
     */
    animationThreshold?: number;
    /**
     * Duration of initialize animation.
     * Can be a callback to specify duration of each element
     */
    animationDuration?: number | AnimationDurationCallback;
    /**
     * Easing of initialize animation
     */
    animationEasing?: AnimationEasing;
    /**
     * Delay of initialize animation
     * Can be a callback to specify duration of each element
     */
    animationDelay?: number | AnimationDelayCallback;
    /**
     * Delay of data update animation.
     * Can be a callback to specify duration of each element
     */
    animationDurationUpdate?: number | AnimationDurationCallback;
    /**
     * Easing of data update animation.
     */
    animationEasingUpdate?: AnimationEasing;
    /**
     * Delay of data update animation.
     * Can be a callback to specify duration of each element
     */
    animationDelayUpdate?: number | AnimationDelayCallback;
}
export interface RoamOptionMixin {
    /**
     * If enable roam. can be specified 'scale' or 'move'
     */
    roam?: boolean | 'pan' | 'move' | 'zoom' | 'scale';
    /**
     * Hover over an area where roaming is triggered.
     * - if `null`/`undefined`, the trigger area is
     *   the intersection of "self bounding rect" and "clipping rect (if any)".
     * - if 'global', the trigger area is
     *   the intersection of "the entire canvas" and "clipping rect (if any)".
     * NOTE:
     *  The clipping rect, which can be enabled by `clip: true`, is typically the layout rect.
     *  The layout rect is typically determined by option `left`/`right`/`top`/`bottom`/`width`/`height`, some
     *  components/series, such as `geo` and `series.map` can also be determined by `layoutCenter`/`layoutSize`,
     *  and may modified by `preserveAspect`.
     *
     * PENDING: do we need to support to only trigger roaming on the shapes themselves,
     *  rather than the bounding rect?
     * PENDING: do we need to support to check by the laytout rect? But in this case,
     *  `roamTrigger: 'global', clip: true` is more reasonable.
     */
    roamTrigger?: 'global' | 'selfRect' | NullUndefined;
    /**
     * @see VIEW_COORD_SYS_CENTER_ZOOM_DEFINITION
     */
    center?: (number | string)[];
    /**
     * Current transformation scale. Default is 1.
     * @see VIEW_COORD_SYS_CENTER_ZOOM_DEFINITION
     */
    zoom?: number;
    /**
     * Limit of `zoom`. The name is inconsistent for historical reason.
     */
    scaleLimit?: {
        min?: number;
        max?: number;
    };
    /**
     * Symbol size scale ratio on roaming.
     */
    nodeScaleRatio?: number;
}
export interface PreserveAspectMixin {
    preserveAspect?: boolean | 'contain' | 'cover';
    preserveAspectAlign?: 'left' | 'right' | 'center';
    preserveAspectVerticalAlign?: 'top' | 'bottom' | 'middle';
}
export declare type SymbolSizeCallback<T> = (rawValue: any, params: T) => number | number[];
export declare type SymbolCallback<T> = (rawValue: any, params: T) => string;
export declare type SymbolRotateCallback<T> = (rawValue: any, params: T) => number;
export declare type SymbolOffsetCallback<T> = (rawValue: any, params: T) => string | number | (string | number)[];
/**
 * Mixin of option set to control the element symbol.
 * Include type of symbol, and size of symbol.
 */
export interface SymbolOptionMixin<T = never> {
    /**
     * type of symbol, like `cirlce`, `rect`, or custom path and image.
     */
    symbol?: string | (T extends never ? never : SymbolCallback<T>);
    /**
     * Size of symbol.
     */
    symbolSize?: number | number[] | (T extends never ? never : SymbolSizeCallback<T>);
    symbolRotate?: number | (T extends never ? never : SymbolRotateCallback<T>);
    symbolKeepAspect?: boolean;
    symbolOffset?: string | number | (string | number)[] | (T extends never ? never : SymbolOffsetCallback<T>);
}
/**
 * ItemStyleOption is a most common used set to config element styles.
 * It includes both fill and stroke style.
 */
export interface ItemStyleOption<TCbParams = never> extends ShadowOptionMixin, BorderOptionMixin {
    color?: ZRColor | (TCbParams extends never ? never : ((params: TCbParams) => ZRColor));
    opacity?: number;
    decal?: DecalObject | 'none';
    borderRadius?: (number | string)[] | number | string;
}
/**
 * ItemStyleOption is a option set to control styles on lines.
 * Used in the components or series like `line`, `axis`
 * It includes stroke style.
 */
export interface LineStyleOption<Clr = ZRColor> extends ShadowOptionMixin {
    width?: number;
    color?: Clr;
    opacity?: number;
    type?: ZRLineType;
    cap?: CanvasLineCap;
    join?: CanvasLineJoin;
    dashOffset?: number;
    miterLimit?: number;
}
/**
 * ItemStyleOption is a option set to control styles on an area, like polygon, rectangle.
 * It only include fill style.
 */
export interface AreaStyleOption<Clr = ZRColor> extends ShadowOptionMixin {
    color?: Clr;
    opacity?: number;
}
declare type Arrayable<T extends Dictionary<any>> = {
    [key in keyof T]: T[key] | T[key][];
};
declare type Dictionaryable<T extends Dictionary<any>> = {
    [key in keyof T]: T[key] | Dictionary<T[key]>;
};
export interface VisualOptionUnit {
    symbol?: string;
    symbolSize?: number;
    color?: ColorString;
    colorAlpha?: number;
    opacity?: number;
    colorLightness?: number;
    colorSaturation?: number;
    colorHue?: number;
    decal?: DecalObject;
    liftZ?: number;
}
export declare type VisualOptionFixed = VisualOptionUnit;
/**
 * Option about visual properties used in piecewise mapping
 * Used in each piece.
 */
export declare type VisualOptionPiecewise = VisualOptionUnit;
/**
 * Option about visual properties used in linear mapping
 */
export declare type VisualOptionLinear = Arrayable<VisualOptionUnit>;
/**
 * Option about visual properties can be encoded from ordinal categories.
 * Each value can either be a dictionary to lookup with category name, or
 * be an array to lookup with category index. In this case the array length should
 * be same with categories.
 */
export declare type VisualOptionCategory = Arrayable<VisualOptionUnit> | Dictionaryable<VisualOptionUnit>;
/**
 * All visual properties can be encoded.
 */
export declare type BuiltinVisualProperty = keyof VisualOptionUnit;
export declare type TextCommonOptionNuanceBase = Record<string, unknown>;
export declare type TextCommonOptionNuanceDefault = {};
declare type LabelStyleColorString = ColorString | 'inherit' | 'auto';
export interface TextCommonOption<TNuance extends TextCommonOptionNuanceBase = TextCommonOptionNuanceDefault> extends ShadowOptionMixin {
    color?: 'color' extends keyof TNuance ? (TNuance['color'] | LabelStyleColorString) : LabelStyleColorString;
    fontStyle?: ZRFontStyle;
    fontWeight?: ZRFontWeight;
    fontFamily?: string;
    fontSize?: number | string;
    align?: HorizontalAlign;
    verticalAlign?: VerticalAlign;
    baseline?: VerticalAlign;
    opacity?: number;
    lineHeight?: number;
    backgroundColor?: ColorString | {
        image: ImageLike | string;
    };
    borderColor?: string;
    borderWidth?: number;
    borderType?: ZRLineType;
    borderDashOffset?: number;
    borderRadius?: number | number[];
    padding?: number | number[];
    /**
     * Currently margin related options are not declared here. They are not supported in rich text.
     * @see {LabelCommonOption}
     */
    width?: number | string;
    height?: number;
    textBorderColor?: string;
    textBorderWidth?: number;
    textBorderType?: ZRLineType;
    textBorderDashOffset?: number;
    textShadowBlur?: number;
    textShadowColor?: string;
    textShadowOffsetX?: number;
    textShadowOffsetY?: number;
    tag?: string;
}
export declare type GlobalTextStyleOption = Pick<TextCommonOption, 'color' | 'opacity' | 'fontStyle' | 'fontWeight' | 'fontSize' | 'fontFamily' | 'textShadowColor' | 'textShadowBlur' | 'textShadowOffsetX' | 'textShadowOffsetY' | 'textBorderColor' | 'textBorderWidth' | 'textBorderType' | 'textBorderDashOffset'>;
export interface RichTextOption extends Dictionary<TextCommonOption> {
}
export interface LabelFormatterCallback<T = CallbackDataParams> {
    (params: T): string;
}
/**
 * LabelOption is an option set to control the style of labels.
 * Include color, background, shadow, truncate, rotation, distance, etc..
 */
export interface LabelOption<TNuance extends {
    positionExtra: unknown;
} = {
    positionExtra: never;
}> extends LabelCommonOption {
    /**
     * If show label
     */
    show?: boolean;
    position?: ElementTextConfig['position'] | TNuance['positionExtra'];
    distance?: number;
    rotate?: number;
    offset?: number[];
    silent?: boolean;
    precision?: number | 'auto';
    valueAnimation?: boolean;
}
/**
 * Common options for both `axis.axisLabel`, `axis.nameTextStyle and other `label`s.
 * Historically, they have had some nuances in options.
 */
export interface LabelCommonOption<TNuanceOption extends TextCommonOptionNuanceBase = TextCommonOptionNuanceDefault> extends TextCommonOption<TNuanceOption> {
    /**
     * Min margin between labels. Used when label has layout.
     * PENDING: @see {LabelMarginType}
     * It's `minMargin` instead of `margin` is for not breaking the previous code using `margin`.
     * See the summary in `textMargin`.
     *
     * [CAUTION]: do not set `minMargin` in `defaultOption`, otherwise users have to explicitly
     *  clear the `minMargin` to use `textMargin`.
     */
    minMargin?: number;
    /**
     * The space around the label to escape from overlapping.
     * Applied on the label local rect (rather than rotated enlarged rect)
     * Follow the format defined by `format.ts#normalizeCssArray`.
     *
     * Introduce the name `textMargin` rather than reuse the existing names to avoid breaking change:
     *  - `margin` historically have been used to indicate the distance from `label.x/.y` to something:
     *      - `axisLabel.margin` & `axisPointer.label.margin`: to the axis line.
     *      - `calendar.dayLabel/monthLabel/yearLabel.margin`:
     *      - `series-pie.label.margin`: to pie body (deprecated, replaced by `edgeDistance`)
     *      - `series-themeRiver.label.margin`: to the shape edge
     *  - `minMargin` conveys the same meaning as this `textMargin` but has a different nuance,
     *    it works like CSS margin collapse (gap = label1.minMargin/2 + label2.minMargin/2),
     *    and `minMargin` applied on the global bounding rect (parallel to screen x and y) rather
     *    than the original local bounding rect (can be rotated, smaller and more presice).
     * PENDING: @see {LabelMarginType}
     */
    textMargin?: number | number[];
    overflow?: TextStyleProps['overflow'];
    lineOverflow?: TextStyleProps['lineOverflow'];
    ellipsis?: TextStyleProps['ellipsis'];
    rich?: RichTextOption;
}
export interface SeriesLabelOption<TCallbackDataParams extends CallbackDataParams = CallbackDataParams, TNuance extends {
    positionExtra: unknown;
} = {
    positionExtra: never;
}> extends LabelOption<TNuance> {
    formatter?: string | LabelFormatterCallback<TCallbackDataParams>;
}
/**
 * Option for labels on line, like markLine, lines
 */
export interface LineLabelOption extends Omit<LabelOption, 'distance' | 'position'> {
    position?: 'start' | 'middle' | 'end' | 'insideStart' | 'insideStartTop' | 'insideStartBottom' | 'insideMiddle' | 'insideMiddleTop' | 'insideMiddleBottom' | 'insideEnd' | 'insideEndTop' | 'insideEndBottom' | 'insideMiddleBottom';
    /**
     * Distance can be an array.
     * Which will specify horizontal and vertical distance respectively
     */
    distance?: number | number[];
}
export interface LabelLineOption {
    show?: boolean;
    /**
     * If displayed above other elements
     */
    showAbove?: boolean;
    length?: number;
    length2?: number;
    smooth?: boolean | number;
    minTurnAngle?: number;
    lineStyle?: LineStyleOption;
}
export interface SeriesLineLabelOption extends LineLabelOption {
    formatter?: string | LabelFormatterCallback<CallbackDataParams>;
}
export interface LabelLayoutOptionCallbackParams {
    /**
     * Index of data which the label represents.
     * It can be null if label doesn't represent any data.
     */
    dataIndex?: number;
    /**
     * Type of data which the label represents.
     * It can be null if label doesn't represent any data.
     */
    dataType?: SeriesDataType;
    seriesIndex: number;
    text: string;
    align: ZRTextAlign;
    verticalAlign: ZRTextVerticalAlign;
    rect: RectLike;
    labelRect: RectLike;
    labelLinePoints?: number[][];
}
export interface LabelLayoutOption {
    /**
     * If move the overlapped label. If label is still overlapped after moved.
     * It will determine if to hide this label with `hideOverlap` policy.
     *
     * shiftX/Y will keep the order on x/y
     * shuffleX/y will move the label around the original position randomly.
     */
    moveOverlap?: 'shiftX' | 'shiftY' | 'shuffleX' | 'shuffleY';
    /**
     * If hide the overlapped label. It will be handled after move.
     * @default 'none'
     */
    hideOverlap?: boolean;
    /**
     * If label is draggable.
     */
    draggable?: boolean;
    /**
     * Can be absolute px number or percent string.
     */
    x?: number | string;
    y?: number | string;
    /**
     * offset on x based on the original position.
     */
    dx?: number;
    /**
     * offset on y based on the original position.
     */
    dy?: number;
    rotate?: number;
    align?: ZRTextAlign;
    verticalAlign?: ZRTextVerticalAlign;
    width?: number;
    height?: number;
    fontSize?: number;
    labelLinePoints?: number[][];
}
export declare type LabelLayoutOptionCallback = (params: LabelLayoutOptionCallbackParams) => LabelLayoutOption;
export interface TooltipFormatterCallback<T> {
    /**
     * For sync callback
     * params will be an array on axis trigger.
     */
    (params: T, asyncTicket: string): string | HTMLElement | HTMLElement[];
    /**
     * For async callback.
     * Returned html string will be a placeholder when callback is not invoked.
     */
    (params: T, asyncTicket: string, callback: (cbTicket: string, htmlOrDomNodes: string | HTMLElement | HTMLElement[]) => void): string | HTMLElement | HTMLElement[];
}
declare type TooltipBuiltinPosition = 'inside' | 'top' | 'left' | 'right' | 'bottom';
declare type TooltipBoxLayoutOption = Pick<BoxLayoutOptionMixin, 'top' | 'left' | 'right' | 'bottom'>;
export declare type TooltipPositionCallbackParams = CallbackDataParams | CallbackDataParams[];
/**
 * Position relative to the hoverred element. Only available when trigger is item.
 */
export interface TooltipPositionCallback {
    (point: [number, number], 
    /**
     * params will be an array on axis trigger.
     */
    params: TooltipPositionCallbackParams, 
    /**
     * Will be HTMLDivElement when renderMode is html
     * Otherwise it's graphic.Text
     */
    el: HTMLDivElement | ZRText | null, 
    /**
     * Rect of hover elements. Will be null if not hovered
     */
    rect: RectLike | null, size: {
        /**
         * Size of popup content
         */
        contentSize: [number, number];
        /**
         * Size of the chart view
         */
        viewSize: [number, number];
    }): Array<number | string> | TooltipBuiltinPosition | TooltipBoxLayoutOption;
}
/**
 * Common tooltip option
 * Can be configured on series, graphic elements
 */
export interface CommonTooltipOption<FormatterParams> {
    show?: boolean;
    /**
     * When to trigger
     * NOTE: mousewheel may modify view by dataZoom.
     */
    triggerOn?: 'mousemove' | 'click' | 'none' | 'mousewheel' | 'mousemove|click|mousewheel';
    /**
     * Whether to not hide popup content automatically
     */
    alwaysShowContent?: boolean;
    formatter?: string | TooltipFormatterCallback<FormatterParams>;
    /**
     * Formatter of value.
     *
     * Will be ignored if tooltip.formatter is specified.
     */
    valueFormatter?: (value: OptionDataValue | OptionDataValue[], dataIndex: number) => string;
    /**
     * Absolution pixel [x, y] array. Or relative percent string [x, y] array.
     * If trigger is 'item'. position can be set to 'inside' / 'top' / 'left' / 'right' / 'bottom',
     * which is relative to the hovered element.
     *
     * Support to be a callback
     */
    position?: (number | string)[] | TooltipBuiltinPosition | TooltipPositionCallback | TooltipBoxLayoutOption;
    confine?: boolean;
    /**
     * Consider triggered from axisPointer handle, verticalAlign should be 'middle'
     */
    align?: HorizontalAlign;
    verticalAlign?: VerticalAlign;
    /**
     * Delay of show. milesecond.
     */
    showDelay?: number;
    /**
     * Delay of hide. milesecond.
     */
    hideDelay?: number;
    transitionDuration?: number;
    /**
     * Whether mouse is allowed to enter the floating layer of tooltip
     * If you need to interact in the tooltip like with links or buttons, it can be set as true.
     */
    enterable?: boolean;
    /**
     * Whether enable display transition when show/hide tooltip.
     * Defaults to `true` for backward compatibility.
     * If set to `false`, the tooltip 'display' will be set to 'none' when hidden.
     * @default true
     * @since v6.0.0
     */
    displayTransition?: boolean;
    backgroundColor?: ColorString;
    borderColor?: ColorString;
    borderRadius?: number;
    borderWidth?: number;
    shadowBlur?: number;
    shadowColor?: string;
    shadowOffsetX?: number;
    shadowOffsetY?: number;
    /**
     * Padding between tooltip content and tooltip border.
     */
    padding?: number | number[];
    /**
     * Available when renderMode is 'html'
     */
    extraCssText?: string;
    textStyle?: Pick<LabelOption, 'color' | 'fontStyle' | 'fontWeight' | 'fontFamily' | 'fontSize' | 'lineHeight' | 'width' | 'height' | 'textBorderColor' | 'textBorderWidth' | 'textShadowColor' | 'textShadowBlur' | 'textShadowOffsetX' | 'textShadowOffsetY' | 'align'> & {
        decoration?: string;
    };
}
export declare type ComponentItemTooltipOption<T> = CommonTooltipOption<T> & {
    content?: string;
    /**
     * Whether to encode HTML content according to `tooltip.renderMode`.
     *
     * e.g. renderMode 'html' needs to encode but 'richText' does not.
     */
    encodeHTMLContent?: boolean;
    formatterParams?: ComponentItemTooltipLabelFormatterParams;
};
export declare type ComponentItemTooltipLabelFormatterParams = {
    componentType: string;
    name: string;
    $vars: string[];
} & {
    [key in string]: unknown;
};
/**
 * Tooltip option configured on each series
 */
export declare type SeriesTooltipOption = CommonTooltipOption<CallbackDataParams> & {
    trigger?: 'item' | 'axis' | boolean | 'none';
};
declare type LabelFormatterParams = {
    value: ScaleDataValue;
    axisDimension: string;
    axisIndex: number;
    seriesData: CallbackDataParams[];
};
/**
 * Common axis option. can be configured on each axis
 */
export interface CommonAxisPointerOption {
    show?: boolean | 'auto';
    z?: number;
    zlevel?: number;
    triggerOn?: 'click' | 'mousemove' | 'none' | 'mousemove|click';
    type?: 'line' | 'shadow' | 'none';
    snap?: boolean;
    triggerTooltip?: boolean;
    triggerEmphasis?: boolean;
    /**
     * current value. When using axisPointer.handle, value can be set to define the initial position of axisPointer.
     */
    value?: ScaleDataValue;
    status?: 'show' | 'hide';
    label?: LabelOption & {
        precision?: 'auto' | number;
        margin?: number;
        /**
         * String template include variable {value} or callback function
         */
        formatter?: string | ((params: LabelFormatterParams) => string);
    };
    animation?: boolean | 'auto';
    animationDurationUpdate?: number;
    animationEasingUpdate?: ZREasing;
    /**
     * Available when type is 'line'
     */
    lineStyle?: LineStyleOption;
    /**
     * Available when type is 'shadow'
     */
    shadowStyle?: AreaStyleOption;
    handle?: {
        show?: boolean;
        icon?: string;
        /**
         * The size of the handle
         */
        size?: number | number[];
        /**
         * Distance from handle center to axis.
         */
        margin?: number;
        color?: ColorString;
        /**
         * Throttle for mobile performance
         */
        throttle?: number;
    } & ShadowOptionMixin;
    seriesDataIndices?: {
        seriesIndex: number;
        dataIndex: number;
        dataIndexInside: number;
    }[];
}
export interface ComponentOption {
    mainType?: string;
    type?: string;
    id?: OptionId;
    name?: OptionName;
    z?: number;
    zlevel?: number;
    coordinateSystem?: string;
    coordinateSystemUsage?: CoordinateSystemUsageOption;
    coord?: CoordinateSystemDataCoord;
}
/**
 * - "data": Each data item is laid out based on a coord sys.
 *   See `COORD_SYS_USAGE_KIND_DATA`.
 * - "box": The overall bounding rect or anchor point is calculated based on a coord sys.
 *   See `COORD_SYS_USAGE_KIND_BOX`.
 *   e.g.,
 *      grid rect (cartesian rect) is calculate based on matrix/calendar coord sys;
 *      pie center is calculated based on calendar/cartesian;
 *
 * The default value (if not declared in option `coordinateSystemUsage`):
 *  For series, be "data", since this is the most case and backward compatible.
 *  For non-series components, be "box", since "data" is not applicable.
 */
export declare type CoordinateSystemUsageOption = 'data' | 'box';
export declare type BlurScope = 'coordinateSystem' | 'series' | 'global';
/**
 * can be array of data indices.
 * Or may be an dictionary if have different types of data like in graph.
 */
export declare type InnerFocus = DefaultEmphasisFocus | ArrayLike<number> | Dictionary<ArrayLike<number>>;
export interface DefaultStatesMixin {
    emphasis?: any;
    select?: any;
    blur?: any;
}
export declare type DefaultEmphasisFocus = 'none' | 'self' | 'series';
export interface DefaultStatesMixinEmphasis {
    /**
     * self: Focus self and blur all others.
     * series: Focus series and blur all other series.
     */
    focus?: DefaultEmphasisFocus;
}
export interface StatesMixinBase {
    emphasis?: unknown;
    select?: unknown;
    blur?: unknown;
}
export interface StatesOptionMixin<StateOption, StatesMixin extends StatesMixinBase> {
    /**
     * Emphasis states
     */
    emphasis?: StateOption & StatesMixin['emphasis'] & {
        /**
         * Scope of blurred element when focus.
         *
         * coordinateSystem: blur others in the same coordinateSystem
         * series: blur others in the same series
         * global: blur all others
         *
         * Default to be coordinate system.
         */
        blurScope?: BlurScope;
        /**
         * If emphasis state is disabled.
         */
        disabled?: boolean;
    };
    /**
     * Select states
     */
    select?: StateOption & StatesMixin['select'] & {
        disabled?: boolean;
    };
    /**
     * Blur states.
     */
    blur?: StateOption & StatesMixin['blur'];
}
export interface UniversalTransitionOption {
    enabled?: boolean;
    /**
     * Animation delay of each divided element
     */
    delay?: (index: number, count: number) => number;
    /**
     * How to divide the shape in combine and split animation.
     */
    divideShape?: 'clone' | 'split';
    /**
     * Series will have transition between if they have same seriesKey.
     * Usually it is a string. It can also be an array,
     * which means it can be transition from or to multiple series with each key in this array item.
     *
     * Note:
     * If two series have both array seriesKey. They will be compared after concated to a string(which is order independent)
     * Transition between string key has higher priority.
     *
     * Default to use series id.
     */
    seriesKey?: string | string[];
}
export interface SeriesOption<StateOption = unknown, StatesMixin extends StatesMixinBase = DefaultStatesMixin> extends ComponentOption, AnimationOptionMixin, ColorPaletteOptionMixin, StatesOptionMixin<StateOption, StatesMixin> {
    mainType?: 'series';
    silent?: boolean;
    blendMode?: string;
    /**
     * Cursor when mouse on the elements
     */
    cursor?: string;
    /**
     * groupId of data. can be used for doing drilldown / up animation
     * It will be ignored if:
     *  - groupId is specified in each data
     *  - encode.itemGroupId is given.
     */
    dataGroupId?: OptionId;
    data?: unknown;
    colorBy?: ColorBy;
    legendHoverLink?: boolean;
    /**
     * Configurations about progressive rendering
     */
    progressive?: number | false;
    progressiveThreshold?: number;
    progressiveChunkMode?: 'mod';
    hoverLayerThreshold?: number;
    /**
     * When dataset is used, seriesLayoutBy specifies whether the column or the row of dataset is mapped to the series
     * namely, the series is "layout" on columns or rows
     * @default 'column'
     */
    seriesLayoutBy?: 'column' | 'row';
    labelLine?: LabelLineOption;
    /**
     * Overall label layout option in label layout stage.
     */
    labelLayout?: LabelLayoutOption | LabelLayoutOptionCallback;
    /**
     * Animation config for state transition.
     */
    stateAnimation?: AnimationOption;
    /**
     * If enabled universal transition cross series.
     * @example
     *  universalTransition: true
     *  universalTransition: { enabled: true }
     */
    universalTransition?: boolean | UniversalTransitionOption;
    /**
     * Map of selected data
     * key is name or index of data.
     */
    selectedMap?: Dictionary<boolean> | 'all';
    selectedMode?: 'single' | 'multiple' | 'series' | boolean;
}
export interface SeriesOnCartesianOptionMixin {
    xAxisIndex?: number;
    yAxisIndex?: number;
    xAxisId?: OptionId;
    yAxisId?: OptionId;
}
export interface SeriesOnPolarOptionMixin {
    polarIndex?: number;
    polarId?: OptionId;
}
export interface SeriesOnSingleOptionMixin {
    singleAxisIndex?: number;
    singleAxisId?: OptionId;
}
export interface SeriesOnGeoOptionMixin {
    geoIndex?: number;
    geoId?: OptionId;
}
export interface SeriesOnRadarOptionMixin {
    radarIndex?: number;
    radarId?: OptionId;
}
export interface ComponentOnCalendarOptionMixin {
    calendarIndex?: number;
    calendarId?: OptionId;
}
export interface ComponentOnMatrixOptionMixin {
    matrixIndex?: number;
    matrixId?: OptionId;
}
export interface SeriesLargeOptionMixin {
    large?: boolean;
    largeThreshold?: number;
}
export interface SeriesStackOptionMixin {
    stack?: string;
    stackStrategy?: 'samesign' | 'all' | 'positive' | 'negative';
    stackOrder?: 'seriesAsc' | 'seriesDesc';
}
declare type SamplingFunc = (frame: ArrayLike<number>) => number;
export interface SeriesSamplingOptionMixin {
    sampling?: 'none' | 'average' | 'min' | 'max' | 'minmax' | 'sum' | 'lttb' | SamplingFunc;
}
export interface SeriesEncodeOptionMixin {
    datasetIndex?: number;
    datasetId?: string | number;
    seriesLayoutBy?: SeriesLayoutBy;
    sourceHeader?: OptionSourceHeader;
    dimensions?: DimensionDefinitionLoose[];
    encode?: OptionEncode;
}
export declare type SeriesEncodableModel = SeriesModel<SeriesOption & SeriesEncodeOptionMixin>;
export interface AriaLabelOption {
    enabled?: boolean;
    description?: string;
    general?: {
        withTitle?: string;
        withoutTitle?: string;
    };
    series?: {
        maxCount?: number;
        single?: {
            prefix?: string;
            withName?: string;
            withoutName?: string;
        };
        multiple?: {
            prefix?: string;
            withName?: string;
            withoutName?: string;
            separator?: {
                middle?: string;
                end?: string;
            };
        };
    };
    data?: {
        maxCount?: number;
        allData?: string;
        partialData?: string;
        withName?: string;
        withoutName?: string;
        separator?: {
            middle?: string;
            end?: string;
        };
        excludeDimensionId?: number[];
    };
}
export interface AriaOption extends AriaLabelOption {
    mainType?: 'aria';
    enabled?: boolean;
    label?: AriaLabelOption;
    decal?: {
        show?: boolean;
        decals?: DecalObject | DecalObject[];
    };
}
export interface AriaOptionMixin {
    aria?: AriaOption;
}
export interface RoamPayload extends Payload {
    type: `${string}${typeof ROAM_ACTION_TYPE_SUFFIX}`;
    dx: number;
    dy: number;
    zoom: number;
    originX: number;
    originY: number;
}
export declare const ROAM_ACTION_TYPE_SUFFIX = "Roam";
/**
 * @usage class Xxx implements RoamHostModel {...}
 */
export interface RoamHostModel {
    __ownRoamView: () => View | NullUndefined;
}
export declare type RoamHostComponentOrSeries = ComponentModel<ComponentOption & RoamOptionMixin> & RoamHostModel;
export interface RoamHostView {
    /**
     * A performance shortcut - called by action handler to update the view directly
     * without any data/visual processing (which are assumed to be unchanged), while
     * ensuring consistent behavior between internal and external action triggers.
     *
     * Only "own coordinate system" is updated here. Dependent series/components should
     * be updated in `ChartView['updateTransform']` or `ComponentView['updateTransform']`.
     */
    __updateOnOwnRoam(payload: RoamPayload, componentOrSeries: ComponentModel, api: ExtensionAPI): void;
}
export declare type ChartComponentRoamHostView = (ChartView | ComponentView) & RoamHostView;
