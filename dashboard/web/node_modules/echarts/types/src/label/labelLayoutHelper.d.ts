import ZRText from 'zrender/lib/graphic/Text.js';
import { LabelLayoutOption, NullUndefined } from '../util/types.js';
import { BoundingRect, OrientedBoundingRect, Polyline } from '../util/graphic.js';
import { PointLike } from 'zrender/lib/core/Point.js';
import { BoundingRectIntersectOpt } from 'zrender/lib/core/BoundingRect.js';
import { MatrixArray } from 'zrender/lib/core/matrix.js';
/**
 * This is the input for label layout and overlap resolving.
 */
interface LabelLayoutBase {
    label: ZRText;
    labelLine?: Polyline | NullUndefined;
    layoutOption?: LabelLayoutOption | NullUndefined;
    priority: number;
    defaultAttr: {
        ignore?: boolean;
        labelGuideIgnore?: boolean;
    };
    marginForce?: (number | NullUndefined)[] | NullUndefined;
    minMarginForce?: (number | NullUndefined)[] | NullUndefined;
    marginDefault?: number[] | NullUndefined;
    suggestIgnore?: boolean;
}
/**
 * [CAUTION]
 *  - These props will be created and cached.
 *  - The created props may be modified directly (rather than recreate) for performance consideration,
 *      therefore, do not use the internal data structure of the el.
 */
export interface LabelGeometry {
    label: Pick<ZRText, 'ignore'>;
    dirty: (typeof LABEL_LAYOUT_DIRTY_ALL) | NullUndefined;
    rect: BoundingRect;
    axisAligned: boolean;
    obb: OrientedBoundingRect | NullUndefined;
    localRect: BoundingRect;
    transform: number[] | NullUndefined;
}
export declare type LabelLayoutData = LabelLayoutBase & Partial<LabelGeometry>;
export declare type LabelLayoutWithGeometry = LabelLayoutBase & LabelGeometry;
declare const LABEL_LAYOUT_DIRTY_ALL: number;
export declare function setLabelLayoutDirty(labelGeometry: Partial<LabelGeometry>, dirtyOrClear: boolean, dirtyBits?: number): void;
/**
 * [CAUTION]
 *  - No auto dirty propagation mechanism yet. If the transform of the raw label or any of its ancestors is
 *    changed, must sync the changes to the props of `LabelGeometry` by:
 *    either explicitly call:
 *      `setLabelLayoutDirty(labelLayout, true); ensureLabelLayoutWithGeometry(labelLayout);`
 *    or call (if only translation is performed):
 *      `labelLayoutApplyTranslation(labelLayout);`
 *  - `label.ignore` is not necessarily falsy, and not considered in computing `LabelGeometry`,
 *    since it might be modified by some overlap resolving handling.
 *  - To duplicate or make a variation:
 *    use `newLabelLayoutWithGeometry`.
 *
 * The result can also be the input of this method.
 * @return `NullUndefined` if and only if `labelLayout` is `NullUndefined`.
 */
export declare function ensureLabelLayoutWithGeometry(labelLayout: LabelLayoutData | NullUndefined): LabelLayoutWithGeometry | NullUndefined;
/**
 * The props in `out` will be filled if existing, or created.
 */
export declare function computeLabelGeometry<TOut extends LabelGeometry>(out: Partial<TOut>, label: ZRText, opt?: Pick<LabelLayoutData, 'marginForce' | 'minMarginForce' | 'marginDefault'>): TOut;
/**
 * The props in `out` will be filled if existing, or created.
 */
export declare function computeLabelGeometry2<TOut extends LabelGeometry>(out: Partial<TOut>, rawLocalRect: BoundingRect, rawTransform: MatrixArray | NullUndefined): TOut;
/**
 * This is a shortcut of
 *   ```js
 *   labelLayout.label.x = newX;
 *   labelLayout.label.y = newY;
 *   setLabelLayoutDirty(labelLayout, true);
 *   ensureLabelLayoutWithGeometry(labelLayout);
 *   ```
 * and provide better performance in this common case.
 */
export declare function labelLayoutApplyTranslation(labelLayout: LabelLayoutData, offset: PointLike): void;
/**
 * To duplicate or make a variation of a label layout.
 * Copy the only relevant properties to avoid the conflict or wrongly reuse of the props of `LabelLayoutWithGeometry`.
 */
export declare function newLabelLayoutWithGeometry(newBaseWithDefaults: Partial<LabelLayoutData>, source: LabelLayoutBase): LabelLayoutWithGeometry;
/**
 * Adjust labels on x/y direction to avoid overlap.
 *
 * PENDING: the current implementation is based on the global bounding rect rather than the local rect,
 *  which may be not preferable in some edge cases when the label has rotation, but works for most cases,
 *  since rotation is unnecessary when there is sufficient space, while squeezing is applied regardless
 *  of overlapping when there is no enough space.
 *
 * NOTICE:
 *  - The input `list` and its content will be modified (sort, label.x/y, rect).
 *  - The caller should sync the modifications to the other parts by
 *    `setLabelLayoutDirty` and `ensureLabelLayoutWithGeometry` if needed.
 *
 * @return adjusted
 */
export declare function shiftLayoutOnXY(list: Pick<LabelLayoutWithGeometry, 'rect' | 'label'>[], xyDimIdx: 0 | 1, // 0 for x, 1 for y
minBound: number, // for x, leftBound; for y, topBound
maxBound: number, // for x, rightBound; for y, bottomBound
balanceShift?: boolean): boolean;
/**
 * @see `SavedLabelAttr` in `LabelManager.ts`
 * @see `hideOverlap`
 */
export declare function restoreIgnore(labelList: LabelLayoutData[]): void;
/**
 * [NOTICE - restore]:
 *  'series:layoutlabels' may be triggered during some EC_PARTIAL_UPDATE passes, such as zooming in series.graph/geo
 *  (`updateLabelLayout`), where the modified `Element` props should be restorable from `defaultAttr`.
 *  @see `SavedLabelAttr` in `LabelManager.ts`
 *  `restoreIgnore` can be called to perform the restore, if needed.
 *
 * [NOTICE - state]:
 *  Regarding Element's states, this method is only designed for the normal state.
 *  PENDING: although currently this method is effectively called in other states in `updateLabelLayout` case,
 *      the bad case is not noticeable in the zooming scenario.
 */
export declare function hideOverlap(labelList: LabelLayoutData[]): void;
/**
 * Enable fast check for performance; use obb if inevitable.
 * If `mtv` is used, `targetLayoutInfo` can be moved based on the values filled into `mtv`.
 *
 * This method is based only on the current `Element` states (regardless of other states).
 * Typically this method (and the entire layout process) is performed in normal state.
 */
export declare function labelIntersect(baseLayoutInfo: LabelGeometry | NullUndefined, targetLayoutInfo: LabelGeometry | NullUndefined, mtv?: PointLike, intersectOpt?: BoundingRectIntersectOpt): boolean;
export {};
