import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import Transformable from 'zrender/lib/core/Transformable.js';
import Element from 'zrender/lib/Element.js';
import { CoordinateSystemMaster, CoordinateSystem } from './CoordinateSystem.js';
import GlobalModel from '../model/Global.js';
import { ParsedModelFinder } from '../util/model.js';
import { AnimationOptionMixin, NullUndefined, RoamHostComponentOrSeries, RoamOptionMixin, RoamPayload } from '../util/types.js';
import ExtensionAPI from '../core/ExtensionAPI.js';
import type ComponentModel from '../model/Component.js';
import type Model from '../model/Model.js';
import { MatrixArray } from 'zrender/lib/core/matrix.js';
/**
 * @tutorial [VIEW_COORD_SYS_ANIMATION]
 *
 *  Some VIEW_COORD_SYS may need to support roaming animation, which may be required when the original
 *  inputs (such as `center/zoom/left/top/right/bottomwidth/height/etc.`) are changed via `setOption`.
 *  Roaming animation requires strict visual alignment between VIEW_COORD_SYS itself (consider "geo map")
 *  and its content (e.g., scatter series).
 *  A logically correct implementation is probably applying animation to VIEW_COORD_SYS's inputs and
 *  calculate VIEW_COORD_SYS's transformation and lay out its dependent series per frame via
 *  `dispatchAction`-ish pattern. But this approach require more mechanism to be introduced and careful
 *  refactoring.
 *  Instead, we currently still follow the conventional implementation - create animation separately on
 *  each element (typically via `graphic.updateProps`) . See VIEW_COORD_SYS_ANIMATION_PROPS_CONSTRAINT.
 *
 *  [VIEW_COORD_SYS_ANIMATION_PROPS_CONSTRAINT]:
 *    The animation should only interpolate `x/y/scaleX/scaleY`, thereby ensuring visual alignment, even
 *    though `MapDraw` applies animations only on a "VIEW_COORD_SYS_TRANS_ROAM" but scatter series applies
 *    animation on a "VIEW_COORD_SYS_TRANS_OVERALL".
 *    But this constraint must always be respected by all relevant components and series.
 *
 *  [VIEW_COORD_SYS_ANIMATION_INTERRUPTION]:
 *    The animation should be able to be interrupted, such as when users roam it by mouse or touch.
 *    When interrupted, `center` and `zoom` must be synchronized back to the VIEW_COORD_SYS and host models
 *    (e.g., geo components or map series). Otherwise, a next `setOption` can cause unexpected result due to
 *    the outdated `center` and `zoom`.
 *    But see FIXME_VIEW_COORD_SYS_SYNC_BACK for some existing bugs.
 *
 *  [VIEW_COORD_SYS_UPDATE_FLOW]:
 *    To avoid bidirectional flow, we consider the original inputs (center/zoom/dataRect/viewRect/etc.) as
 *    the single source of truth, and always calculate transformations based on that.
 *    - Roaming interactions ('pan'/'zoom') can trigger an update to the original inputs via
 *      `dispatchAction({type: 'xxxRoam', ...})`.
 *    - Roaming animation can synchronize back to the original inputs when interrupted.
 *      See `syncBackEl`: It is zrender elements that are assigned with VIEW_COORD_SYS_TRANSFORMATION,
 *      and may be modified outside, typically by animation.
 */
