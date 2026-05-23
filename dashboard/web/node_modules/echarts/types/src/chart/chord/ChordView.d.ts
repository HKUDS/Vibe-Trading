import ChartView from '../../view/Chart.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import ChordSeriesModel from './ChordSeries.js';
declare class ChordView extends ChartView {
    static readonly type = "chord";
    readonly type = "chord";
    private _data;
    private _edgeData;
    init(ecModel: GlobalModel, api: ExtensionAPI): void;
    render(seriesModel: ChordSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    renderEdges(seriesModel: ChordSeriesModel, startAngle: number): void;
    dispose(): void;
}
export default ChordView;
