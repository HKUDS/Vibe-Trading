import Point from 'zrender/lib/core/Point.js';
import OrdinalMeta from '../../data/OrdinalMeta.js';
import { NullUndefined, OrdinalNumber } from '../../util/types.js';
import { MatrixDimensionModel, MatrixDimensionCellOption, MatrixDimensionLevelOption, MatrixCoordValueOption } from './MatrixModel.js';
import { ListIterator } from '../../util/model.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import { MatrixCellLayoutInfoType } from './matrixCoordHelper.js';
export interface MatrixCellLayoutInfo {
    type: MatrixCellLayoutInfoType;
    id: Point;
    xy: number;
    wh: number;
    dim: MatrixDim;
}
export declare type MatrixXYLocator = MatrixCellLayoutInfo['id']['x'] | MatrixCellLayoutInfo['id']['y'];
/**
 * [[xmin, xmax], [ymin, ymax]]
 * For each internal value, be NaN if invalid or out of boundary (never be null/undefined),
 * otherwise must be valid locators.
 * @see parseCoordRangeOption
 * @see resetXYLocatorRange
 */
export declare type MatrixXYLocatorRange = MatrixXYLocator[][] & {
    __brand: 'MatrixXYLocatorRange';
};
/**
 * [[xmin, xmax], [ymin, ymax]], be `NullUndefined` if illegal.
 */
export declare type MatrixXYCellLayoutInfoRange = (MatrixCellLayoutInfo | NullUndefined)[][];
export interface MatrixDimensionCell extends MatrixCellLayoutInfo {
    span: Point;
    level: number;
    firstLeafLocator: MatrixXYLocator;
    ordinal: OrdinalNumber;
    option: MatrixDimensionCellOption;
    rect: RectLike;
}
/**
 * Computed properties of a certain tree level.
 * In most cases this is used to describe level size or locate corner cells.
 */
export interface MatrixDimensionLevelInfo extends MatrixCellLayoutInfo {
    option: MatrixDimensionLevelOption | NullUndefined;
}
export declare type MatrixDimPair = {
    x: MatrixDim;
    y: MatrixDim;
};
/**
 * Lifetime: the same with `MatrixModel`, but different from `coord/Matrix`.
 */
export declare class MatrixDim {
    readonly dim: 'x' | 'y';
    readonly dimIdx: number;
    private _cells;
    private _levels;
    private _leavesCount;
    private _model;
    private _ordinalMeta;
    private _scale;
    private _uniqueValueGen;
    constructor(dim: 'x' | 'y', dimModel: MatrixDimensionModel);
    private _initByDimModelData;
    private _initBySeriesData;
    private _setCellId;
    private _initCellsId;
    private _initLevelIdOptions;
    shouldShow(): boolean;
    /**
     * Iterate leaves (they are layout units) if dimIdx === this.dimIdx.
     * Iterate levels if dimIdx !== this.dimIdx.
     */
    resetLayoutIterator(it: ListIterator<MatrixCellLayoutInfo> | NullUndefined, dimIdx: number, startLocator?: MatrixXYLocator | NullUndefined, count?: number | NullUndefined): ListIterator<MatrixCellLayoutInfo>;
    resetCellIterator(it?: ListIterator<MatrixDimensionCell>): ListIterator<MatrixDimensionCell>;
    resetLevelIterator(it?: ListIterator<MatrixDimensionLevelInfo>): ListIterator<MatrixDimensionLevelInfo>;
    getLayout(outRect: RectLike, dimIdx: number, locator: MatrixXYLocator): void;
    /**
     * Get leaf cell or get level info.
     * Should be able to return null/undefined if not found on x or y, thus input `dimIdx` is needed.
     */
    getUnitLayoutInfo(dimIdx: number, locator: MatrixXYLocator): MatrixCellLayoutInfo | NullUndefined;
    /**
     * Get dimension cell by data, including leaves and non-leaves.
     */
    getCell(value: MatrixCoordValueOption): MatrixDimensionCell | NullUndefined;
    /**
     * Get leaf count or get level count.
     */
    getLocatorCount(dimIdx: number): number;
    getOrdinalMeta(): OrdinalMeta;
}
