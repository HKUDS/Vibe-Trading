import CartesianAxisModel from './AxisModel.js';
import SeriesModel from '../../model/Series.js';
import { LayoutRect } from '../../util/layout.js';
import AxisBuilder, { AxisBuilderCfg, AxisBuilderSharedContext } from '../../component/axis/AxisBuilder.js';
import type Cartesian2D from './Cartesian2D.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { NullUndefined } from 'zrender/lib/core/types.js';
import type Axis2D from './Axis2D.js';
interface CartesianAxisLayout {
    position: AxisBuilderCfg['position'];
    rotation: AxisBuilderCfg['rotation'];
    labelOffset: AxisBuilderCfg['labelOffset'];
    labelDirection: AxisBuilderCfg['labelDirection'];
    tickDirection: AxisBuilderCfg['tickDirection'];
    nameDirection: AxisBuilderCfg['nameDirection'];
    labelRotate: AxisBuilderCfg['labelRotate'];
    z2: number;
}
/**
 * [__CAUTION__]
 *  MUST guarantee: if only the input `rect` and `axis.extent` changed,
 *  only `layout.position` changes.
 *  This character is replied on `grid.contain` calculation in `AxisBuilder`.
 *  @see updateCartesianAxisViewCommonPartBuilder
 *
 * Can only be called after coordinate system creation stage.
 * (Can be called before coordinate system update stage).
 */
export declare function layout(rect: LayoutRect, axisModel: CartesianAxisModel, opt?: {
    labelInside?: boolean;
}): CartesianAxisLayout;
export declare function isCartesian2DDeclaredSeries(seriesModel: SeriesModel): boolean;
/**
 * Note: If pie (or other similar series) use cartesian2d, here
 *  option `seriesModel.get('coordinateSystem') === 'cartesian2d'`
 *  and `seriesModel.coordinateSystem !== cartesian2dCoordSysInstance`
 *  and `seriesModel.boxCoordinateSystem === cartesian2dCoordSysInstance`,
 *  the logic below is probably wrong, therefore skip it temporarily.
 */
export declare function isCartesian2DInjectedAsDataCoordSys(seriesModel: SeriesModel): boolean;
export declare function findAxisModels(seriesModel: SeriesModel): {
    xAxisModel: CartesianAxisModel;
    yAxisModel: CartesianAxisModel;
};
export declare function createCartesianAxisViewCommonPartBuilder(gridRect: LayoutRect, cartesians: Cartesian2D[], axisModel: CartesianAxisModel, api: ExtensionAPI, ctx: AxisBuilderSharedContext | NullUndefined, defaultNameMoveOverlap: boolean | NullUndefined): AxisBuilder;
export declare function updateCartesianAxisViewCommonPartBuilder(axisBuilder: AxisBuilder, gridRect: LayoutRect, axisModel: CartesianAxisModel): void;
export declare type CartesianAxisHashKey = string;
export declare function getCartesianAxisHashKey(axis: Axis2D): CartesianAxisHashKey;
export {};
