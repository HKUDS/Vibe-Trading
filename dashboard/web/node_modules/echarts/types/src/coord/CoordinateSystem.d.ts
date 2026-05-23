import GlobalModel from '../model/Global.js';
import { ParsedModelFinder } from '../util/model.js';
import ExtensionAPI from '../core/ExtensionAPI.js';
import { DimensionDefinitionLoose, ScaleDataValue, DimensionName, NullUndefined, CoordinateSystemDataLayout, CoordinateSystemDataCoord } from '../util/types.js';
import Axis from './Axis.js';
import { BoundingRect } from '../util/graphic.js';
import { MatrixArray } from 'zrender/lib/core/matrix.js';
import ComponentModel from '../model/Component.js';
import { RectLike } from 'zrender/lib/core/BoundingRect.js';
import type { PrepareCustomInfo } from '../chart/custom/CustomSeries.js';
export interface CoordinateSystemCreator {
    create: (ecModel: GlobalModel, api: ExtensionAPI) => CoordinateSystemMaster[];
    dimensions?: DimensionName[];
    getDimensionsInfo?: () => DimensionDefinitionLoose[];
}
/**
 * The instance get from `CoordinateSystemManger` is `CoordinateSystemMaster`.
 * Consider a typical case: `grid` is a `CoordinateSystemMaster`, and it contains
 * one or multiple `cartesian2d`s, which are `CoordinateSystem`s.
 */
export interface CoordinateSystemMaster {
    dimensions: DimensionName[];
    model?: ComponentModel;
    boxCoordinateSystem?: CoordinateSystem;
    update?: (ecModel: GlobalModel, api: ExtensionAPI) => void;
    convertToPixel?(ecModel: GlobalModel, finder: ParsedModelFinder, value: Parameters<CoordinateSystem['dataToPoint']>[0], opt?: unknown): ReturnType<CoordinateSystem['dataToPoint']> | number | NullUndefined;
    convertToLayout?(ecModel: GlobalModel, finder: ParsedModelFinder, value: Parameters<NonNullable<CoordinateSystem['dataToLayout']>>[0], opt?: unknown): ReturnType<NonNullable<CoordinateSystem['dataToLayout']>> | NullUndefined;
    convertFromPixel?(ecModel: GlobalModel, finder: ParsedModelFinder, pixelValue: Parameters<NonNullable<CoordinateSystem['pointToData']>>[0], opt?: unknown): ReturnType<NonNullable<CoordinateSystem['pointToData']>> | NullUndefined;
    containPoint(point: number[]): boolean;
    getAxes?: () => Axis[];
    axisPointerEnabled?: boolean;
    getTooltipAxes?: (dim: DimensionName | 'auto') => {
        baseAxes: Axis[];
        otherAxes: Axis[];
    };
    /**
     * Get layout rect or coordinate system
     */
    getRect?: () => RectLike;
}
/**
 * For example: cartesian is CoordinateSystem.
 * series.coordinateSystem is CoordinateSystem.
 */
export interface CoordinateSystem {
    type: string;
    /**
     * Master of coordinate system. For example:
     * Grid is master of cartesian.
     */
    master?: CoordinateSystemMaster;
    dimensions: DimensionName[];
    model?: ComponentModel;
    /**
     * @param data
     * @param reserved Defined by the coordinate system itself
     * @param out Fill it if passing, and return. For performance optimization.
     * @return Point in global pixel coordinate system.
     *  An invalid returned point should be represented by `[NaN, NaN]`,
     *  rather than `null/undefined`.
     */
    dataToPoint(data: CoordinateSystemDataCoord, opt?: unknown, out?: number[]): number[];
    /**
     * @param data See the meaning in `dataToPoint`.
     * @param reserved Defined by the coordinate system itself
     * @param out Fill it if passing, and return. For performance optimization. Vary by different coord sys.
     * @return Layout in global pixel coordinate system.
     *  An invalid returned rect should be represented by `{x: NaN, y: NaN, width: NaN, height: NaN}`,
     *  Never return `null/undefined`.
     */
    dataToLayout?(data: CoordinateSystemDataCoord, opt?: unknown, out?: CoordinateSystemDataLayout): CoordinateSystemDataLayout;
    /**
     * Some coord sys (like Parallel) might do not have `pointToData`,
     * or the meaning of this kind of features is not clear yet.
     * @param point point Point in global pixel coordinate system.
     * @param out Fill it if passing, and return. For performance optimization.
     * @return data
     *  An invalid returned data should be represented by `[NaN, NaN]` or `NaN`,
     *  rather than `null/undefined`, which represents not-applicable in `convertFromPixel`.
     *  Return `OrdinalNumber` in ordianal (category axis) case.
     *  Return timestamp in time axis.
     */
    pointToData?(point: number[], opt?: unknown, out?: number | number[]): number | number[];
    containPoint(point: number[]): boolean;
    getAxes?: () => Axis[];
    getAxis?: (dim?: DimensionName) => Axis;
    /**
     * FIXME: Remove this method? See details in `Cartesian2D['getBaseAxis']`
     */
    getBaseAxis?: () => Axis;
    getOtherAxis?: (baseAxis: Axis) => Axis;
    clampData?: (data: ScaleDataValue[], out?: number[]) => number[];
    getArea?: (tolerance?: number) => CoordinateSystemClipArea;
    shouldClip?: () => boolean;
    /**
     * Optional; e.g. only for `GeoLikeCoordSys`.
     * External geo like extensions are required to implements it.
     * This is a rect in data space.
     * For historicall reason, the name is `getBoundingRect` - preserve it for backward compatibility.
     * @see VIEW_COORD_SYS_TRANS_RAW
     */
    getBoundingRect?: () => BoundingRect;
    /**
     * Optional; e.g. only for `GeoLikeCoordSys`.
     * External geo like extensions are required to implements it.
     * @see VIEW_COORD_SYS_TRANS_RAW
     */
    getViewRect?: () => BoundingRect;
    /**
     * Optional; e.g. only for `GeoLikeCoordSys`.
     * External geo like extensions are required to implements it.
     */
    getRoamTransform?: () => MatrixArray;
    getAxesByScale?: (scaleType: string) => Axis[];
    prepareCustoms?: PrepareCustomInfo;
}
/**
 * Like GridModel, PolarModel, ...
 */
export interface CoordinateSystemHostModel extends ComponentModel {
    coordinateSystem?: CoordinateSystemMaster;
}
/**
 * Clip area will be returned by getArea of CoordinateSystem.
 * It is used to clip the graphic elements with the contain methods.
 */
export interface CoordinateSystemClipArea {
    x: number;
    y: number;
    width: number;
    height: number;
    contain(x: number, y: number): boolean;
}
export declare function isCoordinateSystemType<T extends CoordinateSystem, S = T['type']>(coordSys: CoordinateSystem, type: S): coordSys is T;
export interface GeoLikeCoordSys extends CoordinateSystem {
    dimensions: ['lng', 'lat'];
    getViewRect: CoordinateSystem['getViewRect'];
}
export declare function isGeoLikeCoordSys(coordSys: CoordinateSystem): coordSys is GeoLikeCoordSys;
