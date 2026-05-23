import type { NullUndefined } from '../../util/types.js';
import type { MatrixXYLocator, MatrixDimPair, MatrixXYLocatorRange } from './MatrixDim.js';
import Point from 'zrender/lib/core/Point.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import type { MatrixBodyCornerCellOption, MatrixBodyOption, MatrixCornerOption } from './MatrixModel.js';
import type Model from '../../model/Model.js';
export declare type MatrixBodyOrCornerKind = 'body' | 'corner';
declare type MatrixBodyOrCornerOption<TKind extends MatrixBodyOrCornerKind> = ('body' extends TKind ? MatrixBodyOption : MatrixCornerOption);
export interface MatrixBodyCornerCell {
    id: Point;
    option: MatrixBodyCornerCellOption | NullUndefined;
    inSpanOf: MatrixBodyCornerCell | NullUndefined;
    cellMergeOwner: boolean;
    span: Point | NullUndefined;
    locatorRange: MatrixXYLocatorRange | NullUndefined;
    spanRect: RectLike | NullUndefined;
}
/**
 * Lifetime: the same with `MatrixModel`, but different from `coord/Matrix`.
 */
export declare class MatrixBodyCorner<TKind extends MatrixBodyOrCornerKind> {
    /**
     * Be sparse, item exists only if needed.
     */
    private _cellMap;
    private _cellMergeOwnerList;
    private _model;
    private _dims;
    private _kind;
    constructor(kind: TKind, bodyOrCornerModel: Model<MatrixBodyOrCornerOption<TKind>>, dims: MatrixDimPair);
    /**
     * Can not be called before series models initialization finished, since the ordinalMeta may
     * use collect the values from `series.data` in series initialization.
     */
    private _ensureCellMap;
    /**
     * Body cells or corner cell are not commonly defined specifically, especially in a large
     * table, thus his is a sparse data structure - bodys or corner cells exist only if there
     * are options specified to it (in `matrix.body.data` or `matrix.corner.data`);
     * otherwise, return `NullUndefined`.
     */
    getCell(xy: MatrixXYLocator[]): MatrixBodyCornerCell | NullUndefined;
    /**
     * Only cell existing (has specific definition or props) will be travelled.
     */
    travelExistingCells(cb: (cell: MatrixBodyCornerCell) => void): void;
    /**
     * @param locatorRange Must be the return of `parseCoordRangeOption`.
     */
    expandRangeByCellMerge(locatorRange: MatrixXYLocatorRange): void;
}
export {};
