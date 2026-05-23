import ComponentModel from '../../model/Component.js';
import { ComponentOption, BoxLayoutOptionMixin, ZRColor, ShadowOptionMixin, NullUndefined, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin } from '../../util/types.js';
import type Grid from './Grid.js';
import { CoordinateSystemHostModel } from '../CoordinateSystem.js';
import type GlobalModel from '../../model/Global.js';
export declare const OUTER_BOUNDS_DEFAULT: {
    left: number;
    right: number;
    top: number;
    bottom: number;
};
export declare const OUTER_BOUNDS_CLAMP_DEFAULT: string[];
export declare const COORD_SYS_TYPE_CARTESIAN_2D = "cartesian2d";
export interface GridOption extends ComponentOption, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, BoxLayoutOptionMixin, ShadowOptionMixin {
    mainType?: 'grid';
    show?: boolean;
    /**
     * @deprecated Use `grid.outerBounds` instead.
     * Whether grid size contains axis labels. This approach estimates the size by sample labels.
     * It works for most case but it does not strictly contain all labels in some cases.
     */
    containLabel?: boolean;
    /**
     * Define a constrains rect.
     * Axis lines is firstly laid out based on the rect defined by `grid.left/right/top/bottom/width/height`.
     * (for axis line alignment requirements between multiple grids)
     * But if axisLabel and/or axisName overflow the outerBounds, shrink the layout to avoid that overflow.
     *
     * Options:
     *  - 'none': outerBounds is infinity.
     *  - 'same': outerBounds is the same as the layout rect defined by `grid.left/right/top/bottom/width/height`.
     *  - 'auto'/null/undefined: Default. Use `outerBounds`, or 'same' if `containLabel:true`.
     *
     * Note:
     *  `grid.containLabel` is equivalent to `{outerBoundsMode: 'same', outerBoundsContain: 'axisLabel'}`.
     */
    outerBoundsMode?: 'auto' | NullUndefined | 'same' | 'none';
    /**
     * {left, right, top, bottom, width, height}: Define a outerBounds rect, based on:
     *  - the canvas by default.
     *  - or the `dataToLayout` result if a `boxCoordinateSystem` is specified.
     */
    outerBounds?: BoxLayoutOptionMixin;
    /**
     * - 'all': Default. Contains the cartesian rect and axis labels and axis name.
     * - 'axisLabel': Contains the cartesian rect and axis labels. This effect differs slightly from the
     *  previous option `containLabel` but more precise.
     * - 'auto'/null/undefined: Default. be 'axisLabel' if `containLabel:true`, otherwise 'all'.
     */
    outerBoundsContain?: 'all' | 'axisLabel' | 'auto' | NullUndefined;
    /**
     * Available only when `outerBoundsMode` is not 'none'.
     * Offer a constraint to not to shrink the grid rect causing smaller that width/height.
     * A string means percent, like '30%', based on the original rect size
     *  determined by `grid.top/right/bottom/left/width/height`.
     */
    outerBoundsClampWidth?: number | string;
    outerBoundsClampHeight?: number | string;
    backgroundColor?: ZRColor;
    borderWidth?: number;
    borderColor?: ZRColor;
    tooltip?: any;
}
declare class GridModel extends ComponentModel<GridOption> implements CoordinateSystemHostModel {
    static type: string;
    static dependencies: string[];
    static layoutMode: "box";
    coordinateSystem: Grid;
    mergeDefaultAndTheme(option: GridOption, ecModel: GlobalModel): void;
    mergeOption(newOption: GridOption, ecModel: GlobalModel): void;
    static defaultOption: GridOption;
}
export default GridModel;
