import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import type Displayable from 'zrender/lib/graphic/Displayable.js';
import { StageHandlerProgressParams, LabelOption, ZRStyleProps, BlurScope, DisplayState, DefaultEmphasisFocus } from '../../util/types.js';
import Model from '../../model/Model.js';
import Element from 'zrender/lib/Element.js';
import SeriesModel from '../../model/Series.js';
import { ISymbolDraw, ListForSymbolDraw, SymbolDrawItemModelOption, SymbolDrawUpdateOpt } from './baseDraw.js';
interface SymbolLike extends graphic.Group {
    updateData(data: SeriesData, idx: number, scope?: SymbolDrawSeriesScope, opt?: SymbolDrawUpdateOpt): void;
    fadeOut?(cb: () => void, seriesModel: SeriesModel): void;
}
interface SymbolLikeCtor {
    new (data: SeriesData, idx: number, scope?: SymbolDrawSeriesScope, opt?: SymbolDrawUpdateOpt): SymbolLike;
}
export interface SymbolDrawSeriesScope {
    emphasisItemStyle?: ZRStyleProps;
    blurItemStyle?: ZRStyleProps;
    selectItemStyle?: ZRStyleProps;
    focus?: DefaultEmphasisFocus;
    blurScope?: BlurScope;
    emphasisDisabled?: boolean;
    labelStatesModels: Record<DisplayState, Model<LabelOption>>;
    itemModel?: Model<SymbolDrawItemModelOption>;
    hoverScale?: boolean | number;
    cursorStyle?: string;
    fadeIn?: boolean;
}
declare class SymbolDraw implements ISymbolDraw {
    group: graphic.Group;
    private _data;
    private _SymbolCtor;
    private _seriesScope;
    private _getSymbolPoint;
    private _progressiveEls;
    constructor(SymbolCtor?: SymbolLikeCtor);
    /**
     * Update symbols draw by new data
     */
    updateData(data: ListForSymbolDraw, opt?: SymbolDrawUpdateOpt): void;
    updateLayout(opt?: SymbolDrawUpdateOpt): void;
    incrementalPrepareUpdate(data: ListForSymbolDraw): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, data: ListForSymbolDraw, incrementalId: Displayable['incremental'], opt?: SymbolDrawUpdateOpt): void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    remove(enableAnimation?: boolean): void;
}
export default SymbolDraw;
