import OrdinalMeta from '../../data/OrdinalMeta.js';
import ComponentModel from '../../model/Component.js';
import Model from '../../model/Model.js';
import { BoxLayoutOptionMixin, CommonTooltipOption, ComponentOption, ItemStyleOption, LabelOption, LineStyleOption, NullUndefined, OrdinalNumber, OrdinalRawValue, PositionSizeOption } from '../../util/types.js';
import Matrix from './Matrix.js';
import { MatrixDim, MatrixXYLocator } from './MatrixDim.js';
import { MatrixBodyCorner } from './MatrixBodyCorner.js';
import { CoordinateSystemHostModel } from '../CoordinateSystem.js';
export interface MatrixOption extends ComponentOption, BoxLayoutOptionMixin {
    mainType?: 'matrix';
    x?: MatrixDimensionOption;
    y?: MatrixDimensionOption;
    body?: MatrixBodyOption;
    corner?: MatrixCornerOption;
    backgroundStyle?: ItemStyleOption;
    borderZ2?: number;
    tooltip?: CommonTooltipOption<MatrixTooltipFormatterParams>;
    triggerEvent?: boolean;
}
interface MatrixBodyCornerBaseOption extends MatrixCellStyleOption {
    /**
     * Only specify some special cell definitions.
     * It can represent both body cells and top-left corner cells.
     *
     * [body/corner cell locating]:
     *  The rule is uniformly applied, such as, in `matrix.dataToPoint`
     *  and `matrix.dataToLayout` and `xxxComponent.coord`.
     *  Suppose the matrix.x/y dimensions (header) are defined as:
     *  matrix: {
     *      x: [{ value: 'Xa0', children: ['Xb0', 'Xb1'] }, 'Xa1'],
     *      y: [{ value: 'Ya0', children: ['Yb0', 'Yb1'] }],
     *  }
     *  -----------------------------------------
     *  |       |       |     Xa0       |       |
     *  |-------+-------+---------------|  Xa1  |
     *  |cornerQ|cornerP|  Xb0  |  Xb1  |       |
     *  |-------+-------+-------+-------+--------
     *  |       |  Yb0  | bodyR | bodyS |       |
     *  |  Ya0  |-------+-------+---------------|
     *  |       |  Yb1  |       |     bodyT     |
     *  |---------------|------------------------
     *  "Locator number" (`MatrixXYLocator`):
     *    The term `locator` refers to a integer number to locate cells on x or y direction.
     *    Use the top-left cell of the body as the origin point (0, 0),
     *      the non-negative locator indicates the right/bottom of the origin point;
     *      the negative locator indicates the left/top of the origin point.
     *  "Ordinal number" (`OrdinalNumber`):
     *    This term follows the same meaning as that in category axis of cartesian. They are
     *    non-negative integer, designating each string `matrix.x.data[i].value`/`matrix.y.data[i].value`.
     *    'Xb0', 'Xb2', 'Xa1', 'Xa0' are assigned with the ordinal numbers 0, 1, 2, 3.
     *    For every leaf dimension cell, `OrdinalNumber` and `MatrixXYLocator` is the same.
     *
     *  A cell or pixel point or rect can be determined/located by a pair of `MatrixCoordValueOption`.
     *  See also `MatrixBodyCornerCellOption['coord']`.
     *
     *  - The body cell `bodyS` above can be located by:
     *      - `coord: [1, 0]` (`MatrixXYLocator` or `OrdinalNumber`, which is a non-negative integer)
     *      - `coord: ['Xb1', 'Yb0']`
     *      - `coord: ['Xb1', 0]` (mix them)
     *  - The corner cell `cornerQ` above can be located by:
     *      - `coord: [-2, -1]` (negative `MatrixXYLocator`)
     *      - But it is NOT supported to use `coord: ['Y1_0', 'X1_0']` (XY transposed form) here.
     *        It's mathematically sound, but may introduce confusion and unnecessary
     *        complexity (consider the 'Xa1' case), and corner locating is not frequently used.
     *  - `mergeCells`: Body cells or corner cells can be merged, such as "bodyT" above, an input
     *      - The merging can be defined by:
     *        `matrix.data[i]: {coord: [['Xb1', 'Xa1'], 'Yb0'], mergeCells: true}`.
     *      - Input `['Xa1', 'Yb1']` to `dataToPoint` will get a point in the center of "bodyT".
     *      - Input `['Xa1', 'Yb1']` to `dataToLayout` will get a rect of the "bodyT".
     *  - If inputing a non-leaf dimension cell to locate, such as `['Xa0', 'Yb0']`,
     *      - it returns only according to the center of the dimension cells, regardless of the body span.
     *        (therefore, the result can be on the boundary of two body cells.)
     *        And the oridinal number assigned to 'Xa0' is 3, thus input `[3, 'Yb0']` get the some result.
     *  - The dimension (header) cell can be located by negative `MatrixXYLocator`. For example:
     *      - The center of the node 'Ya0' can be located by `[-2, 'Ya0']`.
     */
    data?: MatrixBodyCornerCellOption[];
}
export interface MatrixBodyOption extends MatrixBodyCornerBaseOption {
}
export interface MatrixCornerOption extends MatrixBodyCornerBaseOption {
}
/**
 * Commonly used as `MatrixCoordRangeOption[]`
 * Can locate a cell or a rect range of cells.
 * `[2, 8]` indicates a cell.
 * `[2, null/undefined/NaN]` means y is not relevant.
 * `[null/undefined/NaN, 8]` means x is not relevant.
 * `[[2, 5], 8]` indicates a rect of cells in x range of `2~5` and y `8`.
 * `[[2, 5], null/undefined/NaN]` indicates a x range of `2~5` and y is not relevant.
 * `[[2, 5], [7, 8]]` indicates a rect of cells in x range of `2~5` and y range of `7~8`.
 * `['aNonLeaf', 8]` indicates a rect of cells in x range of `aNonLeaf` and y `8`.
 * @see {parseCoordRangeOption}
 * @see {MatrixBodyCornerBaseOption['data']}
 */
