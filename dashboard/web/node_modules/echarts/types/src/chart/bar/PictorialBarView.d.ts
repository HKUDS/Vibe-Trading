import ChartView from '../../view/Chart.js';
import PictorialBarSeriesModel from './PictorialBarSeries.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import GlobalModel from '../../model/Global.js';
declare class PictorialBarView extends ChartView {
    static readonly type = "pictorialBar";
    readonly type = "pictorialBar";
    private _data;
    render(seriesModel: PictorialBarSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): import("../../util/types").ViewRootGroup;
    remove(ecModel: GlobalModel, api: ExtensionAPI): void;
}
export default PictorialBarView;
