import * as zrender from 'zrender/lib/zrender.js';
import Eventful, { EventCallbackSingleParam } from 'zrender/lib/core/Eventful.js';
import { GlobalModelSetOptionOpts } from '../model/Global.js';
import type { CustomSeriesRenderItem } from '../chart/custom/CustomSeries.js';
import * as modelUtil from '../util/model.js';
import { CoordinateSystemCreator } from '../coord/CoordinateSystem.js';
import { Payload, RendererType, ECActionEvent, ActionHandler, ActionInfo, OptionPreprocessor, PostUpdater, LoadingEffectCreator, StageHandlerOverallReset, StageHandler, DimensionDefinitionLoose, ThemeOption, ECBasicOption, ZRColor, ComponentMainType, ScaleDataValue, ZRElementEventName, ECElementEvent, AnimationOption, CoordinateSystemDataLayout, NullUndefined } from '../util/types.js';
import { registerExternalTransform } from '../data/helper/transform.js';
import { LocaleOption } from './locale.js';
import { LifecycleEvents, UpdateLifecycleTransitionItem, UpdateLifecycleParams, UpdateLifecycleTransitionOpt } from './lifecycle.js';
import type geoSourceManager from '../coord/geo/geoSourceManager.js';
declare type ModelFinder = modelUtil.ModelFinder;
export declare const version = "6.1.0";
export declare const dependencies: {
    zrender: string;
};
export declare const PRIORITY: {
    PROCESSOR: {
        SERIES_FILTER: number;
        AXIS_STATISTICS: number;
        FILTER: number;
        STATISTIC: number;
        STATISTICS: number;
    };
    VISUAL: {
        LAYOUT: number;
        PROGRESSIVE_LAYOUT: number;
        GLOBAL: number;
        CHART: number;
        POST_CHART_LAYOUT: number;
        COMPONENT: number;
        BRUSH: number;
        CHART_ITEM: number;
        ARIA: number;
        DECAL: number;
    };
};
/**
 * @tutorial [EC_CYCLE] (ec updating/rendering cycles):
 *
 *  - Common Rules:
 *    - Nested entry is not allowed. If triggering a new run of EC_CYCLE during a
 *      unfinished run, the new run will be delayed until the current run finishes
 *      (if triggered by `dispatchAction`), or throw error (if triggered by other API calls).
 *    - All user-visible ec events are triggered outside EC_CYCLE.
 *      (i.e. be triggered after `this[IN_EC_CYCLE_KEY]` becoming `false`).
 *
 *  - [EC_FULL_UPDATE_CYCLE]:
 *    - It designates a run of a series of processing/updating/rendering.
 *    - It is triggered by:
 *      - `setOption`
 *      - `dispatchAction`
 *        (It is typically internally triggered by user inputs; but can also an explicit API call.)
 *      - `resize`
 *      - The next "animation frame" if in `lazyMode: true`.
 *    - A run of EC_FULL_UPDATE_CYCLE comprises:
 *      - EC_PREPARE (may be absent)
 *      - EC_FULL_UPDATE:
 *        - CoordinateSystem['create']
 *        - Data processing (may be absent) (see `registerProcessor`)
 *        - CoordinateSystem['update'] (may be absent)
 *        - Visual encoding (may be absent) (see `registerVisual`)
 *        - Layout (may be absent) (see `registerLayout`)
 *        - Rendering (`ComponentView` or `SeriesView`)
 *
 *  - [EC_PARTIAL_UPDATE_CYCLE]s:
 *      - They are shortcuts for performance.
 *      - They are triggered by:
 *        - `dispatchAction`
 *      - These steps are typically omitted:
 *        - No EC_PREPARE
 *        - No CoordinateSystem['create'] and CoordinateSystem['update']
 *      - They require careful implementation, otherwise inconsistency may be introduced.
 *
 *  - [EC_PROGRESSIVE_CYCLE]:
 *    - It also carries out a series of processing/updating/rendering.
 *    - It is performed in each subsequent "animation frame" until finished.
 *    - It can be triggered by EC_FULL_UPDATE_CYCLE, EC_PARTIAL_UPDATE_CYCLE or EC_APPEND_DATA_CYCLE.
 *    - A run of EC_PROGRESSIVE_CYCLE comprises:
 *      - Data processing (may be absent) (see `registerProcessor`)
 *      - Visual encoding (may be absent) (see `registerVisual`)
 *      - Layout (may be absent) (see `registerLayout`)
 *      - Rendering (`ComponentView` or `SeriesView`)
 *    - PENDING: currently all data processing tasks (via `registerProcessor`) run in "block" mode.
 *      (see `performDataProcessorTasks`).
 *
 *  - [EC_APPEND_DATA_CYCLE]:
 *    - See `appendData`. It is only supported for some special cases.
 *
 *  - [SERIES_SPECIFIC_CYCLE]s:
 *    - Series may have specific update/render cycles. For example, graph force layout performs
 *      layout and rendering in each "animation frame".
 *
 *  - Model updating:
 *    - Model can only be modified at the beginning of ec cycles, including only:
 *      - EC_PREPARE (see method `prepare()`) in `setOption` call.
 *      - EC action handlers in `dispatchAction` call.
 *      - `appendData` (a special case, where only data can be modified).
 *
 *  - The lifetime of CoordinateSystem/Axis/Scale instances:
 *    - They are only re-created per run of EC_FULL_UPDATE_CYCLE.
 *
 *  - Global caches: see `cycleCache.ts`
 */
