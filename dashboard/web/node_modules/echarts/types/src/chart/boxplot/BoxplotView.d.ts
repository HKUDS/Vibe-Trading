import ChartView from '../../view/Chart.js';
import BoxplotSeriesModel from './BoxplotSeries.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
declare class BoxplotView extends ChartView {
    static readonly type = "boxplot";
    readonly type = "boxplot";
    private _data;
    render(seriesModel: BoxplotSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    remove(ecModel: GlobalModel): void;
}
export default BoxplotView;
