import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import SeriesModel from '../../model/Series.js';
import { StageHandlerProgressParams } from '../../util/types.js';
import Element from 'zrender/lib/Element.js';
import Displayable from 'zrender/lib/graphic/Displayable.js';
import { ISymbolDraw, SymbolDrawUpdateOpt } from './baseDraw.js';
declare class LargeSymbolDraw implements ISymbolDraw {
    group: graphic.Group;
    private _newAdded;
    private _data;
    /**
     * Update symbols draw by new data
     */
    updateData(data: SeriesData, opt?: SymbolDrawUpdateOpt): void;
    updateLayout(opt: SymbolDrawUpdateOpt): void;
    incrementalPrepareUpdate(data: SeriesData): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, data: SeriesData<SeriesModel>, incrementalId: Displayable['incremental'], opt: SymbolDrawUpdateOpt): void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    private _create;
    private _setCommon;
    remove(): void;
    private _clear;
}
export default LargeSymbolDraw;