declare const IN_EC_CYCLE_KEY: "__flagInMainProcess";
declare const EC_UPDATE_CYCLE_VERSION_KEY: "__mainProcessVersion";
declare const PENDING_UPDATE: "__pendingUpdate";
declare const STATUS_NEEDS_UPDATE_KEY: "__needsUpdateStatus";
declare const CONNECT_STATUS_KEY: "__connectUpdateStatus";
export declare type SetOptionTransitionOpt = UpdateLifecycleTransitionOpt;
export declare type SetOptionTransitionOptItem = UpdateLifecycleTransitionItem;
export interface SetOptionOpts {
    notMerge?: boolean;
    lazyUpdate?: boolean;
    silent?: boolean;
    replaceMerge?: GlobalModelSetOptionOpts['replaceMerge'];
    transition?: SetOptionTransitionOpt;
}
export interface ResizeOpts {
    width?: number | 'auto';
    height?: number | 'auto';
    animation?: AnimationOption;
    silent?: boolean;
}
export interface SetThemeOpts {
    silent?: boolean;
}
interface PostIniter {
    (chart: EChartsType): void;
}
declare type UpdateMethod = (this: ECharts, payload?: Payload, renderParams?: UpdateLifecycleParams) => void;
declare let updateMethods: {
    prepareAndUpdate: UpdateMethod;
    update: UpdateMethod;
    updateTransform: UpdateMethod;
    updateView: UpdateMethod;
    updateVisual: UpdateMethod;
    updateLayout: UpdateMethod;
};
export declare type ECUpdateMethodName = (keyof typeof updateMethods) | 'none';
declare type RenderedEventParam = {
    elapsedTime: number;
};
declare type ECEventDefinition = {
    [key in ZRElementEventName]: EventCallbackSingleParam<ECElementEvent>;
} & {
    rendered: EventCallbackSingleParam<RenderedEventParam>;
    finished: () => void | boolean;
} & {
    [key: string]: (...args: unknown[]) => void | boolean;
};
export declare type EChartsInitOpts = {
    locale?: string | LocaleOption;
    renderer?: RendererType;
    devicePixelRatio?: number;
    useDirtyRect?: boolean;
    useCoarsePointer?: boolean;
    pointerSize?: number;
    ssr?: boolean;
    width?: number | string;
    height?: number | string;
};
declare class ECharts extends Eventful<ECEventDefinition> {
    /**
     * @readonly
     */
    id: string;
    /**
     * Group id
     * @readonly
     */
    group: string;
    private _ssr;
    private _zr;
    private _dom;
    private _model;
    private _throttledZrFlush;
    private _theme;
    private _locale;
    private _chartsViews;
    private _chartsMap;
    private _componentsViews;
    private _componentsMap;
    private _coordSysMgr;
    private _api;
    private _scheduler;
    private _messageCenter;
    private _pendingActions;
    protected _$eventProcessor: never;
    private _disposed;
    private _loadingFX;
    private _usingTHL;
    private [PENDING_UPDATE];
    private [IN_EC_CYCLE_KEY];
    private [EC_UPDATE_CYCLE_VERSION_KEY];
    private [CONNECT_STATUS_KEY];
    private [STATUS_NEEDS_UPDATE_KEY];
    constructor(dom: HTMLElement, theme?: string | ThemeOption, opts?: EChartsInitOpts);
    private _onframe;
    getDom(): HTMLElement;
    getId(): string;
    getZr(): zrender.ZRenderType;
    isSSR(): boolean;
    /**
     * Usage:
     * chart.setOption(option, notMerge, lazyUpdate);
     * chart.setOption(option, {
     *     notMerge: ...,
     *     lazyUpdate: ...,
     *     silent: ...
     * });
     *
     * @param opts opts or notMerge.
     * @param opts.notMerge Default `false`.
     * @param opts.lazyUpdate Default `false`. Useful when setOption frequently.
     * @param opts.silent Default `false`.
     * @param opts.replaceMerge Default undefined.
     */
    setOption<Opt extends ECBasicOption>(option: Opt, notMerge?: boolean, lazyUpdate?: boolean): void;
    setOption<Opt extends ECBasicOption>(option: Opt, opts?: SetOptionOpts): void;
    /**
     * Update theme with name or theme option and repaint the chart.
     * @param theme Theme name or theme option.
     * @param opts Optional settings
     */
    setTheme(theme: string | ThemeOption, opts?: SetThemeOpts): void;
    private _updateTheme;
    private getModel;
    getOption(): ECBasicOption;
    getWidth(): number;
    getHeight(): number;
    getDevicePixelRatio(): number;
    /**
     * Get canvas which has all thing rendered
     * @deprecated Use renderToCanvas instead.
     */
    getRenderedCanvas(opts?: any): HTMLCanvasElement;
    renderToCanvas(opts?: {
        backgroundColor?: ZRColor;
        pixelRatio?: number;
    }): HTMLCanvasElement;
    renderToSVGString(opts?: {
        useViewBox?: boolean;
    }): string;
    /**
     * Get svg data url
     */
    getSvgDataURL(): string;
    getDataURL(opts?: {
        type?: 'png' | 'jpeg' | 'svg';
        pixelRatio?: number;
        backgroundColor?: ZRColor;
        excludeComponents?: ComponentMainType[];
    }): string;
    getConnectedDataURL(opts?: {
        type?: 'png' | 'jpeg' | 'svg';
        pixelRatio?: number;
        backgroundColor?: ZRColor;
        connectedBackgroundColor?: ZRColor;
        excludeComponents?: string[];
    }): string;
    /**
     * Convert from logical coordinate system to pixel coordinate system.
     * See CoordinateSystem#convertToPixel.
     *
     * TODO / PENDING:
     *  currently `convertToPixel` `convertFromPixel` `convertToLayout` may not be suitable
     *  for some extremely performance-sensitive scenarios (such as, handling massive amounts of data),
     *  since it performce "find component" every time.
     *  And it is not friendly to the nuances between different coordinate systems.
     *  @see https://github.com/apache/echarts/issues/20985 for details
     *
     * @see CoordinateSystem['dataToPoint'] for parameters and return.
     * @see CoordinateSystemDataCoord
     */
    convertToPixel(finder: ModelFinder, value: ScaleDataValue): number;
    convertToPixel(finder: ModelFinder, value: ScaleDataValue[]): number[];
    convertToPixel(finder: ModelFinder, value: ScaleDataValue | ScaleDataValue[]): number | number[];
    convertToPixel(finder: ModelFinder, value: (ScaleDataValue | ScaleDataValue[] | NullUndefined)[]): number | number[];
    /**
     * Convert from logical coordinate system to pixel coordinate system.
     * See CoordinateSystem#convertToPixel.
     *
     * @see CoordinateSystem['dataToLayout'] for parameters and return.
     * @see CoordinateSystemDataCoord
     */
    convertToLayout(finder: ModelFinder, value: (ScaleDataValue | NullUndefined) | (ScaleDataValue | ScaleDataValue[] | NullUndefined)[], opt?: unknown): CoordinateSystemDataLayout;
    /**
     * Convert from pixel coordinate system to logical coordinate system.
     * See CoordinateSystem#convertFromPixel.
     *
     * @see CoordinateSystem['pointToData'] for parameters and return.
     */
    convertFromPixel(finder: ModelFinder, value: number): number;
    convertFromPixel(finder: ModelFinder, value: number[]): number[];
    convertFromPixel(finder: ModelFinder, value: number | number[]): number | number[];
    /**
     * Is the specified coordinate systems or components contain the given pixel point.
     * @param {Array|number} value
     * @return {boolean} result
     */
    containPixel(finder: ModelFinder, value: number[]): boolean;
    /**
     * Get visual from series or data.
     * @param finder
     *        If string, e.g., 'series', means {seriesIndex: 0}.
     *        If Object, could contain some of these properties below:
     *        {
     *            seriesIndex / seriesId / seriesName,
     *            dataIndex / dataIndexInside
     *        }
     *        If dataIndex is not specified, series visual will be fetched,
     *        but not data item visual.
     *        If all of seriesIndex, seriesId, seriesName are not specified,
     *        visual will be fetched from first series.
     * @param visualType 'color', 'symbol', 'symbolSize'
     */
    getVisual(finder: ModelFinder, visualType: string): string | number | number[] | import("zrender/lib/graphic/Pattern").PatternObject | import("zrender/lib/graphic/LinearGradient").LinearGradientObject | import("zrender/lib/graphic/RadialGradient").RadialGradientObject;
    /**
     * Get view of corresponding component model
     */
    private getViewOfComponentModel;
    /**
     * Get view of corresponding series model
     */
    private getViewOfSeriesModel;
    private _initEvents;
    isDisposed(): boolean;
    clear(): void;
    dispose(): void;
    /**
     * Resize the chart
     */
    resize(opts?: ResizeOpts): void;
    /**
     * Show loading effect
     * @param name 'default' by default
     * @param cfg cfg of registered loading effect
     */
    showLoading(cfg?: object): void;
    showLoading(name?: string, cfg?: object): void;
    /**
     * Hide loading effect
     */
    hideLoading(): void;
    makeActionFromEvent(eventObj: ECActionEvent): Payload;
    /**
     * @param opt If pass boolean, means opt.silent
     * @param opt.silent Default `false`. Whether trigger events.
     * @param opt.flush Default `undefined`.
     *        true: Flush immediately, and then pixel in canvas can be fetched
     *            immediately. Caution: it might affect performance.
     *        false: Not flush.
     *        undefined: Auto decide whether perform flush.
     */
    dispatchAction(payload: Payload, opt?: boolean | {
        silent?: boolean;
        flush?: boolean | undefined;
    }): void;
    updateLabelLayout(): void;
    appendData(params: {
        seriesIndex: number;
        data: any;
    }): void;
    private static internalField;
}
/**
 * @param opts.devicePixelRatio Use window.devicePixelRatio by default
 * @param opts.renderer Can choose 'canvas' or 'svg' to render the chart.
 * @param opts.width Use clientWidth of the input `dom` by default.
 *        Can be 'auto' (the same as null/undefined)
 * @param opts.height Use clientHeight of the input `dom` by default.
 *        Can be 'auto' (the same as null/undefined)
 * @param opts.locale Specify the locale.
 * @param opts.useDirtyRect Enable dirty rectangle rendering or not.
 */