/**
 * @tutorial [VIEW_COORD_SYS_TRANSFORMATION]
 *
 *  @tutorial [VIEW_COORD_SYS_TRANS_RAW]
 *    It is the transformation from `ViewInner['dataRect']` to `ViewInner['viewRect']`.
 *    - ViewInner['dataRect']:
 *      A rect in a source space (or say, data space).
 *      The unit is defined by the source. For example,
 *        - for geo source, the unit defined as lat/lng,
 *        - for SVG source, the unit is the same as the width/height defined in SVG.
 *        - for series.graph/series.tree/series.sankey, the unit defined as px directly.
 *    - ViewInner['viewRect']:
 *      A rect in the canvas pixel space.
 *      For example, it can be ec option left/right/top/bottom/width/height of a component or series.
 *    NOTICE:
 *      - ViewInner['dataRect'] and ViewInner['viewRect'] affect the behavior when centerOption contains
 *        absolute values. See VIEW_COORD_SYS_CENTER_ZOOM_DEFINITION .
 *
 *  @tutorial [VIEW_COORD_SYS_TRANS_ROAM]
 *    It is built with respect to `RoamOptionMixin['center']` and `RoamOptionMixin['zoom']`.
 *    [VIEW_COORD_SYS_CENTER_ZOOM_DEFINITION]:
 *      {pxSpace} <-roamTrans- {viewRectSpace} <-rawTrans- {dataRectSpace} <-- ...
 *                     |                                         |
 *                 zoomOption                                centerOption
 *      `RoamOptionMixin['center']` is a user specified point on the space of `ViewInner['dataRect']`,
 *      which will be located to the center of `ViewInner['viewRect']`.
 *      It can also be a percent value (e.g. '50%'), based on ViewInner['dataRect'].width/height` (since v6).
 *      Under this definition, users can use '0%' to map the top-left of `ViewInner['dataRect']`
 *      to the center of `ViewInner['viewRect']`.
 *      NOTICE:
 *        - `RoamOptionMixin['center']` is in a linear space regardless of `GeoCommonOptionMixin['projection']`
 *        - Absolute values in centerOption may hardly have a rigorous meaningful definition if the layout
 *          is auto-calculated, since users are unlikely to known the exact value of the bounding rect.
 *          And it is affected by the settings of ViewInner['dataRect'] and ViewInner['viewRect'].
 *          Therefore, percent centerOption is preferred.
 *      Use cases:
 *        geo and map series (`MapDraw`) use this transformation for roamming, since the source
 *        has been converted with respect to VIEW_COORD_SYS_TRANS_RAW.
 *
 *  @tutorial [VIEW_COORD_SYS_TRANS_OVERALL]
 *    This is the result of
 *      `matrix_left_multiply(VIEW_COORD_SYS_TRANS_ROAM, VIEW_COORD_SYS_TRANS_RAW)`.
 *    Use case:
 *      sankey/tree/graph series use this transformation for roamming.
 *
 *  @tutorial [VIEW_COORD_SYS_TRANSFORMATION_FORMULA]
 *    [Basic]:
 *      {pxSpace} <-roamTrans- {viewRectSpace} <-rawTrans- {dataRectSpace} <-- ...
 *      pxPoint = roamTrans * rawTrans * dataPoint
 *      overallTrans = roamTrans * rawTrans
 *    [e.g., geo case]:
 *             pxPoint = roamTrans * (rawTrans * (projection * dataPoint))
 *      Hence: pxPoint = group_syncBackType_ROAM * (rawTrans * (projection * dataPoint))
 *      Hence: pxPoint = group_syncBackType_ROAM * rawTrans_projection_precalculated_point
 *    [e.g., graph series case]:
 *             pxPoint = (roamTrans * rawTrans) * upper_els
 *      Hence: pxPoint = group_syncBackType_OVERALL * upper_els
 *      (NOTE: upper_els can have their own transformations)
 *
 * @see viewCoordSysCopyTrans for fetching transformations.
 */
export declare const VIEW_COORD_SYS_TRANS_RAW = 0;
export declare const VIEW_COORD_SYS_TRANS_ROAM = 1;
export declare const VIEW_COORD_SYS_TRANS_OVERALL = 2;
/**
 * Private props of VIEW_COORD_SYS.
 */
