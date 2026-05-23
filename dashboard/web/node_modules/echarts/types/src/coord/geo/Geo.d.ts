import View from '../View.js';
import { Region } from './Region.js';
import { GeoProjection, GeoResource, NameMap } from './geoTypes.js';
import GlobalModel from '../../model/Global.js';
import { ParsedModelFinder } from '../../util/model.js';
import type GeoModel from './GeoModel.js';
import { resizeGeoType } from './geoCreator.js';
import type ExtensionAPI from '../../core/ExtensionAPI.js';
import { CoordinateSystemMaster, GeoLikeCoordSys } from '../CoordinateSystem.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import Transformable from 'zrender/lib/core/Transformable.js';
import { MatrixArray } from 'zrender/lib/core/matrix.js';
import { NullUndefined } from 'zrender/lib/core/types.js';
export declare const geo2DDimensions: ['lng', 'lat'];
declare class Geo extends Transformable// See VIEW_COORD_SYS_TRANS_OVERALL_BACKWARD_COMPATIBILITY
 implements CoordinateSystemMaster, GeoLikeCoordSys {
    dimensions: ['lng', 'lat'];
    type: string;
    readonly map: string;
    readonly resourceType: GeoResource['type'];
    readonly view: View;
    readonly name: string;
    private _nameCoordMap;
    private _regionsMap;
    private _clip;
    readonly regions: Region[];
    readonly aspectScale: number;
    projection: GeoProjection;
    model: GeoModel | NullUndefined;
    resize: resizeGeoType;
    constructor(name: string, map: string, opt: {
        projection?: GeoProjection;
        nameMap?: NameMap;
        nameProperty?: string;
        aspectScale?: number;
        api: ExtensionAPI;
        ecModel: GlobalModel;
        clip?: boolean;
    });
    getRegion(name: string): Region;
    getRegionByCoord(coord: number[]): Region;
    /**
     * Add geoCoord for indexing by name
     */
    addGeoCoord(name: string, geoCoord: number[]): void;
    /**
     * Get geoCoord by name
     */
    getGeoCoord(name: string): number[];
    dataToPoint(data: number[] | string, noRoam?: boolean, out?: number[]): number[];
    pointToData(point: number[], reserved?: unknown, out?: number[]): number[];
    convertToPixel(ecModel: GlobalModel, finder: ParsedModelFinder, value: number[]): number[];
    convertFromPixel(ecModel: GlobalModel, finder: ParsedModelFinder, pixel: number[]): number[];
    containPoint(point: number[]): boolean;
    getArea(tolerance?: number): BoundingRect;
    shouldClip(): boolean;
    /**
     * @implements CoordinateSystem['getBoundingRect']
     */
    getBoundingRect(): BoundingRect;
    /**
     * @implements CoordinateSystem['getViewRect']
     */
    getViewRect(): BoundingRect;
    /**
     * @implements CoordinateSystem['getRoamTransform']
     */
    getRoamTransform(): MatrixArray;
}
export default Geo;