export declare function init(dom?: HTMLElement | null, theme?: string | object | null, opts?: EChartsInitOpts): EChartsType;
/**
 * @usage
 * (A)
 * ```js
 * let chart1 = echarts.init(dom1);
 * let chart2 = echarts.init(dom2);
 * chart1.group = 'xxx';
 * chart2.group = 'xxx';
 * echarts.connect('xxx');
 * ```
 * (B)
 * ```js
 * let chart1 = echarts.init(dom1);
 * let chart2 = echarts.init(dom2);
 * echarts.connect('xxx', [chart1, chart2]);
 * ```
 */
export declare function connect(groupId: string | EChartsType[]): string;
export declare function disconnect(groupId: string): void;
/**
 * Alias and backward compatibility
 * @deprecated
 */
export declare const disConnect: typeof disconnect;
/**
 * Dispose a chart instance
 */
export declare function dispose(chart: EChartsType | HTMLElement | string): void;
export declare function getInstanceByDom(dom: HTMLElement): EChartsType | undefined;
export declare function getInstanceById(key: string): EChartsType | undefined;
/**
 * Register theme
 */
export declare function registerTheme(name: string, theme: ThemeOption): void;
/**
 * Register option preprocessor
 */
export declare function registerPreprocessor(preprocessorFunc: OptionPreprocessor): void;
/**
 * NOTICE: Alway run in block way (no progessive is allowed).
 */
