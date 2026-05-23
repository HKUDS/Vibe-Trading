import type { CoordinateSystemDataLayout, NullUndefined } from '../../util/types.js';
import { CoordinateSystem, CoordinateSystemMaster } from '../CoordinateSystem.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import MatrixModel, { MatrixCoordRangeOption } from './MatrixModel.js';
import { LayoutRect } from '../../util/layout.js';
import { ParsedModelFinder } from '../../util/model.js';
import type { MatrixXYLocator } from './MatrixDim.js';
import { MatrixClampOption } from './matrixCoordHelper.js';
declare class Matrix implements CoordinateSystem, CoordinateSystemMaster {
    static readonly dimensions: string[];
    /**
     * @see fetchers in `model/referHelper.ts`,
     * which is used to parse data in ordinal way.
     * In most series only 'x' and 'y' is required,
     * but some series, such as heatmap, can specify value.
     */
    static getDimensionsInfo(): ({
        name: string;
        type: "ordinal";
    } | {
        name: string;
        type?: undefined;
    })[];
    readonly dimensions: string[];
    readonly type = "matrix";
    private _model;
    private _dimModels;
    private _dims;
    private _rect;
    static create(ecModel: GlobalModel, api: ExtensionAPI): Matrix[];
    constructor(matrixModel: MatrixModel, ecModel: GlobalModel, api: ExtensionAPI);
    getRect(): LayoutRect;
    private _resize;
    /**
     * @implement
     * - The input is allowed to be `[NaN/null/undefined, xxx]`/`[xxx, NaN/null/undefined]`;
     *  the return is `[NaN, xxxresult]`/`[xxxresult, NaN]` or clamped boundary value if
     *  `clamp` passed. This is for the usage that only get coord on single x or y.
     * - Alwasy return an numeric array, but never be null/undefined.
     *  If it can not be located or invalid, return `[NaN, NaN]`.
     */
    dataToPoint(data: MatrixCoordRangeOption[], opt?: Parameters<Matrix['dataToLayout']>[1], out?: number[]): number[];
    /**
     * @implement
     * - The input is allowed to be `[NaN/null/undefined, xxx]`/`[xxx, NaN/null/undefined]`;
     *  the return is `{x: NaN, width: NaN, y: xxxresulty, height: xxxresulth}`/
     *  `{y: NaN, height: NaN, x: xxxresultx, width: xxxresultw}` or clamped boundary value
     *  if `clamp` passed. This is for the usage that only get coord on single x or y.
     * - The returned `out.rect` and `out.matrixXYLocatorRange` is always an object or an 2d-array,
     *  but never be null/undefined. If it cannot be located or invalid, `NaN` is in their
     *  corresponding number props.
     * - Do not provide `out.contentRect`, because it's allowed to input non-leaf dimension x/y or
     *  a range of x/y, which determines a rect covering multiple cells (even not merged), in which
     *  case the padding and borderWidth can not be determined to make a contentRect. Therefore only
     *  return `out.rect` in any case for consistency. The caller is responsible for adding space to
     *  avoid covering cell borders, if necessary.
     */
    dataToLayout(data: MatrixCoordRangeOption[], opt?: {
        clamp?: MatrixClampOption | NullUndefined;
        ignoreMergeCells?: boolean;
    }, out?: CoordinateSystemDataLayout): CoordinateSystemDataLayout;
    /**
     * The returned locator pair can be the input of `dataToPoint` or `dataToLayout`.
     *
     * If point[0] is out of the matrix rect,
     *  the out[0] is NaN;
     * else if it is on the right of top-left corner of body,
     *  the out[0] is the oridinal number (>= 0).
     * else
     *  out[0] is the locator for corner or header (<= 0).
     *
     * The same rule goes for point[1] and out[1].
     *
     * But point[0] and point[1] are calculated separately, i.e.,
     * the reuslt can be `[1, NaN]` or `[NaN, 1]` if only one dimension is out of boundary.
     *
     * @implement
     */
    pointToData(point: number[], opt?: {
        clamp?: MatrixClampOption | NullUndefined;
    }, out?: MatrixXYLocator[]): MatrixXYLocator[];
    convertToPixel(ecModel: GlobalModel, finder: ParsedModelFinder, value: Parameters<Matrix['dataToPoint']>[0], opt?: Parameters<Matrix['dataToPoint']>[1]): ReturnType<Matrix['dataToPoint']> | NullUndefined;
    convertToLayout(ecModel: GlobalModel, finder: ParsedModelFinder, value: Parameters<Matrix['dataToLayout']>[0], opt?: Parameters<Matrix['dataToLayout']>[1]): ReturnType<Matrix['dataToLayout']> | NullUndefined;
    convertFromPixel(ecModel: GlobalModel, finder: ParsedModelFinder, pixel: Parameters<Matrix['pointToData']>[0], opt?: Parameters<Matrix['pointToData']>[1]): ReturnType<Matrix['pointToData']> | NullUndefined;
    containPoint(point: number[]): boolean;
}
export default Matrix;
