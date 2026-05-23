import ChartView from '../../view/Chart.js';
import TreeSeriesModel from './TreeSeries.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import { RoamPayload } from '../../util/types.js';
declare class TreeView extends ChartView {
    static readonly type = "tree";
    readonly type = "tree";
    private _mainGroup;
    private _controller;
    private _data;
    private _min;
    private _max;
    private _firstRender;
    init(ecModel: GlobalModel, api: ExtensionAPI): void;
    render(seriesModel: TreeSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    __updateOnOwnRoam(payload: RoamPayload, seriesModel: TreeSeriesModel, api: ExtensionAPI): void;
    private _updateViewCoordSys;
    _updateNodeAndLinkScale(seriesModel: TreeSeriesModel): void;
    dispose(): void;
    remove(): void;
}
export default TreeView;