export declare function registerProcessor(priority: number | StageHandler | StageHandlerOverallReset, processor?: StageHandler | StageHandlerOverallReset): void;
/**
 * Register postIniter
 * @param {Function} postInitFunc
 */
export declare function registerPostInit(postInitFunc: PostIniter): void;
/**
 * Register postUpdater
 * @param {Function} postUpdateFunc
 */
export declare function registerPostUpdate(postUpdateFunc: PostUpdater): void;
export declare function registerUpdateLifecycle<T extends keyof LifecycleEvents>(name: T, cb: (...args: LifecycleEvents[T]) => void): void;
/**
 * @usage
 * registerAction('someAction', 'someEvent', function () { ... });
 * registerAction('someAction', function () { ... });
 * registerAction(
 *     {type: 'someAction', event: 'someEvent', update: 'updateView'},
 *     function () { ... }
 * );
 * registerAction({
 *     type: 'someAction',
 *     event: 'someEvent',
 *     update: 'updateView'
 *     action: function () { ... }
 *     refineEvent: function () { ... }
 * });
 * @see {ActionInfo} for more details.
 */
export declare function registerAction(type: string, eventType: string, action: ActionHandler): void;
export declare function registerAction(type: string, action: ActionHandler): void;
export declare function registerAction(actionInfo: ActionInfo, action?: ActionHandler): void;
export declare function registerCoordinateSystem(type: string, coordSysCreator: CoordinateSystemCreator): void;
/**
 * Get dimensions of specified coordinate system.
 * @param {string} type
 * @return {Array.<string|Object>}
 */
