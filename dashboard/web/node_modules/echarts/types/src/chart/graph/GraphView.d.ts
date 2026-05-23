import ChartView from '../../view/Chart.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import GraphSeriesModel from './GraphSeries.js';
import { RoamHostView, RoamPayload } from '../../util/types.js';
declare class GraphView extends ChartView implements RoamHostView {
    static readonly type = "graph";
    readonly type = "graph";
    private _symbolDraw;
    private _lineDraw;
    private _controller;
    private _firstRender;
    private _model;
    private _api;
    private _layoutTimeout;
    private _layouting;
    private _mainGroup;
    private _active;
    init(ecModel: GlobalModel, api: ExtensionAPI): void;
    render(seriesModel: GraphSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    dispose(): void;
    private _startForceLayoutIteration;
    /**
     * @implements RoamHostView['__updateOnOwnRoam']
     */
    __updateOnOwnRoam(payload: RoamPayload, seriesModel: GraphSeriesModel, api: ExtensionAPI): void;
    private _updateNodeAndLinkScale;
    updateLayout(seriesModel: GraphSeriesModel): void;
    remove(): void;
    /**
     * Get thumbnail data structure only if supported.
     */
    private _getThumbnailInfo;
    private _updateThumbnailWindow;
    private _renderThumbnail;
}
export default GraphView;