interface ViewInner extends View {
    /**
     * @see useLegacyViewCoordSysCenterBase
     */
    lgCt?: {
        w: number;
        h: number;
    } | NullUndefined;
    lgGeo?: Transformable;
    invertY: boolean;
    /**
     * @see VIEW_COORD_SYS_CENTER_ZOOM_DEFINITION
     */
    centerOption: RoamOptionMixin['center'] | NullUndefined;
    zoom: RoamOptionMixin['zoom'];
    zoomLimit: RoamOptionMixin['scaleLimit'] | NullUndefined;
    /**
     * The index is `VIEW_COORD_SYS_TRANS_RAW`/`VIEW_COORD_SYS_TRANS_ROAM`/`VIEW_COORD_SYS_TRANS_OVERALL`.
     *
     * TRANSFORMABLE_PROPS on the returned transformable is ready to use.
     */
    trans: Transformable[];
    /**
     * This is `transformableGetLocalTransform(viewInner.trans[VIEW_COORD_SYS_TRANS_RAW])`.
     * It should follow each update of `viewInner.trans[VIEW_COORD_SYS_TRANS_RAW]`.
     */
    mtRaw: MatrixArray;
    /**
     * This is the inverse matrix of `mtRaw`.
     */
    mtRawInv: MatrixArray;
    /**
     * This is `transformableGetLocalTransform(viewInner.trans[VIEW_COORD_SYS_TRANS_OVERALL])`
     * It should follow each update of `viewInner.trans[VIEW_COORD_SYS_TRANS_OVERALL]`.
     */
    mtOverall: MatrixArray;
    /**
     * This is the inverse matrix of `mtOverall`.
     */
    mtOverallInv: MatrixArray;
    /**
     * @see VIEW_COORD_SYS_TRANS_RAW
     */
    dataRect: BoundingRect | NullUndefined;
    /**
     * @see VIEW_COORD_SYS_TRANS_RAW
     */
    viewRect: BoundingRect | NullUndefined;
    /**
     * @see VIEW_COORD_SYS_ANIMATION
     */
    syncBackEl: Element | NullUndefined;
    syncBackType: typeof VIEW_COORD_SYS_TRANS_ROAM | typeof VIEW_COORD_SYS_TRANS_OVERALL;
}
export declare const VIEW_COORD_SYS_TYPE = "view";
/**
 * [VIEW_COORD_SYS]
 *
 * @final [NOTICE] Inheritance of this class is not recommended. Use composition instead.
 */
declare class View extends Transformable implements CoordinateSystemMaster, CoordinateSystem {
    readonly type: string;
    static dimensions: string[];
    readonly dimensions: string[];
    constructor(invertY?: boolean, legacyCenterBase?: ViewInner['lgCt'], legacyGeo?: Transformable);
    /**
     * @implements CoordinateSystem['getBoundingRect']
     * @see VIEW_COORD_SYS_TRANS_RAW
     *
     * This is a rect in data space.
     * For historicall reason, the name is `getBoundingRect` - preserve it for backward compatibility.
     */
    getBoundingRect(): BoundingRect;
    /**
     * @implements CoordinateSystem['getViewRect']
     * @see VIEW_COORD_SYS_TRANS_RAW
     */
    getViewRect(): BoundingRect;
    /**
     * @implements CoordinateSystem['getRoamTransform']
     */
    getRoamTransform(): MatrixArray;
    dataToPoint(data: number[], noRoam?: boolean, out?: number[]): number[];
    pointToData(point: number[], reserved?: unknown, out?: number[]): number[];
    convertToPixel(ecModel: GlobalModel, finder: ParsedModelFinder, value: number[]): number[];
    convertFromPixel(ecModel: GlobalModel, finder: ParsedModelFinder, pixel: number[]): number[];
    containPoint(point: number[]): boolean;
}
export declare function viewCoordSysCopyOverallMatrix(out: MatrixArray | NullUndefined, viewCoordSys: View): MatrixArray;
export declare function viewCoordSysGetZoomOption(viewCoordSys: View): RoamOptionMixin['zoom'];
export declare function viewCoordSysCopyBoundingRect(out: BoundingRect | NullUndefined, viewCoordSys: View): BoundingRect;
export declare function viewCoordSysCopyViewRect(out: BoundingRect | NullUndefined, viewCoordSys: View): BoundingRect;
/**
 * Copy from `ViewInner['trans']`.
 */
