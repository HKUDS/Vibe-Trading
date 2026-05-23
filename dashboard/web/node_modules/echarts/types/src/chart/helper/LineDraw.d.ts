import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import { StageHandlerProgressParams, ZRStyleProps, DisplayState, LabelOption, DefaultEmphasisFocus, BlurScope } from '../../util/types.js';
import Displayable from 'zrender/lib/graphic/Displayable.js';
import Model from '../../model/Model.js';
import Element from 'zrender/lib/Element.js';
import { ILineDraw, ListForLineDraw } from './baseDraw.js';
interface LineLike extends graphic.Group {
    updateData(data: SeriesData, idx: number, scope?: LineDrawSeriesScope): void;
    updateLayout(data: SeriesData, idx: number): void;
    fadeOut?(cb: () => void): void;
}
interface LineLikeCtor {
    new (data: SeriesData, idx: number, scope?: LineDrawSeriesScope): LineLike;
}
export interface LineDrawSeriesScope {
    lineStyle?: ZRStyleProps;
    emphasisLineStyle?: ZRStyleProps;
    blurLineStyle?: ZRStyleProps;
    selectLineStyle?: ZRStyleProps;
    labelStatesModels: Record<DisplayState, Model<LabelOption>>;
    focus?: DefaultEmphasisFocus;
    blurScope?: BlurScope;
    emphasisDisabled?: boolean;
}
declare class LineDraw implements ILineDraw {
    group: graphic.Group;
    private _LineCtor;
    private _lineData;
    private _seriesScope;
    private _progressiveEls;
    constructor(LineCtor?: LineLikeCtor);
    updateData(lineData: ListForLineDraw): void;
    updateLayout(): void;
    incrementalPrepareUpdate(lineData: ListForLineDraw): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, lineData: ListForLineDraw, incrementalId: Displayable['incremental']): void;
    remove(): void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    private _doAdd;
    private _doUpdate;
}
export default LineDraw;
