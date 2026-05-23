import ChartView from '../../view/Chart.js';
import ScatterSeriesModel from './ScatterSeries.js';
import GlobalModel from '../../model/Global.js';
import ExtensionAPI from '../../core/ExtensionAPI.js';
import SeriesData from '../../data/SeriesData.js';
import { TaskProgressParams } from '../../core/task.js';
import Element from 'zrender/lib/Element.js';
import { ISymbolDraw } from '../helper/baseDraw.js';
declare class ScatterView extends ChartView {
    static readonly type = "scatter";
    type: string;
    _finished: boolean;
    _isLargeDraw: boolean;
    _symbolDraw: ISymbolDraw;
    render(seriesModel: ScatterSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    incrementalPrepareRender(seriesModel: ScatterSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): void;
    incrementalRender(taskParams: TaskProgressParams, seriesModel: ScatterSeriesModel, ecModel: GlobalModel): void;
    /**
     * See also VIEW_COORD_SYS_ANIMATION
     */
    updateTransform(seriesModel: ScatterSeriesModel, ecModel: GlobalModel, api: ExtensionAPI): {
        readonly update: true;
    };
    eachRendered(cb: (el: Element) => boolean | void): void;
    _updateSymbolDraw(data: SeriesData, seriesModel: ScatterSeriesModel): ISymbolDraw;
    remove(ecModel: GlobalModel, api: ExtensionAPI): void;
    dispose(): void;
}
export default ScatterView;