export declare function viewCoordSysCopyTrans(out: NullUndefined, viewCoordSys: View, transKind: typeof VIEW_COORD_SYS_TRANS_RAW | typeof VIEW_COORD_SYS_TRANS_ROAM | typeof VIEW_COORD_SYS_TRANS_OVERALL): Transformable;
export declare function viewCoordSysCopyTrans<TOut extends Transformable>(out: TOut, viewCoordSys: View, transKind: typeof VIEW_COORD_SYS_TRANS_RAW | typeof VIEW_COORD_SYS_TRANS_ROAM | typeof VIEW_COORD_SYS_TRANS_OVERALL): TOut;
/**
 * [NOTICE]
 *  The definition of this center has always been irrelevant to some other series center like
 *  'series-pie.center' - this center is a point in the space of `ViewInner['dataRect'].x/y`,
 *  rather than canvas viewport, and the unit is not necessarily pixel (e.g., in geo case).
 */
export declare function viewCoordSysSetRoamOptionFromModel(viewCoordSys: View, hostModel: RoamHostComponentOrSeries): void;
/**
 * @see ViewInner['dataRect']
 */
export declare function viewCoordSysSetBoundingRect(viewCoordSys: View, x: number, y: number, width: number, height: number): void;
/**
 * @see ViewInner['viewRect']
 */
export declare function viewCoordSysSetViewRect(viewCoordSys: View, x: number, y: number, width: number, height: number): void;
export declare function isViewCoordSys(coordSys: CoordinateSystem | NullUndefined): coordSys is View;
/**
 * NOTICE:
 *  - `syncBackEl` should be in the pixel space without any other transformation
 *    in its accesters, otherwise the roaming may incorrect.
 *  - `syncBackEl` can be a `Group`, having its own descendants and transformation.
 *    But in this case, `dataToPoint` can only reach the space of `syncBackEl` itself.
 */
export declare function applyViewCoordSysTransToElement(syncBackEl: Element | NullUndefined, syncBackType: typeof VIEW_COORD_SYS_TRANS_ROAM | typeof VIEW_COORD_SYS_TRANS_OVERALL, viewCoordSys: View, animatableModel: Model<AnimationOptionMixin> | NullUndefined): void;
/**
 * Invert to `center` and `zoom` of VIEW_COORD_SYS and host models based on
 *  - `syncBackEl` or VIEW_COORD_SYS_TRANS_OVERALL
 *  - Delta in `payload`.
 *
 * Should be only called in action handlers.
 *
 * @see RoamHostView['__updateOnOwnRoam']
 */
export declare function ownRoamModelCoordSysUpdateInAction(payload: RoamPayload, hostModel: RoamHostComponentOrSeries, otherModelsToSync?: RoamHostComponentOrSeries[] | NullUndefined): void;
export declare function getOwnRoamViewCoordSys(hostModel: RoamHostComponentOrSeries): View | NullUndefined;
export declare function ownRoamViewUpdateDirectlyInAction(payload: RoamPayload, componentOrSeries: ComponentModel, ecModel: GlobalModel, api: ExtensionAPI): void;
export declare function useLegacyViewCoordSysCenterBase(ecModel: GlobalModel, api: ExtensionAPI): ViewInner['lgCt'];
export declare function clampByZoomLimit(zoom: number, zoomLimit: RoamOptionMixin['scaleLimit'] | NullUndefined): number;
export declare function calcCompensationScaleToPreserveNodeSize(viewCoordSys: View, model: Model<Pick<RoamOptionMixin, 'nodeScaleRatio'>>): number;
export default View;
