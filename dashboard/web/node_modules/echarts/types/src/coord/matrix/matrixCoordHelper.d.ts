import Point from 'zrender/lib/core/Point.js';
import type { MatrixCellLayoutInfo, MatrixDimPair, MatrixXYLocator, MatrixXYLocatorRange } from './MatrixDim.js';
import type { NullUndefined } from '../../util/types.js';
import type { MatrixCoordRangeOption, MatrixCoordValueOption } from './MatrixModel.js';
import type { RectLike } from 'zrender/lib/core/BoundingRect.js';
export declare const MatrixCellLayoutInfoType: {
    readonly level: 1;
    readonly leaf: 2;
    readonly nonLeaf: 3;
};
export declare type MatrixCellLayoutInfoType = (typeof MatrixCellLayoutInfoType)[keyof typeof MatrixCellLayoutInfoType];
/**
 * @public Public to users in `chart.convertFromPixel`.
 */
export declare const MatrixClampOption: {
    none: number;
    all: number;
    body: number;
    corner: number;
};
export declare type MatrixClampOption = (typeof MatrixClampOption)[keyof typeof MatrixClampOption];
/**
 * For the x direction,
 *  - find dimension cell from `xMatrixDim`,
 *      - If `xDimCell` or `yDimCell` is not a leaf, return the non-leaf cell itself.
 *  - otherwise find level from `yMatrixDim`.
 *  - otherwise return `NullUndefined`.
 *
 * For the y direction, it's the opposite.
 */
export declare function coordDataToAllCellLevelLayout(coordValue: MatrixCoordValueOption, dims: MatrixDimPair, thisDimIdx: number): MatrixCellLayoutInfo | NullUndefined;
export declare function resetXYLocatorRange(out: unknown[] | NullUndefined): MatrixXYLocatorRange;
/**
 * If illegal or out of boundary, set NaN to `locOut`. See `isXYLocatorRangeInvalidOnDim`.
 * x dimension and y dimension are calculated separately.
 */
export declare function parseCoordRangeOption(locOut: MatrixXYLocatorRange, reasonOut: string[] | NullUndefined, data: MatrixCoordRangeOption[], dims: MatrixDimPair, clamp: MatrixClampOption): void;
/**
 * @param locatorRange Must be the return of `parseCoordRangeOption`,
 *  where if not NaN, it must be a valid locator.
 */
export declare function isXYLocatorRangeInvalidOnDim(locatorRange: MatrixXYLocatorRange, dimIdx: number): boolean;
export declare function resolveXYLocatorRangeByCellMerge(inOutLocatorRange: MatrixXYLocatorRange, outMergedMarkList: boolean[] | NullUndefined, mergeDefList: {
    locatorRange: MatrixXYLocatorRange | NullUndefined;
    cellMergeOwner: boolean;
}[], mergeDefListTravelLen: number): void;
export declare function fillIdSpanFromLocatorRange(owner: {
    id: Point;
    span: Point;
}, locatorRange: MatrixXYLocatorRange): void;
export declare function cloneXYLocatorRange(target: MatrixXYLocatorRange, source: MatrixXYLocatorRange): void;
/**
 * If illegal, the corresponding x/y/width/height is set to `NaN`.
 * `x/width` or `y/height` is supported to be calculated separately,
 * i.e., one side are NaN, the other side are normal.
 * @param oneDimOut only write to `x/width` or `y/height`, depending on `dimIdx`.
 */
export declare function xyLocatorRangeToRectOneDim(oneDimOut: RectLike, locRange: MatrixXYLocatorRange, dims: MatrixDimPair, dimIdx: number): void;
/**
 * @usage To get/set on dimension, use:
 *  `xyVal[XY[dim]] = val;` // set on this dimension.
 *  `xyVal[XY[1 - dim]] = val;` // set on the perpendicular dimension.
 */
export declare function setDimXYValue(out: Point, dimIdx: number, // 0 | 1
valueOnThisDim: MatrixXYLocator, valueOnOtherDim: MatrixXYLocator): Point;
export declare function createNaNRectLike(): RectLike;
