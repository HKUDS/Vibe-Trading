import SeriesModel from '../../model/Series.js';
import { SeriesOption, BoxLayoutOptionMixin, SeriesEncodeOptionMixin, OptionDataItemObject, OptionDataValueNumeric, ParsedValue, SeriesOnGeoOptionMixin, StatesOptionMixin, SeriesLabelOption, StatesMixinBase, CallbackDataParams, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, RoamHostModel } from '../../util/types.js';
import { Dictionary, NullUndefined } from 'zrender/lib/core/types.js';
import GeoModel, { GeoCommonOptionMixin, GeoItemStyleOption } from '../../coord/geo/GeoModel.js';
import SeriesData from '../../data/SeriesData.js';
import Model from '../../model/Model.js';
import Geo from '../../coord/geo/Geo.js';
import { ECSymbol } from '../../util/symbol.js';
import { LegendIconParams } from '../../component/legend/LegendModel.js';
import { Group } from '../../util/graphic.js';
import GlobalModel from '../../model/Global.js';
export interface MapStateOption<TCbParams = never> {
    itemStyle?: GeoItemStyleOption<TCbParams>;
    label?: SeriesLabelOption;
}
export interface MapDataItemOption extends MapStateOption, StatesOptionMixin<MapStateOption, StatesMixinBase>, OptionDataItemObject<OptionDataValueNumeric> {
    cursor?: string;
    silent?: boolean;
}
export declare type MapValueCalculationType = 'sum' | 'average' | 'min' | 'max';
export declare type MapSeriesGroup = {
    r: MapSeries[];
    f: MapSeries[];
};
declare type AllMapSeriesGroups = Dictionary<MapSeriesGroup>;
export interface MapSeriesOption extends SeriesOption<MapStateOption<CallbackDataParams>, StatesMixinBase>, MapStateOption<CallbackDataParams>, GeoCommonOptionMixin, SeriesOnGeoOptionMixin, ComponentOnCalendarOptionMixin, ComponentOnMatrixOptionMixin, BoxLayoutOptionMixin, SeriesEncodeOptionMixin {
    type?: 'map';
    coordinateSystem?: string;
    silent?: boolean;
    markLine?: any;
    markPoint?: any;
    markArea?: any;
    mapValueCalculation?: MapValueCalculationType;
    showLegendSymbol?: boolean;
    geoCoord?: Dictionary<number[]>;
    data?: (OptionDataValueNumeric | OptionDataValueNumeric[] | MapDataItemOption)[];
    nameProperty?: string;
}
export declare const SERIES_TYPE_MAP = "map";
declare class MapSeries extends SeriesModel<MapSeriesOption> implements RoamHostModel {
    static readonly type: string;
    readonly type: string;
    static dependencies: string[];
    static layoutMode: "box";
    coordinateSystem: Geo;
    originalData: SeriesData;
    seriesGroup: MapSeriesGroup | NullUndefined;
    getInitialData(this: MapSeries, option: MapSeriesOption): SeriesData;
    /**
     * If no host geo model, return null, which means using a
     * inner exclusive geo model.
     */
    getHostGeoModel(): GeoModel;
    getMapType(): string;
    getRawValue(dataIndex: number): ParsedValue;
    /**
     * Get model of region
     */
    getRegionModel(regionName: string): Model<MapDataItemOption>;
    /**
     * Map tooltip formatter
     */
    formatTooltip(dataIndex: number, multipleSeries: boolean, dataType: string): import("../../component/tooltip/tooltipMarkup").TooltipMarkupSection;
    getTooltipPosition: (this: MapSeries, dataIndex: number) => number[];
    getLegendIcon(opt: LegendIconParams): ECSymbol | Group;
    __ownRoamView(): import("../../coord/View").default;
    static defaultOption: MapSeriesOption;
}
/**
 * Has exclusive geo, rahter than depends on a separate geo componet.
 */
export declare function mapSeriesGroupHasOwnGeo(groupKey: string): boolean;
export declare function mapSeriesNeedsDrawMap(mapSeries: MapSeries): boolean;
export declare function getMainMapSeries(mapSeriesGroup: MapSeriesGroup): MapSeries | NullUndefined;
/**
 * @tutorial [MAP_SERIES_GROUP]
 *  - For map series that reference external geo components (typically via `geoIndex` or `geoId` in ec option),
 *    a map series group is all map series that reference to the same geo component.
 *  - For other map series,
 *    a map series group is all map series that use the same `map` in ec option.
 *  NOTICE: series filtering (typically by legend) matters:
 *   If this method is executed before series filtering, all series are included,
 *   otherwise, series filtered out are excluded.
 *   When legend disables the original first series, the original second series takes the responsibility
 *   to render map (via its `MapDraw`).
 */
export declare function buildAllMapSeriesGroups(ecModel: GlobalModel, beforeSeriesFiltering?: boolean): AllMapSeriesGroups;
export default MapSeries;
