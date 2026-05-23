import ChartView from '../../view/Chart.js';
import MapSeries from './MapSeries.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { Payload, RoamPayload } from '../../util/types.js';
declare class MapView extends ChartView {
    static readonly type = "map";
    readonly type = "map";
    private _mapDraw;
    render(mapModel: MapSeries, ecModel: GlobalModel, api: ExtensionAPI, payload: Payload): void;
    /**
     * @implements RoamHostView['__updateOnOwnRoam']
     */
    __updateOnOwnRoam(payload: RoamPayload, model: MapSeries, api: ExtensionAPI): void;
    remove(): void;
    dispose(): void;
    private _clearMapDraw;
    private _renderSymbols;
}
export default MapView;