export declare function getCoordinateSystemDimensions(type: string): DimensionDefinitionLoose[];
export declare function registerCustomSeries(seriesType: string, renderItem: CustomSeriesRenderItem): void;
export { registerLocale } from './locale.js';
/**
 * Layout is a special stage of visual encoding
 * Most visual encoding like color are common for different chart
 * But each chart has it's own layout algorithm
 */
declare function registerLayout(priority: number, layoutTask: StageHandler | StageHandlerOverallReset): void;
declare function registerLayout(layoutTask: StageHandler | StageHandlerOverallReset): void;
declare function registerVisual(priority: number, layoutTask: StageHandler | StageHandlerOverallReset): void;
declare function registerVisual(layoutTask: StageHandler | StageHandlerOverallReset): void;
export { registerLayout, registerVisual };
export declare function registerLoading(name: string, loadingFx: LoadingEffectCreator): void;
/**
 * ZRender need a canvas context to do measureText.
 * But in node environment canvas may be created by node-canvas.
 * So we need to specify how to create a canvas instead of using document.createElement('canvas')
 *
 *
 * @deprecated use setPlatformAPI({ createCanvas }) instead.
 *
 * @example
 *     let Canvas = require('canvas');
 *     let echarts = require('echarts');
 *     echarts.setCanvasCreator(function () {
 *         // Small size is enough.
 *         return new Canvas(32, 32);
 *     });
 */
export declare function setCanvasCreator(creator: () => HTMLCanvasElement): void;
declare type RegisterMapParams = Parameters<typeof geoSourceManager.registerMap>;
/**
 * The parameters and usage: see `geoSourceManager.registerMap`.
 * Compatible with previous `echarts.registerMap`.
 */
export declare function registerMap(mapName: RegisterMapParams[0], geoJson: RegisterMapParams[1], specialAreas?: RegisterMapParams[2]): void;
export declare function getMap(mapName: string): any;
export declare const registerTransform: typeof registerExternalTransform;
export declare const dataTool: {};
export interface EChartsType extends ECharts {
}
