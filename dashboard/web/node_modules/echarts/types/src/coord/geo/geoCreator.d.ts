import Geo from './Geo.js';
import GeoModel, { GeoOption, RegionOption } from './GeoModel.js';
import MapSeries, { MapSeriesOption } from '../../chart/map/MapSeries.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { CoordinateSystemCreator } from '../CoordinateSystem.js';
import { NameMap } from './geoTypes.js';
import type GlobalModel from '../../model/Global.js';
import type ComponentModel from '../../model/Component.js';
export declare type resizeGeoType = typeof resizeGeo;
export declare type MapOrGeoModel = (GeoModel | MapSeries) & ComponentModel<GeoOption | MapSeriesOption>;
/**
 * Resize method bound to the geo
 */
declare function resizeGeo(this: Geo, geoModel: MapOrGeoModel, api: ExtensionAPI): void;
declare class GeoCreator implements CoordinateSystemCreator {
    dimensions: ["lng", "lat"];
    create(ecModel: GlobalModel, api: ExtensionAPI): Geo[];
    /**
     * Fill given regions array
     */
    getFilledRegions(originRegionArr: RegionOption[], mapName: string, nameMap: NameMap, nameProperty: string): RegionOption[];
}
declare const geoCreator: GeoCreator;
export default geoCreator;