export declare type MatrixCoordRangeOption = (MatrixCoordValueOption | MatrixCoordValueOption[] | NullUndefined);
/**
 * `OrdinalRawValue` is originally provided by `matrix.x/y.data[i].value` or `series.data`.
 */
export declare type MatrixCoordValueOption = OrdinalRawValue | OrdinalNumber | MatrixXYLocator;
export interface MatrixBaseCellOption extends MatrixCellStyleOption {
}
export interface MatrixBodyCornerCellOption extends MatrixBaseCellOption {
    value?: string;
    coord?: MatrixCoordRangeOption[];
    coordClamp?: boolean;
    mergeCells?: boolean;
}
interface MatrixDimensionOption extends MatrixCellStyleOption, MatrixDimensionLevelOption {
    type?: 'category';
    show?: boolean;
    data?: MatrixDimensionCellLooseOption[];
    length?: number;
    levels?: (MatrixDimensionLevelOption | NullUndefined)[];
    dividerLineStyle?: LineStyleOption;
}
export interface MatrixDimensionCellOption extends MatrixBaseCellOption {
    value?: string | NullUndefined;
    size?: PositionSizeOption;
    children?: MatrixDimensionCellOption[];
}
export declare type MatrixDimensionCellLooseOption = MatrixDimensionCellOption | MatrixDimensionCellOption['value'];
export interface MatrixDimensionLevelOption {
    levelSize?: PositionSizeOption;
}
export interface MatrixDimensionModel extends Model<MatrixDimensionOption> {
}
export interface MatrixLabelOption extends LabelOption {
    formatter?: string | ((params: MatrixLabelFormatterParams) => string);
}
export interface MatrixLabelFormatterParams {
    componentType: 'matrix';
    componentIndex: number;
    name: string;
    value: unknown;
    coord: MatrixXYLocator[];
    $vars: readonly ['name', 'value', 'coord'];
}
/**
 * Two levels of cascade inheritance:
 *  - priority-high: style options defined in `matrix.x/y/coner/body.data[i]` (in cell)
 *  - priority-low: style options defined in `matrix.x/y/coner/body`
 */
export interface MatrixCellStyleOption {
    label?: MatrixLabelOption;
    itemStyle?: ItemStyleOption;
    cursor?: string;
    silent?: boolean | NullUndefined;
    z2?: number;
}
export interface MatrixTooltipFormatterParams {
    componentType: 'matrix';
    matrixIndex: number;
    name: string;
    $vars: ['name', 'xyLocator'];
}
declare class MatrixModel extends ComponentModel<MatrixOption> implements CoordinateSystemHostModel {
    static type: string;
    type: string;
    coordinateSystem: Matrix;
    static layoutMode: "box";
    private _dimModels;
    private _body;
    private _corner;
    static defaultOption: MatrixOption;
    optionUpdated(): void;
    getDimensionModel(dim: 'x' | 'y'): MatrixDimensionModel;
    getBody(): MatrixBodyCorner<'body'>;
    getCorner(): MatrixBodyCorner<'corner'>;
}
export declare class MatrixDimensionModel extends Model<MatrixDimensionOption> {
    dim: MatrixDim;
    getOrdinalMeta(): OrdinalMeta;
}
export default MatrixModel;
