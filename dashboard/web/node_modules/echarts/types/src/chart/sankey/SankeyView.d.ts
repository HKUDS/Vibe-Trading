import { RoamHostView, RoamPayload } from '../../util/types.js';
import SankeySeriesModel from './SankeySeries.js';
import ChartView from '../../view/Chart.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
declare class SankeyView extends ChartView implements RoamHostView {
    static readonly type = "sankey";
    readonly type = "sankey";
    private _mainGroup;
    private _data;
    private _controller;
    private _firstRender;
    init(ecModel: GlobalModel, api: ExtensionAPI): void;
    render(seriesModel: SankeySeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    __updateOnOwnRoam(payload: RoamPayload, seriesModel: SankeySeriesModel, api: ExtensionAPI): void;
    dispose(): void;
    private _updateViewCoordSys;
}
export default SankeyView;
