import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import { StageHandlerProgressParams, LineStyleOption } from '../../util/types.js';
import Model from '../../model/Model.js';
import Element from 'zrender/lib/Element.js';
import Displayable from 'zrender/lib/graphic/Displayable.js';
import { ILineDraw } from './baseDraw.js';
interface LargeLinesCommonOption {
    polyline?: boolean;
    lineStyle?: LineStyleOption & {
        curveness?: number;
    };
}
/**
 * Data which can support large lines.
 */
declare type LargeLinesData = SeriesData<Model<LargeLinesCommonOption> & {
    seriesIndex?: number;
}>;
declare class LargeLineDraw implements ILineDraw {
    group: graphic.Group;
    private _newAdded;
    /**
     * Update symbols draw by new data
     */
    updateData(data: LargeLinesData): void;
    incrementalPrepareUpdate(data: LargeLinesData): void;
    incrementalUpdate(taskParams: StageHandlerProgressParams, data: LargeLinesData, incrementalId: Displayable['incremental']): void;
    /**
     * @override
     */
    remove(): void;
    eachRendered(cb: (el: Element) => boolean | void): void;
    private _create;
    private _setCommon;
    private _clear;
}
export default LargeLineDraw;
