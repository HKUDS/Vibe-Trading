import type GlobalModel from '../model/Global.js';
import type ExtensionAPI from './ExtensionAPI.js';
import type { CoordinateSystem, CoordinateSystemCreator, CoordinateSystemMaster } from '../coord/CoordinateSystem.js';
import ComponentModel from '../model/Component.js';
import { CoordinateSystemDataCoord, NullUndefined } from '../util/types.js';
declare class CoordinateSystemManager {
    private _normalMasterList;
    private _nonSeriesBoxMasterList;
    /**
     * Typically,
     *  - in `create`, a coord sys lays out based on a given rect;
     *  - in `update`, update the pixel and data extent of there axes (if any) based on processed `series.data`.
     * After that, a coord sys can serve (typically by `dataToPoint`/`dataToLayout`/`pointToData`).
     * If the coordinate system do not lay out based on `series.data`, `update` is not needed.
     */
    create(ecModel: GlobalModel, api: ExtensionAPI): void;
    /**
     * @see CoordinateSystem['create']
     */
    update(ecModel: GlobalModel, api: ExtensionAPI): void;
    getCoordinateSystems(): CoordinateSystemMaster[];
    static register: (type: string, creator: CoordinateSystemCreator) => void;
    static get: (type: string) => CoordinateSystemCreator;
}
export declare const BOX_COORD_SYS_COORD_FROM_PROP_COORD: 1;
export declare const BOX_COORD_SYS_COORD_FROM_PROP_COORD2: 2;
export declare type BoxCoordinateSystemCoordFrom = typeof BOX_COORD_SYS_COORD_FROM_PROP_COORD | typeof BOX_COORD_SYS_COORD_FROM_PROP_COORD2;
declare type BoxCoordinateSystemGetCoord2 = (model: ComponentModel) => CoordinateSystemDataCoord;
/**
 * @see_also `createBoxLayoutReference`
 * @see_also `injectCoordSysByOption`
 */
export declare function registerLayOutOnCoordSysUsage(opt: {
    fullType: ComponentModel['type'];
    getCoord2?: BoxCoordinateSystemGetCoord2;
}): void;
/**
 * @return Be an object, but never be NullUndefined.
 */
export declare function getCoordForCoordSysUsageKindBox(model: ComponentModel): {
    coord: CoordinateSystemDataCoord | NullUndefined;
    from: BoxCoordinateSystemCoordFrom;
};
/**
 * - `COORD_SYS_USAGE_KIND_DATA`: each data item is laid out based on a coord sys.
 * - `COORD_SYS_USAGE_KIND_BOX`: the overall bounding rect or anchor point is calculated based on a coord sys.
 *   e.g.,
 *      grid rect (cartesian rect) is calculate based on matrix/calendar coord sys;
 *      pie center is calculated based on calendar/cartesian;
 *
 * The default value (if not declared in option `coordinateSystemUsage`):
 *  For series, use `COORD_SYS_USAGE_KIND_DATA`, since this is the most common case and backward compatible.
 *  For non-series components, use `COORD_SYS_USAGE_KIND_BOX`, since `COORD_SYS_USAGE_KIND_DATA` is not applicable.
 */
export declare const COORD_SYS_USAGE_KIND_NONE: 0;
export declare const COORD_SYS_USAGE_KIND_DATA: 1;
export declare const COORD_SYS_USAGE_KIND_BOX: 2;
export declare type CoordinateSystemUsageKind = typeof COORD_SYS_USAGE_KIND_NONE | typeof COORD_SYS_USAGE_KIND_DATA | typeof COORD_SYS_USAGE_KIND_BOX;
export declare function decideCoordSysUsageKind(model: ComponentModel, printError?: boolean): {
    kind: CoordinateSystemUsageKind;
    coordSysType: string | NullUndefined;
};
/**
 * These cases are considered:
 *  (A) Most series can use only "COORD_SYS_USAGE_KIND_DATA", but "COORD_SYS_USAGE_KIND_BOX" is not applicable:
 *    - e.g., series.heatmap, series.line, series.bar, series.scatter, ...
 *  (B) Some series and most components can use only "COORD_SYS_USAGE_KIND_BOX", but "COORD_SYS_USAGE_KIND_DATA"
 *    is not applicable:
 *    - e.g., series.pie, series.funnel, ...
 *    - e.g., grid, polar, geo, title, ...
 *  (C) Several series can use both "COORD_SYS_USAGE_KIND_BOX" and "COORD_SYS_USAGE_KIND_DATA", even at the same time:
 *    - e.g., series.graph, series.map
 *      - If graph or map series use "COORD_SYS_USAGE_KIND_BOX", it creates a internal coord sys as
 *        "COORD_SYS_USAGE_KIND_DATA" to lay out its data.
 *      - Graph series can use matrix coord sys as either the "COORD_SYS_USAGE_KIND_DATA" (each item layout
 *        on one cell) or "COORD_SYS_USAGE_KIND_BOX" (the entire series are layout within one cell).
 *    - To achieve this effect,
 *      `series.coordinateSystemUsage: 'box'` needs to be specified explicitly.
 *
 * Check these echarts option settings:
 *  - If `series: {type: 'bar'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "cartesian2d",
 *      COORD_SYS_USAGE_KIND_BOX: "none".
 *      (since `coordinateSystem: 'cartesian2d'` is the default option in bar.)
 *  - If `grid: {coordinateSystem: 'matrix'}`
 *      COORD_SYS_USAGE_KIND_DATA: "none",
 *      COORD_SYS_USAGE_KIND_BOX: "matrix".
 *  - If `series: {type: 'pie', coordinateSystem: 'matrix'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "none",
 *      COORD_SYS_USAGE_KIND_BOX: "matrix".
 *      (since `coordinateSystemUsage: 'box'` is the default option in pie.)
 *  - If `series: {type: 'graph', coordinateSystem: 'matrix'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "matrix",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'graph', coordinateSystem: 'matrix', coordinateSystemUsage: 'box'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "an internal view",
 *      COORD_SYS_USAGE_KIND_BOX: "the internal view is laid out on a matrix"
 *  - If `series: {type: 'map'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "a internal geo",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'map', coordinateSystem: 'geo', geoIndex: 0}`:
 *      COORD_SYS_USAGE_KIND_DATA: "a geo",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'map', coordinateSystem: 'matrix'}`:
 *      not_applicable
 *  - If `series: {type: 'map', coordinateSystem: 'matrix', coordinateSystemUsage: 'box'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "an internal geo",
 *      COORD_SYS_USAGE_KIND_BOX: "the internal geo is laid out on a matrix"
 *
 * @usage
 * For case (A) & (B),
 *  call `injectCoordSysByOption({coordSysType: 'aaa', ...})` once for each series/components.
 * For case (C),
 *  call `injectCoordSysByOption({coordSysType: 'aaa', ...})` once for each series/components,
 *  and then call `injectCoordSysByOption({coordSysType: 'bbb', ..., isDefaultDataCoordSys: true})`
 *  once for each series/components.
 */
export declare function injectCoordSysByOption(opt: {
    targetModel: ComponentModel;
    coordSysType: string;
    coordSysProvider: CoordSysInjectionProvider;
    isDefaultDataCoordSys?: boolean;
    allowNotFound?: boolean;
}): CoordinateSystemUsageKind;
declare type CoordSysInjectionProvider = (coordSysType: string, injectTargetModel: ComponentModel) => CoordinateSystem | NullUndefined;
export declare const simpleCoordSysInjectionProvider: CoordSysInjectionProvider;
export default CoordinateSystemManager;
