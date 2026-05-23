import * as graphic from '../../util/graphic.js';
import SeriesData from '../../data/SeriesData.js';
import ChordSeriesModel, { ChordNodeItemOption } from './ChordSeries.js';
import type Model from '../../model/Model.js';
import type { GraphNode } from '../../data/Graph.js';
export default class ChordPiece extends graphic.Sector {
    constructor(data: SeriesData, idx: number, startAngle: number);
    updateData(data: SeriesData, idx: number, startAngle?: number, firstCreate?: boolean): void;
    protected _updateLabel(seriesModel: ChordSeriesModel, itemModel: Model<ChordNodeItemOption>, node: GraphNode): void;
}
